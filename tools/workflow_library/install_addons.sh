#!/usr/bin/env bash
# Clone the recommended ComfyUI addons into custom_nodes.
#
# Installs the three extensions from docs/workflow-prompt-addons-research.md
# that live inside ComfyUI. SmartGallery is not installed here: it is a
# separate application, not a custom node.
#
# Existing clones are left alone unless UPDATE=1 is set. Nothing is deleted.
#
#   ./install_addons.sh /path/to/ComfyUI
#   UPDATE=1 ./install_addons.sh /path/to/ComfyUI

set -euo pipefail

COMFY_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CUSTOM_NODES="$COMFY_ROOT/custom_nodes"
UPDATE="${UPDATE:-0}"

if [ ! -d "$CUSTOM_NODES" ]; then
  echo "error: no custom_nodes folder under '$COMFY_ROOT'" >&2
  exit 1
fi

# name|url|why
ADDONS=(
  "comfyui-adaptiveprompts|https://github.com/Alectriciti/comfyui-adaptiveprompts.git|Wildcards, variables and adaptive RNG"
  "ComfyUI-Autocomplete-Plus|https://github.com/newtextdoc1111/ComfyUI-Autocomplete-Plus.git|Tag autocomplete and related-tag panel"
  "comfyui-g-workflows|https://github.com/AI4VFX/comfyui-g-workflows.git|Workflow browser with thumbnails and sidecar tags"
)

echo "ComfyUI root: $COMFY_ROOT"
echo

for entry in "${ADDONS[@]}"; do
  IFS='|' read -r name url why <<< "$entry"
  target="$CUSTOM_NODES/$name"
  printf '%-30s %s\n' "$name" "$why"

  if [ -d "$target" ]; then
    if [ "$UPDATE" = "1" ]; then
      echo "  updating..."
      git -C "$target" pull --ff-only >/dev/null
    else
      echo "  already present, skipping (set UPDATE=1 to pull)"
    fi
    continue
  fi

  echo "  cloning..."
  if ! git clone --depth 1 "$url" "$target" >/dev/null 2>&1; then
    echo "  FAILED" >&2
    continue
  fi

  if [ -f "$target/requirements.txt" ]; then
    echo "  installing requirements..."
    python -m pip install -q -r "$target/requirements.txt"
  fi
done

wildcard_source="$COMFY_ROOT/wildcards/archpt"
wildcard_target="$CUSTOM_NODES/comfyui-adaptiveprompts/wildcards"
echo
if [ -d "$wildcard_source" ] && [ -d "$CUSTOM_NODES/comfyui-adaptiveprompts" ]; then
  echo "Copying arch-pt wildcards into adaptiveprompts..."
  mkdir -p "$wildcard_target"
  # cp -r onto an existing directory of the same name nests it, so a second
  # run would create archpt/archpt. Clear it first.
  rm -rf "$wildcard_target/archpt"
  cp -r "$wildcard_source" "$wildcard_target/archpt"
else
  echo "Wildcard export not found at $wildcard_source"
  echo "  run: python -m tools.workflow_library.export_wildcards"
fi

cat <<'NEXT'

Next steps:
  1. Restart the ComfyUI server (not just a browser refresh).
  2. Hard-refresh the browser (Ctrl+F5).
  3. If ComfyUI-Custom-Scripts is installed, disable its autocomplete -
     it binds the same text widgets as Autocomplete-Plus.
  4. SmartGallery DAM is a separate app, not a custom node:
     https://github.com/biagiomaf/smart-comfyui-gallery
NEXT
