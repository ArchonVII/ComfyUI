# arch-pt prompt builder

`arch-pt` is a set of focused ComfyUI prompt nodes for still images and
optics. It lets you build a positive prompt a few decisions at a time without
turning one node into a wall of controls. Everything is blank by default: a
field says nothing until you choose or type something.

The included example is
`user/default/workflows/agent/38 - Arch PT Prompt Builder.json`. Copy the
example or open it and immediately use **Save As**. Never overwrite one of your
saved workflows unless you explicitly mean to replace it.

## Quickest workflow

1. Add the six focused nodes and one `arch-pt-Combine`, or open a copy of the
   example workflow.
2. Leave any subject you do not care about blank. In the fields you do care
   about, use quick buttons, search for a choice, or type additional specifics.
3. Connect each focused node's `prompt_bundle` output to its matching input on
   Combine: Identity to identity, Pose to pose, and so on.
4. Optionally connect an Input Text node to Combine's base prompt and extra
   prompt inputs. Base comes first; extra comes last.
5. Send `positive_prompt` to the positive text input of your image workflow.
   The example also connects all three outputs to Preview as Text nodes so you
   can inspect the prompt, metadata JSON, and future LoRA requests JSON without
   loading a checkpoint.

## What each node controls

- `arch-pt-Identity` describes who the subject is: subject, adult age, body
  type, height, weight/build, chest or breasts, hips or butt, waist, skin,
  hair, eyes, facial details, and expression.
- `arch-pt-Pose` describes what the subject is doing. Overall pose, body axis,
  facing and depth are separate from head/torso, left and right arms/hands, and
  left and right legs/feet.
- `arch-pt-Clothing` describes clothing state, garments, waist and lower-body
  pieces, outfit details, materials, colors, fit, condition, and accessories.
  “Use clothing source” means copy the clothing from a clothing-source image;
  “use reference subject's clothing” means preserve what the reference subject
  is wearing. Those are deliberately distinct.
- `arch-pt-Environment` describes the scene type, named setting, contents,
  density, time, season, weather, mood, palette, and period.
- `arch-pt-Camera` describes still-image framing and optics: distance, angle,
  focal length, depth of field, composition, and effects such as bokeh or lens
  flare. It does not add video camera movement.
- `arch-pt-Lighting` describes brightness, exposure, source count and type,
  direction, color temperature, softness, shadows, falloff, contrast, and
  lighting techniques.
- `arch-pt-Combine` assembles the six bundles in that order between the base
  prompt and extra prompt. It emits only positive prompt material.

## Choosing and editing

Small, obvious sets use quick buttons. Larger sets are searchable. You can
always type in the Additional specifics box for details that are not in the
catalog.

Some fields allow one choice inside a group. Choosing another value in that
same group replaces the earlier value. Independent groups remain additive, so
you can combine long + wavy + auburn hair. Snippet-style fields are also
additive and can hold several actions or details.

Every chosen phrase becomes a chip copied into the workflow. The chip is
editable and you can remove it. It is a snapshot, not a live link: changing the
catalog, changing a saved user choice, or switching model family will not
rewrite an existing chip.

Left and right limbs always mean the subject's anatomical left and right. Body
axis and placement use explicit image frame language, such as frame-left or
lower-right, so they do not silently switch to the viewer's idea of the
subject's left.

A semantic slider contributes no words until you enable it. Once enabled, the
slider selects a hand-authored phrase on its spectrum. Disable it again to
remove that phrase without deleting text you typed in Additional specifics.

## Flux and Qwen

Each focused node defaults to Flux and can instead be set to Qwen. The model
family controls the wording copied by future selections. Switching from Flux
to Qwen does not translate or rewrite selections already copied into the
workflow. This keeps old workflows repeatable even when the catalog changes.
If the visible selector and saved editor snapshot ever disagree, the visible
selector wins for future choices while every existing chip stays unchanged.

The setting is only a prompt-phrase selector. It does not load a Flux or Qwen
model, checkpoint, text encoder, or sampler.

## Saved choices

Built-in choices are protected. They cannot be edited or deleted. Use
**Duplicate** to make a user-owned copy, then edit or delete that copy. You can
also create a new option directly in the field's Manage choices panel.
Duplicate labels are allowed because each user option has its own stable ID.

User choices live under the active ComfyUI profile at
`<configured ComfyUI user root>/<profile>/arch_prompt_tools/options.json`. With
ComfyUI's normal repository-level user root and single-user default profile,
that is `user/default/arch_prompt_tools/options.json`. Multi-user requests use
the validated `comfy-user` profile, so one profile cannot list or mutate
another profile's saved choices. Create, edit, and delete are explicit actions;
merely choosing a chip does not change the library.

Each saved choice belongs to one node, field, selection behavior, and model
family. Grouped fields offer only the groups defined by their schema, and
another choice in the same group replaces the earlier one. Additive fields
stack custom choices; their stable per-option group is assigned by the system
and is not something you type or edit. Duplicating an additive built-in also
creates an independent stacking choice. If you want different Flux and Qwen
wording, create the corresponding choice for each family.

## Combine outputs

Combine outputs, in order:

1. `positive_prompt` — base prompt, Identity, Pose, Clothing, Environment,
   Camera, Lighting, then extra prompt, joined by the selected separator.
2. `metadata_json` — structured information about non-empty bundles.
3. `lora_requests_json` — enabled future LoRA associations carried by selected
   chips.

With dedupe enabled, repeated text is compared after trimming and normalizing
whitespace, case-insensitively, and the first wording is kept. With dedupe
disabled, repeated phrases remain. Empty text and empty bundles add nothing.

This phase is positive-only. It intentionally has no negative-prompt builder,
contradiction checker, video motion, or model loader.

## Future LoRA associations

An option may carry LoRA association metadata and an enabled checkbox. That
metadata is copied with the chip and Combine can list it in
`lora_requests_json`. This package does not load, apply, or turn on a LoRA.
A later centralized LoRA node can consume those explicit requests; until then
they are inspection data only.

LoRA metadata must contain ordinary JSON values. Numbers must be finite, and
integer-valued numbers must stay within JavaScript's safe-integer range
(`-(2^53 - 1)` through `2^53 - 1`). The editor and HTTP API reject values
outside that range instead of silently rounding or replacing them.

## Safety and recovery

User-option writes use a temporary file and atomic replacement so an
interrupted write does not leave a half-written catalog. If
`options.json` contains invalid JSON, invalid UTF-8, an unsupported version, or
an invalid option, the file is preserved and the library reports an error
instead of silently replacing it.

Before hand-editing user choices, back up the file at that configured user-root
path. If the file becomes invalid, keep the broken copy for recovery, restore
your backup or correct the JSON, and reload ComfyUI. Deleting the file starts
with an empty user library; protected built-ins remain available.

These nodes coexist with the legacy Arch prompt nodes. Their class names and
workflow state are separate, and installing `arch-pt` does not replace or
migrate any existing workflow. Copy a workflow before experimenting, use
**Save As**, and never overwrite saved work unless that replacement was
explicitly requested.
