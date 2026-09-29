import json
import subprocess
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "web" / "random_reference_source.js"


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
  installReferenceBrowser() {{}},
  openReferenceBrowser() {{}},
  refreshReferenceBrowser() {{}},
  refreshReferencePrompt() {{}},
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
    favorite_prompt: "same character",
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
    {{ name: "favorite_prompt", type: "string", value: values.favorite_prompt, options: {{}} }},
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


@pytest.mark.parametrize("seed", [1, 123456789])
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
    favorite_prompt: "same character",
  }};
  const original = createNode(expected);
  const saved = serialiseWidgetValues(original);
  assertEqual(saved.length, 10, "persisted widget count");
  if (saved.some((value) => value === null)) {{
    throw new Error(`Workflow contains sparse widget holes: ${{JSON.stringify(saved)}}`);
  }}
  const restored = createNode();
  configureWidgetValues(restored, saved);
  assertPersistedState(restored, expected);
"""
    )


def test_dense_seed_zero_workflow_is_upgraded_without_losing_seed_mode():
    _run_extension_assertions(
        """
  const restored = createNode();
  configureWidgetValues(restored, [
    "reference_subject",
    "selection",
    "None",
    ".",
    "a.png\\nb.png",
    "seeded",
    0,
    "fixed",
    false,
  ]);
  assertWidget(restored, "seed", 1);
  assertWidget(restored, "control_after_generate", "fixed");
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
    control_after_generate: "fixed",
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
    control_after_generate: "fixed",
    include_subfolders: true,
  });
"""
    )


def test_sparse_seed_zero_workflow_is_restored_with_seed_one():
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
    seed: 1,
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
    control_after_generate: "fixed",
    include_subfolders: true,
  });
"""
    )


def test_selecting_sequential_mode_sets_incrementing_seed_control():
    _run_extension_assertions(
        """
  const node = createNode({
    selection_policy: "random_each_queue",
    seed: 0,
    control_after_generate: "randomize",
  });
  const policy = findWidget(node, "selection_policy");
  policy.value = "sequential";
  policy.callback("sequential", app.canvas, node);
  assertWidget(node, "seed", 1);
  assertWidget(node, "control_after_generate", "increment");
"""
    )


@pytest.mark.parametrize("control_mode", ["fixed", "decrement", "randomize"])
def test_sequential_restore_always_advances_the_index(control_mode):
    _run_extension_assertions(
        f"""
  const restored = createNode();
  configureWidgetValues(restored, [
    "reference_subject",
    "selection",
    "None",
    ".",
    "a.png\\nb.png",
    "sequential",
    7,
    {json.dumps(control_mode)},
    false,
  ]);
  assertWidget(restored, "seed", 7);
  assertWidget(restored, "control_after_generate", "increment");
"""
    )


def test_advanced_sequential_cursor_round_trips_after_frontend_increment():
    _run_extension_assertions(
        """
  const original = createNode({
    selection_policy: "sequential",
    seed: 1,
    control_after_generate: "increment",
  });
  findWidget(original, "seed").value += 1;

  const restored = createNode();
  configureWidgetValues(restored, serialiseWidgetValues(original));
  assertWidget(restored, "selection_policy", "sequential");
  assertWidget(restored, "seed", 2);
  assertWidget(restored, "control_after_generate", "increment");
"""
    )


def test_favorite_manager_controls_are_transient_and_named_by_action():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'addTransientButton("Open Reference Browser…"' in source
    assert 'addTransientButton("Browse folder…"' in source
    assert 'addTransientButton("★ Save new favorite…"' not in source


def test_compact_widgets_use_frontend_visibility_flag():
    _run_extension_assertions("""
  const node = createNode({ selection_policy: "random_each_queue" });
  for (const name of ["seed", "folder", "selected_images", "control_after_generate"])
    assertEqual(findWidget(node, name).hidden, true, name + " hidden");
  findWidget(node, "selection_policy").value = "seeded";
  context.compactWidgets(node);
  assertEqual(findWidget(node, "seed").hidden, false, "seed restored");
""")


def test_picking_folder_replaces_selection_and_detaches_favorite():
    _run_extension_assertions("""
  const node = createNode({ favorite: "Old", selected_images: "old.png" });
  context.selectFolder(node, "C:/new-folder");
  assertWidget(node, "source_mode", "folder");
  assertWidget(node, "folder", "C:/new-folder");
  assertWidget(node, "selected_images", "");
  assertWidget(node, "favorite", "None");
""")


