import json
import subprocess
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "web" / "random_reference_source.js"
)


def _run_extension_assertions(assertions: str) -> None:
    node_script = f"""
const fs = require("fs");
const vm = require("vm");
const scriptPath = {json.dumps(str(SCRIPT_PATH))};
const source = fs.readFileSync(scriptPath, "utf8")
  .replace(/^import[^\\n]*\\n/gm, "");

let extension = null;
const app = {{
  canvas: {{}},
  extensionManager: {{ toast: {{ add() {{}} }} }},
  registerExtension(value) {{ extension = value; }},
}};
const context = {{
  app,
  api: {{
    fetchApi: async () => {{
      throw new Error("Network access is not expected in persistence tests");
    }},
  }},
  clearTimeout() {{}},
  console,
  document: {{
    createElement() {{
      return {{ innerHTML: "", style: {{}} }};
    }},
  }},
  globalThis: null,
  setTimeout() {{ return 1; }},
}};
context.globalThis = context;
vm.runInNewContext(source, context);

if (!extension) throw new Error("Extension did not register");

function backendWidgets(overrides = {{}}) {{
  const defaults = {{
    lane: "reference_subject",
    source_mode: "selection",
    favorite: "None",
    folder: ".",
    selected_images: "a.png\\nb.png",
    selection_policy: "seeded",
    seed: 42,
    control_after_generate: "fixed",
    include_subfolders: true,
  }};
  const values = {{ ...defaults, ...overrides }};
  return [
    {{ name: "lane", type: "combo", value: values.lane, options: {{}} }},
    {{ name: "source_mode", type: "combo", value: values.source_mode, options: {{}} }},
    {{ name: "favorite", type: "combo", value: values.favorite, options: {{}} }},
    {{ name: "folder", type: "string", value: values.folder, options: {{}} }},
    {{ name: "selected_images", type: "string", value: values.selected_images, options: {{}} }},
    {{
      name: "selection_policy",
      type: "combo",
      value: values.selection_policy,
      options: {{ values: ["random_each_queue", "seeded", "sequential"] }},
    }},
    {{ name: "seed", type: "number", value: values.seed, options: {{}} }},
    {{
      name: "control_after_generate",
      type: "combo",
      value: values.control_after_generate,
      options: {{
        serialize: false,
        values: ["fixed", "increment", "decrement", "randomize"],
      }},
    }},
    {{
      name: "include_subfolders",
      type: "toggle",
      value: values.include_subfolders,
      options: {{}},
    }},
  ].map((widget) => ({{ ...widget, callback() {{}} }}));
}}

function createNode(overrides = {{}}) {{
  const node = Object.create(NodeType.prototype);
  Object.assign(node, {{
    widgets: backendWidgets(overrides),
    size: [320, 300],
    addWidget(type, name, value, callback, options = {{}}) {{
      const widget = {{ type, name, value, callback, options }};
      this.widgets.push(widget);
      return widget;
    }},
    addDOMWidget(name, type, element, options = {{}}) {{
      const widget = {{ type, name, value: "", element, options }};
      this.widgets.push(widget);
      return widget;
    }},
    computeSize() {{ return [320, 420]; }},
    setDirtyCanvas() {{}},
    setSize(size) {{ this.size = size; }},
  }});
  node.onNodeCreated?.();
  return node;
}}

function findWidget(node, name) {{
  return node.widgets.find((widget) => widget.name === name);
}}

function serialiseWidgetValues(node) {{
  const values = [];
  for (const [index, widget] of node.widgets.entries()) {{
    if (widget.serialize === false) continue;
    const value = widget.value;
    values[index] = value ?? null;
  }}
  return JSON.parse(JSON.stringify(values));
}}

function configureWidgetValues(node, values) {{
  let index = 0;
  for (const widget of node.widgets) {{
    if (widget.serialize === false) continue;
    if (index >= values.length) break;
    widget.value = values[index++];
  }}
  node.onConfigure?.({{ widgets_values: values }});
}}

function assertEqual(actual, expected, label) {{
  if (actual !== expected) {{
    throw new Error(`${{label}}: expected ${{JSON.stringify(expected)}}, got ${{JSON.stringify(actual)}}`);
  }}
}}

function assertWidget(node, name, expected) {{
  assertEqual(findWidget(node, name)?.value, expected, name);
}}

function assertPersistedState(node, expected) {{
  for (const [name, value] of Object.entries(expected)) {{
    assertWidget(node, name, value);
  }}
}}

function NodeType() {{}}

(async () => {{
  await extension.beforeRegisterNodeDef(NodeType, {{ name: "RandomReferenceImageSource" }});
  {assertions}
}})().catch((error) => {{
  console.error(error.stack || error.message);
  process.exit(1);
}});
"""

    result = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("seed", [0, 123456789])
