import json
import shutil
import subprocess
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "custom_nodes"
    / "comfyui-prompt-composer"
    / "web"
    / "prompt_composer.js"
)
NODE_EXECUTABLE = shutil.which("node")


def test_prompt_composer_uses_compact_directly_clickable_badges():
    assert NODE_EXECUTABLE, "Node.js is required for the frontend regression test"
    node_script = f"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync({json.dumps(str(SCRIPT_PATH))}, "utf8")
  .replace(/^import[^\\n]*\\n/gm, "");

class FakeElement {{
  constructor(tagName) {{
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {{}};
    this.style = {{}};
    this.listeners = {{}};
    this.className = "";
    this.textContent = "";
    this.title = "";
    this.type = "";
    this.value = "";
    this.checked = false;
  }}
  appendChild(child) {{
    child.parentElement = this;
    this.children.push(child);
    return child;
  }}
  append(...children) {{
    for (const child of children) this.appendChild(child);
  }}
  addEventListener(type, callback) {{
    (this.listeners[type] ||= []).push(callback);
  }}
  dispatchEvent(event) {{
    event.target ||= this;
    for (const callback of this.listeners[event.type] || []) callback(event);
    const handler = this[`on${{event.type}}`];
    if (handler) handler(event);
    return true;
  }}
  set innerHTML(_value) {{
    this.children = [];
  }}
  get innerHTML() {{
    return "";
  }}
  get scrollHeight() {{
    return this.children.length * 24;
  }}
}}

function descendants(root) {{
  const found = [];
  for (const child of root.children || []) {{
    found.push(child, ...descendants(child));
  }}
  return found;
}}

function byRole(root, role) {{
  return descendants(root).filter((element) => element.dataset?.pcRole === role);
}}

function assertEqual(actual, expected, label) {{
  if (actual !== expected) {{
    throw new Error(`${{label}}: expected ${{JSON.stringify(expected)}}, got ${{JSON.stringify(actual)}}`);
  }}
}}

function assert(condition, label) {{
  if (!condition) throw new Error(label);
}}

const schema = {{
  PromptComposerBody: {{
    category: "body",
    slots: [
      ["subject", "Subject (age / identity)"],
      ["body_type", "Body type / shape"],
      ["height_build", "Height & build"],
      ["skin", "Skin"],
      ["hair", "Hair"],
      ["eyes", "Eyes"],
      ["face", "Facial features"],
      ["expression", "Expression"],
      ["chest", "Chest"],
      ["features", "Distinguishing features"],
      ["pose", "Pose"],
    ].map(([key, label]) => ({{ key, label }})),
    garment_keys: [],
  }},
  PromptComposerClothing: {{
    category: "clothing",
    slots: [
      {{ key: "headwear", label: "Headwear" }},
    ],
    garment_keys: [],
  }},
}};
const libraries = {{
  quality: {{
    Photoreal: "photorealistic, highly detailed",
    Studio: "professional studio photograph",
    Sharp: "sharp focus",
  }},
  lighting: {{
    Golden: "golden hour",
  }},
}};

let extension = null;
let canvasWheelEvents = 0;
const app = {{
  canvas: {{
    canvas: {{
      dispatchEvent(event) {{
        if (event.type === "wheel") canvasWheelEvents += 1;
      }},
    }},
  }},
  extensionManager: {{ toast: {{ add() {{}} }} }},
  registerExtension(value) {{ extension = value; }},
}};
const api = {{
  async fetchApi(url) {{
    let data;
    if (url.endsWith("/schema")) data = schema;
    else if (url.endsWith("/libraries")) data = libraries;
    else if (url.includes("/presets?category=body")) {{
      data = {{ Portrait: {{ hair: "long red hair", eyes: "green eyes" }} }};
    }} else if (url.includes("/presets?category=clothing")) {{
      data = {{}};
    }} else {{
      throw new Error(`Unexpected request: ${{url}}`);
    }}
    return {{ ok: true, async json() {{ return data; }} }};
  }},
}};
const context = {{
  app,
  api,
  clearTimeout() {{}},
  confirm() {{ return true; }},
  console,
  document: {{ createElement(tagName) {{ return new FakeElement(tagName); }} }},
  globalThis: null,
  prompt() {{ return null; }},
  setTimeout(callback) {{ callback(); return 1; }},
  WheelEvent: class WheelEvent {{
    constructor(type, source = {{}}) {{ this.type = type; Object.assign(this, source); }}
  }},
}};
context.globalThis = context;
vm.runInNewContext(source, context);
if (!extension) throw new Error("Extension did not register");

function widget(name, value = "") {{
  return {{
    name,
    type: "string",
    value,
    options: {{}},
    callback(next) {{ this.value = next; }},
  }};
}}

function baseNode(widgets) {{
  return {{
    widgets,
    size: [360, 300],
    domWidgets: [],
    addWidget(type, name, value, callback, options = {{}}) {{
      const added = {{ type, name, value, callback, options }};
      this.widgets.push(added);
      return added;
    }},
    addDOMWidget(name, type, element, options = {{}}) {{
      const added = {{ type, name, element, options, value: "" }};
      this.widgets.push(added);
      this.domWidgets.push(added);
      return added;
    }},
    setDirtyCanvas() {{}},
  }};
}}

function SlotNodeType() {{}}
function ClothingNodeType() {{}}
function LegacySlotNodeType() {{}}
function SnippetNodeType() {{}}