def test_picking_images_clears_folder_and_detaches_favorite():
    _run_extension_assertions("""
  const node = createNode({ folder: "C:/old", favorite: "Old" });
  context.selectImages(node, ["C:/new/a.png", "C:/new/b.png"]);
  assertWidget(node, "source_mode", "selection");
  assertWidget(node, "folder", "");
  assertWidget(node, "selected_images", "C:/new/a.png\\nC:/new/b.png");
  assertWidget(node, "favorite", "None");
""")


def test_applying_favorite_is_atomic_and_manual_edit_detaches_it():
    _run_extension_assertions("""
  const node = createNode({ favorite: "New" });
  node._archReferencePresets = { New: { kind: "folder", folder: "C:/fav", prompt_text: "prefix" } };
  context.applyFavorite(node);
  assertWidget(node, "favorite", "New");
  assertWidget(node, "folder", "C:/fav");
  assertWidget(node, "selected_images", "");
  const folder = findWidget(node, "folder");
  folder.value = "C:/manual";
  folder.callback();
  assertWidget(node, "favorite", "None");
  assertWidget(node, "folder", "C:/manual");
""")


def test_seeded_policy_uses_fixed_seed_after_user_switch():
    _run_extension_assertions("""
  const node = createNode({ selection_policy: "random_each_queue", control_after_generate: "randomize" });
  const policy = findWidget(node, "selection_policy");
  policy.value = "seeded";
  policy.callback();
  assertWidget(node, "control_after_generate", "fixed");
""")


def test_missing_or_deleted_favorite_keeps_the_current_source():
    _run_extension_assertions("""
  const node = createNode({ favorite: "Old", folder: "C:/chosen", selected_images: "C:/chosen/a.png" });
  context.refreshFavoriteOptions(node, {});
  assertWidget(node, "favorite", "None");
  assertWidget(node, "folder", "C:/chosen");
  assertWidget(node, "selected_images", "C:/chosen/a.png");
  context.api.fetchApi = async () => ({ ok: true, json: async () => ({presets: {}}) });
  await context.deleteFavorite(node, "Old");
  assertWidget(node, "folder", "C:/chosen");
  assertWidget(node, "selected_images", "C:/chosen/a.png");
""")


def test_empty_folder_payload_stays_empty():
    _run_extension_assertions("""
  const node = createNode({ folder: "", selected_images: "" });
  assertEqual(context.referencePayload(node).folder, "", "empty source");
""")


def test_picker_quotes_filenames_containing_commas():
    _run_extension_assertions('''
  const node = createNode();
  context.selectImages(node, ["C:/portraits/last, first.png", "C:/portraits/plain.png"]);
  assertWidget(node, "selected_images", '"C:/portraits/last, first.png"\\nC:/portraits/plain.png');
''')


def test_prompt_drafts_survive_source_changes_and_workflow_round_trip():
    _run_extension_assertions('''
  const node = createNode();
  node._archReferencePresets = { A: {prompt_text: "saved A"}, B: {prompt_text: "saved B"} };
  context.applySource(node, {favorite:"A", folder:"C:/a", source_mode:"folder", favorite_prompt:"saved A"});
  findWidget(node, "favorite_prompt").value = "draft A";
  findWidget(node, "favorite_prompt").callback();
  context.setPromptName(node, "My separate favorite");
  context.selectFolder(node, "C:/manual");
  assertWidget(node, "favorite_prompt", "draft A");
  context.applySource(node, {favorite:"B", folder:"C:/b", favorite_prompt:"saved B"});
  const restored = createNode();
  restored.properties = JSON.parse(JSON.stringify(node.properties));
  configureWidgetValues(restored, serialiseWidgetValues(node));
  restored._archReferencePresets = node._archReferencePresets;
  context.applySource(restored, {favorite:"A", folder:"C:/a", favorite_prompt:"saved A"});
  assertWidget(restored, "favorite_prompt", "draft A");
  assertEqual(context.promptState(restored).name, "My separate favorite", "saved draft name");
  assertEqual(context.promptState(restored).modified, true, "modified state");
  context.applySource(restored, {favorite_prompt:context.promptState(restored).baseline});
  assertWidget(restored, "favorite_prompt", "saved A");
  assertEqual(context.promptState(restored).modified, false, "reverted state");
''')


