# ComfyUI Prompt Composer

Composable, **saveable** prompt-building nodes. Fill structured slots (or pick
from saved snippets), and the node assembles a clean comma-joined prompt string
— plus a JSON view of the structured parts. Presets and snippet libraries are
stored on the server so you can reuse them across every workflow.

**Location:** `C:\tools\image\ComfyUI\custom_nodes\comfyui-prompt-composer\`
**Data store:** `C:\tools\image\ComfyUI\custom_nodes\comfyui-prompt-composer\data\presets.json`

> After copying this folder in, **restart the ComfyUI server** (new Python nodes
> + HTTP routes are only picked up at startup) and **hard-refresh the browser**
> (Ctrl+F5) so the frontend extension loads.

All nodes appear under the **`prompt/composer`** category (right-click → Add Node).

---

## Nodes

### 🧥 Clothing Prompt (`PromptComposerClothing`)
One text slot per clothing region — headwear, face/eyewear, top, outerwear,
full outfit, bottom, hosiery, footwear, gloves/accessories, underwear, extra.
Fill any, leave the rest blank.

- **`nude` toggle** — when on, the *garment* slots (top, outerwear, full outfit,
  bottom, hosiery, footwear, underwear) are dropped and replaced by the
  **`nude_text`** value (default `nude`). **Accessory** slots (headwear,
  face/eyewear, gloves/accessories, extra) are *kept* — "nude but still wearing
  a hat / glasses" is a real case, so the toggle doesn't blindly wipe everything.
- Example: `headwear = "red baseball hat"`, `top = "blue shirt"` →
  `prompt` = `red baseball hat, blue shirt`
  and `prompt_json` = `{"headwear":"red baseball hat","top":"blue shirt"}`.

### 🧍 Body Description (`PromptComposerBody`)
Slots for subject/age, body type, height & build, skin, hair, eyes, face,
expression, chest, distinguishing features, pose.

### 🏞 Environment Prompt (`PromptComposerEnvironment`)
Slots for location, setting, background, time of day, season, weather, lighting,
mood/atmosphere, color palette, shot/camera angle.

### 📚 Snippet Library (`PromptComposerSnippets`)
The generic, fully user-defined one. Build named **libraries** of titled
snippets ("Photoreal" → `photorealistic, highly detailed, sharp focus, 8k`),
then tick the ones you want and the node chains them together. Libraries live in
the data store and are reusable anywhere. Ships with starter libraries:
`quality`, `lighting`, `camera`.

### ➕ Prompt Combine (`PromptComposerCombine`)
Fan-in: up to six prompt inputs joined into one. `dedupe` (default on) removes
repeated comma-tags so chaining never doubles up a tag.

---

## Outputs & chaining

Every composer node outputs:
- **`prompt`** — the assembled string (comma-joined, empties skipped)
- **`prompt_json`** — the structured `{slot: value}` form as a JSON string

Two ways to chain:
1. **Inline** — wire one node's `prompt` into the next node's optional
   **`prepend`** input; it gets merged in front.
2. **Fan-in** — feed several `prompt` outputs into a **Prompt Combine** node.

Feed the final `prompt` into your `CLIP Text Encode` (or any text input).

---

## Presets & saving (frontend)

On the slot nodes a small bar appears at the top of the node:
- **`📋 preset`** dropdown — pick a saved preset to fill all slots
- **`💾 save preset`** — name the current slot values and store them
- **`🗑 delete preset`** / **`✖ clear slots`**

On the Snippet Library node:
- **`📚 library`** dropdown + **`🗂 new library`** / **`🗑 delete library`**
- **`➕ add snippet`**, and per-row **✎ edit** / **✕ delete**
- tick the checkboxes to choose which snippets to chain; a live preview shows
  the result

Presets are keyed by category, so a "Casual" clothing preset and a "Casual" body
preset never collide.

---

## Notes

- **Headless-safe:** the nodes resolve entirely from their widget values (and,
  for snippets, the on-disk library) — they run correctly even if the frontend
  JS never loads. The JS only adds the preset/snippet convenience UI.
- **Portability:** snippet *libraries* live in `data\presets.json` on the
  server. Move that file with your workflows if you want the snippets to come
  along. Slot-node values are saved inside the workflow itself.
- **Self-test:** `C:\tools\image\ComfyUI\venv\Scripts\python.exe C:\tools\image\ComfyUI\custom_nodes\comfyui-prompt-composer\_selftest.py`
  exercises every node's logic without needing the server running.
