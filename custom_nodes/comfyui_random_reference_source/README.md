# arch-Random Reference Image Source

This local ComfyUI package loads one reference image from a folder or an explicit image selection. It supports random-per-queue, seeded, and sequential selection while keeping the existing `RandomReferenceImageSource` and `ReferenceLanePack` workflow node types stable.

## Reference browser

Click **Load image…** on a source node for a plain single-image file picker.
It uses ComfyUI's local input upload and selects only that image, clearing the
previous folder/favorite selection. Cancel or a failed upload preserves the source.

Click **Browse folder…** on a source node to open the native folder picker directly.
The **Folder** and **Selected images** buttons inside the browser open their
native pickers directly; cancelling keeps
the existing source. Reload ComfyUI after installing frontend changes.

Click **Open Reference Browser…** on a source node. The separate browser names
the target node at the top and offers **Folder** and **Selected images** modes.
Choosing a folder clears the previous image list; picking images clears the old
folder and detaches any active favorite. The old Auto value is still accepted
when loading older workflows but is not offered in the browser.

The image grid scrolls independently of the workflow canvas and loads 24 images
at a time. Search filenames, check images across pages, then choose **Use checked
images** to replace the source with that explicit set. Click a thumbnail to open
a larger preview. A folder remains a folder source until an explicit set is used.

**Random each run**, **Repeatable seed**, and **Next image in order** describe
the selection policies. Changing to repeatable mode fixes the seed; changing to
sequential mode advances the index after each queue. The compact node shows one
preview and labels random pools honestly: their next image is chosen at run time.
Reopening a workflow enforces those same policy rules. Random choices can repeat.
Changing seed or policy preserves the gallery scroll position; changing source
clears the previous filename search.

## Favorites

Open **Reference Favorites** in the ComfyUI sidebar, or use the Favorites column
inside the browser. The target selector identifies exactly which node receives
a favorite. Search names and click one to load it.

The dedicated **Reference prompt** panel sits beside the image gallery. Its
larger editor applies text as you type and shows **Saved**, **Modified**, or
**Draft** status. Use:

- **Save changes** to update the selected favorite's source and text.
- **Save as new** with a separate name to create another favorite. Duplicate
  names are rejected, including names differing only in capitalization.
- **Revert** to restore the selected favorite's saved text, or clear an unnamed draft.
- **Delete saved favorite** to remove the preset while keeping this node's source and text.

Prompt drafts and proposed names are kept separately for each node and source.
Switching favorites, reselecting the current favorite, changing folders, and
closing/reopening the panel do not discard them. Save the workflow to retain
drafts across reloads; Save changes/Save as new persists the favorite itself.
Failed saves leave the draft intact. If you keep typing during a save, the newer
text stays modified instead of being overwritten by the completed request.
Raw image paths remain in a separate **Image paths** section.

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

If either value is empty, the output contains the other value without an extra comma.
Prompt edits apply to the current node immediately, including clearing the text.
**Save changes/Save as new** stores those edits in the favorite for reuse.
The editor indicates when the prompt output is disconnected. In workflow #54,
**Reference Prompt Compose** joins the edit instruction, main reference text,
and enabled identity/auxiliary reference text before Flux text encoding. Each
optional image switch also controls that reference's prompt contribution.
The prompt/model subgraph contains **Combined prompt sent to Flux** for inspecting
the full text after running. Disabled prompt lanes are lazy and do not load images.

The panel's **Combined prompt · live** preview shows the complete text before
running, with Included/Empty/Off indicators for the instruction and reference
lanes. It resolves the current graph locally and follows switch changes without
queueing generation. Custom text generators that require execution are reported
as unavailable rather than presenting an invented preview. Multiple composers
are listed by title and execution ID.

## Paths

Relative folders resolve beneath ComfyUI's active input directory. Relative selected-image paths resolve beneath their favorite's folder. Absolute local paths are also supported. Folder favorites may include subfolders; image-set favorites preserve the selected path order.
An empty folder requires choosing a source. Enter `.` explicitly to use the input
directory. Picker selections safely preserve filenames containing commas.