def test_slow_save_preserves_newer_text_and_new_favorite_name():
    _run_extension_assertions('''
  const node = createNode({favorite_prompt:"submitted text"});
  context.setPromptName(node, "New");
  let finish;
  context.api.fetchApi = async (path, options) => {
    const body = JSON.parse(options.body);
    assertEqual(body.save_mode, "create", "save action");
    assertEqual(body.prompt_text, "submitted text", "save snapshot");
    return new Promise(resolve => { finish = () => resolve({ok:true,json:async()=>({name:"New",presets:{New:{kind:"selection",folder:"",images:["a.png"],prompt_text:"submitted text"}}})}); });
  };
  const pending = context.saveFavorite(node, "New", "create");
  findWidget(node, "favorite_prompt").value = "newer text";
  findWidget(node, "favorite_prompt").callback();
  context.setPromptName(node, "Next favorite");
  finish(); await pending;
  assertWidget(node, "favorite", "New");
  assertWidget(node, "favorite_prompt", "newer text");
  assertEqual(context.promptState(node).modified, true, "newer edit remains unsaved");
  assertEqual(context.promptState(node).name, "Next favorite", "newer name preserved");
''')


def test_failed_save_preserves_draft_and_name():
    _run_extension_assertions('''
  const node = createNode({favorite_prompt:"keep me"});
  context.setPromptName(node, "New");
  context.api.fetchApi = async () => ({ok:false,status:400,json:async()=>({error:"Name exists"})});
  let failed = false;
  try { await context.saveFavorite(node, "New", "create"); } catch { failed = true; }
  assertEqual(failed, true, "save failure reported");
  assertWidget(node, "favorite_prompt", "keep me");
  assertWidget(node, "favorite", "None");
  assertEqual(context.promptState(node).name, "New", "failed save keeps name");
''')


def test_reselecting_favorite_preserves_draft_and_latest_choice_wins():
    _run_extension_assertions('''
  const node = createNode();
  const presets = {A:{kind:"folder",folder:"a",prompt_text:"saved A"},B:{kind:"folder",folder:"b",prompt_text:"saved B"}};
  const response = {ok:true,json:async()=>({presets})};
  context.api.fetchApi = async () => response;
  await context.chooseFavorite(node, "A");
  findWidget(node, "favorite_prompt").value = "unsaved A";
  findWidget(node, "favorite_prompt").callback();
  await context.chooseFavorite(node, "A");
  assertWidget(node, "favorite_prompt", "unsaved A");
  let requests = [];
  context.api.fetchApi = () => new Promise(resolve => requests.push(resolve));
  const first = context.chooseFavorite(node, "A");
  const second = context.chooseFavorite(node, "B");
  requests[1](response); await second;
  requests[0](response); await first;
  assertWidget(node, "favorite", "B");
  const third = context.chooseFavorite(node, "A");
  context.selectFolder(node, "manual");
  requests[2](response); await third;
  assertWidget(node, "folder", "manual");
  assertWidget(node, "favorite", "None");
''')


def test_deleting_favorite_preserves_current_text_over_older_source_draft():
    _run_extension_assertions('''
  const node = createNode({favorite:"None", source_mode:"folder", folder:"C:/folder", selected_images:"", favorite_prompt:"old manual draft"});
  context.rememberPromptDraft(node);
  context.applySource(node, {favorite:"Saved", favorite_prompt:"current favorite text"});
  context.api.fetchApi = async () => ({ok:true,json:async()=>({presets:{}})});
  await context.deleteFavorite(node, "Saved");
  assertWidget(node, "favorite", "None");
  assertWidget(node, "favorite_prompt", "current favorite text");
''')


def test_saved_state_ignores_whitespace_normalized_by_preset_store():
    _run_extension_assertions('''
  const node = createNode({favorite:"Saved", favorite_prompt:"  saved text\\n"});
  node._archReferencePresets = {Saved:{prompt_text:"saved text"}};
  assertEqual(context.promptState(node).modified, false, "saved normalized text");
''')


def test_completing_save_cannot_cancel_a_newer_pending_favorite_choice():
    _run_extension_assertions('''
  const node = createNode({favorite:"A",source_mode:"folder",folder:"a",favorite_prompt:"draft A"});
  const presets = {A:{kind:"folder",folder:"a",prompt_text:"draft A"},B:{kind:"folder",folder:"b",prompt_text:"saved B"}};
  node._archReferencePresets = presets;
  let finishSave, finishChoice;
  context.api.fetchApi = (path, options) => new Promise(resolve => {
    const finish = () => resolve({ok:true,json:async()=>({name:"A",presets})});
    if (options?.method === "POST") finishSave = finish; else finishChoice = finish;
  });
  const saving = context.saveFavorite(node, "A", "update");
  const choosing = context.chooseFavorite(node, "B");
  finishSave(); await saving;
  finishChoice(); await choosing;
  assertWidget(node, "favorite", "B");
  assertWidget(node, "favorite_prompt", "saved B");
''')