(async () => {{
  await extension.setup();

  await extension.beforeRegisterNodeDef(
    SlotNodeType,
    {{ name: "PromptComposerBody" }},
  );
  const slotNode = Object.assign(
    Object.create(SlotNodeType.prototype),
    baseNode([...schema.PromptComposerBody.slots.map((slot) => widget(slot.key)), widget("separator", ", ")]),
  );
  slotNode.onNodeCreated();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  for (const {{ key }} of schema.PromptComposerBody.slots) {{
    assertEqual(slotNode.widgets.find((item) => item.name === key)?.type, "pc_hidden", `${{key}} hidden`);
  }}
  assertEqual(slotNode.widgets.find((item) => item.name === "separator")?.type, "string", "separator remains editable");
  assertEqual(slotNode.widgets.filter((item) => item.type === "button").length, 0, "no stacked native action buttons");
  assertEqual(slotNode.domWidgets.length, 1, "one compact slot DOM widget");

  const slotRoot = slotNode.domWidgets[0].element;
  const fieldGrid = byRole(slotRoot, "field-grid")[0];
  assert(fieldGrid, "field badge grid exists");
  assertEqual(fieldGrid.style.flexWrap, "wrap", "field badges wrap");
  assert(fieldGrid.style.overflowY !== "auto", "field grid has no inner scroll trap");
  assertEqual(byRole(slotRoot, "field-badge").length, 11, "all fields are directly visible");
  assertEqual(byRole(slotRoot, "preset-badge").length, 1, "presets are directly visible");

  const hairBadge = byRole(slotRoot, "field-badge").find((button) => button.dataset.slotKey === "hair");
  hairBadge.dispatchEvent({{ type: "click" }});
  const editor = byRole(slotRoot, "field-editor")[0];
  assertEqual(editor.dataset.slotKey, "hair", "shared editor targets clicked badge");
  editor.value = "short black hair";
  editor.dispatchEvent({{ type: "input" }});
  assertEqual(slotNode.widgets.find((item) => item.name === "hair").value, "short black hair", "editor updates serialized widget");

  slotNode.widgets.find((item) => item.name === "hair").value = "restored auburn hair";
  slotNode.onConfigure?.({{ widgets_values: [] }});
  const restoredHairBadge = byRole(slotRoot, "field-badge").find((button) => button.dataset.slotKey === "hair");
  assert(restoredHairBadge.textContent.includes("restored auburn hair"), "badges refresh after workflow values restore");

  let prevented = false;
  slotRoot.dispatchEvent({{
    type: "wheel",
    preventDefault() {{ prevented = true; }},
    stopPropagation() {{}},
  }});
  assertEqual(canvasWheelEvents, 1, "wheel forwards to canvas");
  assert(prevented, "wheel does not get trapped by DOM widget");

  await extension.beforeRegisterNodeDef(
    ClothingNodeType,
    {{ name: "PromptComposerClothing" }},
  );
  const clothingNode = Object.assign(
    Object.create(ClothingNodeType.prototype),
    baseNode([
      {{ ...widget("nude", false), type: "toggle" }},
      widget("headwear"),
      widget("nude_text", "nude"),
      widget("separator", ", "),
    ]),
  );
  clothingNode.onNodeCreated();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assertEqual(clothingNode.widgets.find((item) => item.name === "nude")?.type, "pc_hidden", "nude uses a compact badge");
  assertEqual(clothingNode.widgets.find((item) => item.name === "headwear")?.type, "pc_hidden", "clothing slot hidden");
  assertEqual(clothingNode.widgets.find((item) => item.name === "nude_text")?.type, "string", "nude text remains editable");
  assertEqual(clothingNode.widgets.find((item) => item.name === "separator")?.type, "string", "clothing separator remains editable");

  await extension.beforeRegisterNodeDef(
    LegacySlotNodeType,
    {{ name: "PromptComposerBody" }},
  );
  const legacyNodeState = baseNode([
    ...schema.PromptComposerBody.slots.map((slot) => widget(slot.key)),
    widget("separator", ", "),
  ]);
  delete legacyNodeState.addDOMWidget;
  const legacyNode = Object.assign(Object.create(LegacySlotNodeType.prototype), legacyNodeState);
  legacyNode.onNodeCreated();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assertEqual(legacyNode.widgets.find((item) => item.name === "subject")?.type, "string", "legacy build keeps native slots");
  assertEqual(legacyNode.widgets.find((item) => item.name === "separator")?.type, "string", "legacy build keeps separator");

  await extension.beforeRegisterNodeDef(
    SnippetNodeType,
    {{ name: "PromptComposerSnippets" }},
  );
  const snippetNode = Object.assign(
    Object.create(SnippetNodeType.prototype),
    baseNode([widget("library", "quality"), widget("selected", "[]"), widget("separator", ", ")]),
  );
  snippetNode.onNodeCreated();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assertEqual(snippetNode.widgets.filter((item) => item.type === "button").length, 0, "snippet actions are not stacked native buttons");
  assertEqual(snippetNode.domWidgets.length, 1, "one compact snippet DOM widget");
  const snippetRoot = snippetNode.domWidgets[0].element;
  assertEqual(byRole(snippetRoot, "library-badge").length, 2, "libraries are direct category badges");
  assertEqual(byRole(snippetRoot, "snippet-badge").length, 3, "snippet options are direct badges");
  assertEqual(byRole(snippetRoot, "snippet-edit").length, 1, "one shared edit action");
  assertEqual(byRole(snippetRoot, "snippet-delete").length, 1, "one shared delete action");
  assert(!descendants(snippetRoot).some((element) => element.style.overflowY === "auto"), "snippet UI has no inner scroll trap");
}})().catch((error) => {{
  console.error(error.stack || error.message);
  process.exit(1);
}});
"""

    result = subprocess.run(
        [NODE_EXECUTABLE, "-e", node_script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