def test_round_trip_preserves_dense_named_widget_state(seed):
    _run_extension_assertions(
        f"""
  const expected = {{
    lane: "reference_subject",
    source_mode: "selection",
    favorite: "None",
    folder: ".",
    selected_images: "a.png\\nb.png",
    selection_policy: "sequential",
    seed: {seed},
    control_after_generate: "increment",
    include_subfolders: true,
  }};
  const original = createNode(expected);
  const saved = serialiseWidgetValues(original);
  assertEqual(saved.length, 9, "persisted widget count");
  if (saved.some((value) => value === null)) {{
    throw new Error(`Workflow contains sparse widget holes: ${{JSON.stringify(saved)}}`);
  }}
  const restored = createNode();
  configureWidgetValues(restored, saved);
  assertPersistedState(restored, expected);
"""
    )


def test_legacy_dense_workflow_restores_include_subfolders_without_stealing_control():
    _run_extension_assertions(
        """
  const restored = createNode({ control_after_generate: "randomize", include_subfolders: false });
  configureWidgetValues(restored, [
    "environment",
    "folder",
    "None",
    "places",
    "",
    "seeded",
    77,
    true,
  ]);
  assertPersistedState(restored, {
    lane: "environment",
    source_mode: "folder",
    favorite: "None",
    folder: "places",
    selected_images: "",
    selection_policy: "seeded",
    seed: 77,
    control_after_generate: "randomize",
    include_subfolders: true,
  });
"""
    )


def test_sparse_interleaved_workflow_is_migrated_by_widget_name():
    _run_extension_assertions(
        """
  const restored = createNode();
  configureWidgetValues(restored, [
    "reference_subject",
    "selection",
    "None",
    ".",
    null,
    "a.png\\nb.png",
    null,
    "seeded",
    9001,
    "increment",
    true,
    "",
  ]);
  assertPersistedState(restored, {
    lane: "reference_subject",
    source_mode: "selection",
    favorite: "None",
    folder: ".",
    selected_images: "a.png\\nb.png",
    selection_policy: "seeded",
    seed: 9001,
    control_after_generate: "increment",
    include_subfolders: true,
  });
"""
    )


def test_sparse_seed_zero_workflow_matches_the_reported_failure_shape():
    _run_extension_assertions(
        """
  const restored = createNode();
  configureWidgetValues(restored, [
    "reference_subject",
    "auto",
    "Input folder root",
    ".",
    null,
    "C:/reference-images/selected.png",
    null,
    "random_each_queue",
    0,
    false,
    false,
    "",
  ]);
  assertPersistedState(restored, {
    lane: "reference_subject",
    source_mode: "auto",
    favorite: "Input folder root",
    folder: ".",
    selected_images: "C:/reference-images/selected.png",
    selection_policy: "random_each_queue",
    seed: 0,
    control_after_generate: "randomize",
    include_subfolders: false,
  });
"""
    )


def test_sparse_resave_recovers_legacy_include_from_stolen_control_slot():
    _run_extension_assertions(
        """
  const restored = createNode();
  configureWidgetValues(restored, [
    "environment",
    "folder",
    "None",
    "places",
    null,
    "",
    null,
    "seeded",
    77,
    true,
    false,
    "",
  ]);
  assertPersistedState(restored, {
    lane: "environment",
    source_mode: "folder",
    favorite: "None",
    folder: "places",
    selected_images: "",
    selection_policy: "seeded",
    seed: 77,
    control_after_generate: "randomize",
    include_subfolders: true,
  });
"""
    )


def test_selecting_sequential_mode_sets_incrementing_seed_control():
    _run_extension_assertions(
        """
  const node = createNode({
    selection_policy: "random_each_queue",
    control_after_generate: "randomize",
  });
  const policy = findWidget(node, "selection_policy");
  policy.value = "sequential";
  policy.callback("sequential", app.canvas, node);
  assertWidget(node, "control_after_generate", "increment");
"""
    )


def test_advanced_sequential_cursor_round_trips_after_frontend_increment():
    _run_extension_assertions(
        """
  const original = createNode({
    selection_policy: "sequential",
    seed: 0,
    control_after_generate: "increment",
  });
  findWidget(original, "seed").value += 1;

  const restored = createNode();
  configureWidgetValues(restored, serialiseWidgetValues(original));
  assertWidget(restored, "selection_policy", "sequential");
  assertWidget(restored, "seed", 1);
  assertWidget(restored, "control_after_generate", "increment");
"""
    )
