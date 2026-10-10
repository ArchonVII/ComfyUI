import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import torch

PATH = Path(__file__).resolve().parents[1] / 'imaging.py'
spec = importlib.util.spec_from_file_location('workbench_imaging', PATH)
imaging = importlib.util.module_from_spec(spec) if PATH.exists() else None
if imaging:
    spec.loader.exec_module(imaging)


class ImagingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(imaging, 'imaging nodes must exist')

    def test_full_letterbox_batch_and_owned_outputs(self):
        source = torch.ones(2, 4, 8, 3)
        out, mask, preview, metadata = imaging.ArchReferencePrepare().prepare(source, width=8, height=8, padding=0)
        self.assertEqual(tuple(out.shape), (2, 8, 8, 3))
        self.assertTrue(torch.all(out[:, :2] == 0))
        self.assertTrue(torch.all(out[:, 2:6] == 1))
        self.assertTrue(torch.all(mask[:, 2:6] == 1))
        self.assertEqual(json.loads(metadata)['items'][1]['crop_xyxy'], [0, 0, 8, 4])
        self.assertNotEqual(preview.data_ptr(), source.data_ptr())
        self.assertTrue(torch.all(source == 1))

    def test_subject_mask_and_batch_broadcast(self):
        source = torch.ones(2, 10, 12, 3)
        mask = torch.zeros(1, 10, 12)
        mask[:, 2:6, 3:9] = 1
        out, transformed, _, metadata = imaging.ArchReferencePrepare().prepare(source, mode='subject', width=6, height=4, padding=0, mask=mask)
        self.assertEqual(json.loads(metadata)['items'][0]['crop_xyxy'], [3, 2, 9, 6])
        self.assertTrue(torch.all(transformed == 1))
        self.assertEqual(tuple(out.shape), (2, 4, 6, 3))

    def test_missing_empty_and_mismatched_mask_fail(self):
        node = imaging.ArchReferencePrepare()
        source = torch.ones(1, 10, 12, 3)
        for mask in (None, torch.zeros(1, 10, 12), torch.ones(1, 2, 2)):
            with self.assertRaisesRegex(ValueError, '(?i)mask'):
                node.prepare(source, mode='subject', mask=mask)

    def test_face_detection_selection_and_no_face_failure(self):
        faces = np.array([[1, 1, 4, 4, .8], [6, 2, 2, 2, .95]])
        with patch.object(imaging, '_detect_faces', return_value=faces) as detect:
            out = imaging.ArchReferencePrepare().prepare(torch.ones(2, 10, 12, 3), mode='face', padding=0,
                face_selection={'selection': 'highest_confidence', 'index': 0, 'threshold': .75})
            self.assertEqual(json.loads(out[3])['items'][0]['crop_xyxy'], [6, 2, 8, 4])
            self.assertEqual(detect.call_count, 2)
            self.assertEqual(detect.call_args.args[1], .75)
        with patch.object(imaging, '_detect_faces', return_value=None):
            with self.assertRaisesRegex(ValueError, 'No face'):
                imaging.ArchReferencePrepare().prepare(torch.ones(1, 10, 12, 3), mode='face')

    def test_contact_sheet_all_members_and_aspect(self):
        red = torch.zeros(3, 4, 8, 3)
        red[..., 0] = 1
        out, = imaging.ArchReferenceContactSheet().sheet(subject=red, style=torch.ones(1, 8, 4, 3), tile_width=80, tile_height=80, columns=2,
            manifest=json.dumps({'lanes': {'subject': {'selected_name': 'person.png'}, 'style': {'selected_name': 'art.png'}}}))
        self.assertEqual(out.shape[2], 160)
        self.assertGreater(out.shape[1], 160)
        # First tile is centered letterbox: a 2:1 source occupies only 40 rows.
        self.assertEqual(float(out[0, 10, 40, 0]), 0)
        self.assertEqual(float(out[0, 30, 40, 0]), 1)
        self.assertEqual(float(out[0, 30, 120, 0]), 1)

    def test_contact_sheet_requires_an_image(self):
        with self.assertRaisesRegex(ValueError, 'image'):
            imaging.ArchReferenceContactSheet().sheet()


if __name__ == '__main__':
    unittest.main()
