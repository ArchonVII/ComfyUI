# arch-Random Reference Image Source

This local ComfyUI package loads one reference image from a folder or an explicit image selection. It supports random-per-queue, seeded, and sequential selection while keeping the existing `RandomReferenceImageSource` and `ReferenceLanePack` workflow node types stable.

## Reference browser

Click **Load image…** on a source node for a plain single-image file picker.
It uses ComfyUI's local input upload and selects only that image, clearing the
previous folder/favorite selection. Cancel or a failed upload preserves the source.

Click **Browse folder…** on a source node to open the native folder picker directly.
The **Load folder…** and **Load images…** buttons inside the browser open their
native pickers directly; cancelling keeps
the existing source. Reload ComfyUI after installing frontend changes.

Click **Open Reference Browser…** on a source node. The separate browser names
the target node at the top and offers folder and selected-image sources.
You can also type a folder path and press **Load folder path**.
The browser fills the window, with the gallery taking the main area. **Groups**
and **Prompt** in the header toggle the side panels. **Settings** opens folder
paths, selection policy, seed/index, subfolders, and raw image paths in a
popover. Load/search controls and selection/save actions use horizontal toolbars.
Choosing a folder clears the previous image list; picking images clears the old
folder and detaches any active favorite. The old Auto value is still accepted
when loading older workflows but is not offered in the browser.

The image grid scrolls independently of the workflow canvas and loads 24 images
at a time. Search filenames, check images across pages, then choose **Use checked
images** to replace the source with that explicit set. Click a thumbnail to
toggle its selection; the **⤢** button opens a larger preview. A folder remains
a folder source until an explicit set is used. Native picker controls show busy
state, and late responses cannot replace a newer source or a different target.

Picked images start checked, including images on later pages. **Select all**
checks every search match across the whole source; **Unselect all** clears all
checks without changing the source. The dense grid uses image-only cards with
overlay checkboxes; hover for a filename or use **⤢** to enlarge.

**Save to character…** copies checked images into an existing or newly named
subject/character in the local **Reference Library** sidebar. Originals stay in
place, identical content is deduplicated, and library images remain local and
outside git. This action saves images; favorite prompt editing remains separate.

**Random each run**, **Repeatable seed**, and **Next image in order** describe
the selection policies. Changing to repeatable mode fixes the seed; changing to
sequential mode advances the index after each queue. The compact node shows one
preview and labels random pools honestly: their next image is chosen at run time.
Reopening a workflow enforces those same policy rules. Random choices can repeat.
Changing seed or policy preserves the gallery scroll position; changing source
clears the previous filename search.

## Favorites

**Save to favorite group…** below the gallery saves exactly the checked photos,
with a name and the current reference prompt. Create a new group, or select an
existing group to replace its membership and optionally edit its name. Name
collisions are rejected. Saving also selects the group as this node's run source.
Click a saved group in the **Favorite groups** column to reuse it. To edit its
membership, load it, check/uncheck photos (or load another folder to add photos),
then choose the group in the save dialog. Groups store local paths; character
saves copy photos into the separate character library. Original photos stay local.

Open **Reference Favorites** in the ComfyUI sidebar, or use the Favorites column
inside the browser. The target selector identifies exactly which node receives
a favorite. Search names and click one to load it.

The dedicated **Reference prompt** panel sits beside the image gallery. Its
larger editor applies text as you type and shows **Saved**, **Modified**, or
**Draft** status. Use:

- **Save changes** to update the selected favorite's source and text.
- **Save as new**, under **Save whole source + prompt as a new group**, with a
  separate name to create another favorite from the active run source. Duplicate
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

Favorites store paths only. Character saves explicitly copy images into the local
library; the single-image picker uploads only to this PC's ComfyUI input folder.
Source images are never moved or edited. Data is written inside this custom node at:

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
