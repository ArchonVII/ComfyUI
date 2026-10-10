"""Local reference layout and reversible crop preparation; no image caches."""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch
import torch.nn.functional as F


def _image(value):
    if not isinstance(value, torch.Tensor) or value.ndim != 4 or value.shape[-1] not in (3, 4) or min(value.shape[:3]) < 1:
        raise ValueError('Expected a nonempty IMAGE batch [B,H,W,3 or 4].')
    return value.detach().to(device='cpu', dtype=torch.float32)[..., :3].clamp(0, 1)


def _letterbox(image, width, height, value=0):
    h, w = image.shape[:2]
    scale = min(width / w, height / h)
    rw, rh = min(width, max(1, round(w * scale))), min(height, max(1, round(h * scale)))
    x, y = (width - rw) // 2, (height - rh) // 2
    result = torch.full((height, width, image.shape[-1]), float(value))
    resized = F.interpolate(image.permute(2, 0, 1).unsqueeze(0), size=(rh, rw), mode='bilinear', align_corners=False)
    result[y:y + rh, x:x + rw] = resized[0].permute(1, 2, 0)
    return result, [x, y, x + rw, y + rh]


def _detect_faces(image, threshold):
    # Reuse local YuNet detection without importing sibling web routes. The
    # bounded helper is an optional live-install enhancement, not a repo dependency.
    sibling = Path(__file__).resolve().parents[1] / 'comfyui_identity_score'
    helper = sibling / 'face_detection.py'
    model = sibling / 'models' / 'face_detection_yunet_2023mar.onnx'
    if not model.is_file():
        raise ValueError('Face preparation requires the existing local Identity Score YuNet detector and model. No models are downloaded.')
    bounded = helper.is_file()
    if not bounded:
        helper = sibling.parent / 'comfyui_arch_image_tools' / 'face_identity.py'
    if not helper.is_file():
        raise ValueError('Face preparation requires the local Arch Image Tools detector. No models are downloaded.')
    spec = importlib.util.spec_from_file_location('arch_reference_shared_face_detection', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bgr = np.ascontiguousarray((image.numpy() * 255).astype(np.uint8)[..., ::-1])
    return module.detect_face_rows(bgr, model, threshold) if bounded else module._detect_faces(bgr, threshold)


class ArchReferencePrepare:
    CATEGORY = 'Arch/Reference Workbench'
    FUNCTION = 'prepare'
    RETURN_TYPES = ('IMAGE', 'MASK', 'IMAGE', 'STRING')
    RETURN_NAMES = ('image', 'mask', 'crop_preview', 'metadata')
    DESCRIPTION = 'Crop each batch member using a mask or local face detector, then fit without distortion. Mask is coverage when no mask is supplied; crop coordinates are exclusive xyxy.'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'image': ('IMAGE',), 'mode': (['full', 'subject', 'face'],),
            'width': ('INT', {'default': 512, 'min': 16, 'max': 8192}),
            'height': ('INT', {'default': 512, 'min': 16, 'max': 8192}),
            'padding': ('FLOAT', {'default': .1, 'min': 0, 'max': 2, 'step': .01, 'tooltip': 'Extra crop margin as a fraction of the detected box per side.'}),
            'pad_value': ('FLOAT', {'default': 0, 'min': 0, 'max': 1, 'step': .01})},
            'optional': {'mask': ('MASK',), 'face_selection': ('ARCH_FACE_SELECTION',)}}

    def prepare(self, image, mode='full', width=512, height=512, padding=.1, pad_value=0., mask=None, face_selection=None):
        image = _image(image)
        count, h, w, _ = image.shape
        width, height = int(width), int(height)
        if mode not in ('full', 'subject', 'face'):
            raise ValueError(f'Unknown crop mode: {mode}')
        if not 1 <= width <= 8192 or not 1 <= height <= 8192 or not 0 <= float(padding) <= 2 or not 0 <= float(pad_value) <= 1:
            raise ValueError('Invalid target size or padding controls.')
        if mask is None:
            if mode == 'subject':
                raise ValueError('Subject mode requires a MASK; connect a foreground mask.')
            masks = torch.ones((count, h, w))
        else:
            masks = mask.detach().to(device='cpu', dtype=torch.float32)
            if masks.ndim == 2:
                masks = masks.unsqueeze(0)
            if masks.ndim != 3 or tuple(masks.shape[1:]) != (h, w) or masks.shape[0] not in (1, count):
                raise ValueError('MASK must match image dimensions and have one or matching batch members.')
            masks = masks.clamp(0, 1).expand(count, -1, -1)
        selection = face_selection or {'selection': 'largest', 'index': 0, 'threshold': .7}
        prepared, transformed, previews, items = [], [], [], []
        for i, source in enumerate(image):
            box = [0, 0, w, h]
            if mode == 'subject':
                points = torch.nonzero(masks[i] > .5)
                if not len(points):
                    raise ValueError(f'Subject MASK for batch member {i} has no foreground above 0.5.')
                lo, hi = points.min(0).values, points.max(0).values
                box = [int(lo[1]), int(lo[0]), int(hi[1]) + 1, int(hi[0]) + 1]
            elif mode == 'face':
                order = selection.get('selection', 'largest')
                if order not in ('largest', 'highest_confidence'):
                    raise ValueError(f'Unknown face selection: {order}')
                faces = _detect_faces(source, float(selection.get('threshold', .7)))
                if faces is None or not len(faces):
                    raise ValueError(f'No face detected in batch member {i}; use a clearer face reference.')
                faces = sorted(faces, key=lambda f: float(f[-1]) if order == 'highest_confidence' else float(f[2] * f[3]), reverse=True)
                index = int(selection.get('index', 0))
                if index < 0 or index >= len(faces):
                    raise ValueError(f'Face index {index} unavailable in batch member {i}; detected {len(faces)} face(s).')
                x, y, fw, fh = map(float, faces[index][:4])
                box = [x, y, x + fw, y + fh]
            x1, y1, x2, y2 = box
            px, py = (x2 - x1) * float(padding), (y2 - y1) * float(padding)
            x1, y1 = max(0, math.floor(x1 - px)), max(0, math.floor(y1 - py))
            x2, y2 = min(w, math.ceil(x2 + px)), min(h, math.ceil(y2 + py))
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f'Crop for batch member {i} is outside the image.')
            output, content = _letterbox(source[y1:y2, x1:x2], width, height, pad_value)
            output_mask, _ = _letterbox(masks[i, y1:y2, x1:x2, None], width, height)
            preview = source.clone()
            color = torch.tensor([1., .15, .05])
            preview[y1:min(y1 + 2, y2), x1:x2] = color
            preview[max(y1, y2 - 2):y2, x1:x2] = color
            preview[y1:y2, x1:min(x1 + 2, x2)] = color
            preview[y1:y2, max(x1, x2 - 2):x2] = color
            prepared.append(output)
            transformed.append(output_mask[..., 0])
            previews.append(preview)
            items.append({'batch_index': i, 'original_size': [w, h], 'crop_xyxy': [x1, y1, x2, y2], 'content_xyxy': content})
        metadata = {'mode': mode, 'target_size': [width, height], 'padding': float(padding), 'items': items}
        if mode == 'face':
            metadata['face_selection'] = selection
        return torch.stack(prepared), torch.stack(transformed), torch.stack(previews), json.dumps(metadata)


