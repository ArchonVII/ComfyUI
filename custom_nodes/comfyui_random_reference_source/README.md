# arch-Random Reference Image Source

This local ComfyUI package loads one reference image from a folder or an explicit image selection. It supports random-per-queue, seeded, and sequential selection while keeping the existing `RandomReferenceImageSource` and `ReferenceLanePack` workflow node types stable.

## Favorites

Configure the node's folder or selected images, enter optional text in **favorite_prompt**, then use:

- **Save new favorite…** to create a named folder or image-set favorite.
- **Update favorite** to replace the selected favorite with the node's current source and text.
- **Delete favorite** to remove only the saved preset. Images are never removed.

Favorites store paths only. The package never copies, moves, edits, or uploads source images. Data is written inside this custom node at:

```text
custom_nodes/comfyui_random_reference_source/config/presets.json
```

The first save carries the package's older folder-only favorites into this versioned local file. Each ComfyUI installation has its own favorites, independent of any configured user directory.

## Prompt text

Connect a string to the optional **prompt** input and use **prompt_with_favorite** downstream. When the selected favorite has text, the output is:

```text
favorite text, incoming prompt
```

If either value is empty, the output contains the other value without an extra comma. Editing **favorite_prompt** does not change the saved favorite until **Update favorite** is used.

## Paths

Relative folders resolve beneath ComfyUI's active input directory. Relative selected-image paths resolve beneath their favorite's folder. Absolute local paths are also supported. Folder favorites may include subfolders; image-set favorites preserve the selected path order.