def _wrap_caption(text, font, width):
    lines, line = [], ''
    for char in str(text):
        if char in '\r\n':
            lines.append(line)
            line = ''
        elif line and font.getlength(line + char) > width:
            lines.append(line)
            line = char
        else:
            line += char
    return lines + [line]


class ArchReferenceContactSheet:
    CATEGORY = 'Arch/Reference Workbench'
    FUNCTION = 'sheet'
    RETURN_TYPES = ('IMAGE',)
    RETURN_NAMES = ('contact_sheet',)
    DESCRIPTION = 'Show every connected reference batch member with role and filename captions, preserving aspect ratio.'

    @classmethod
    def INPUT_TYPES(cls):
        optional = {role: ('IMAGE',) for role in ('subject', 'clothing', 'environment', 'style', 'images')}
        optional.update({'selected_name': ('STRING', {'forceInput': True}), 'manifest': ('STRING', {'forceInput': True})})
        return {'required': {'tile_width': ('INT', {'default': 256, 'min': 64, 'max': 2048}),
            'tile_height': ('INT', {'default': 256, 'min': 64, 'max': 2048}),
            'columns': ('INT', {'default': 2, 'min': 1, 'max': 16})}, 'optional': optional}

    def sheet(self, tile_width=256, tile_height=256, columns=2, subject=None, clothing=None, environment=None, style=None, images=None, selected_name='', manifest=''):
        if not 16 <= int(tile_width) <= 2048 or not 16 <= int(tile_height) <= 2048 or not 1 <= int(columns) <= 16:
            raise ValueError('Invalid contact sheet dimensions.')
        tile_width, tile_height, columns = int(tile_width), int(tile_height), int(columns)
        data = json.loads(manifest) if manifest else {}
        lanes = data.get('lanes', {})
        font = ImageFont.load_default(size=14)
        entries = []
        for role, batch in [('subject', subject), ('clothing', clothing), ('environment', environment), ('style', style), ('images', images)]:
            if batch is None:
                continue
            info = lanes.get(role, {})
            if info.get('enabled') is False:
                continue
            name = info.get('selected_name') or info.get('selected_file') or info.get('path') or selected_name
            name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
            batch = _image(batch)
            for index, member in enumerate(batch):
                label = role + (f' [{index + 1}/{len(batch)}]' if len(batch) > 1 else '')
                if name:
                    label += ': ' + name
                lines = _wrap_caption(label, font, tile_width - 12)
                entries.append((member, lines))
        if not entries:
            raise ValueError('Connect at least one enabled reference image.')
        columns = min(columns, len(entries))
        caption_height = max(len(lines) for _, lines in entries) * 18 + 12
        row_height = tile_height + caption_height
        canvas = Image.new('RGB', (columns * tile_width, math.ceil(len(entries) / columns) * row_height), (0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        for index, (member, lines) in enumerate(entries):
            x, y = index % columns * tile_width, index // columns * row_height
            tile, _ = _letterbox(member, tile_width, tile_height)
            canvas.paste(Image.fromarray((tile.numpy() * 255).round().astype(np.uint8)), (x, y))
            draw.multiline_text((x + 6, y + tile_height + 4), '\n'.join(lines), font=font, fill='white', spacing=4)
        return (torch.from_numpy(np.asarray(canvas).copy()).float().div(255).unsqueeze(0),)
