import json
import shutil
import subprocess
from pathlib import Path

import pytest


PACKAGE_DIR = Path(__file__).parents[1]
FRONTEND = PACKAGE_DIR / "web" / "arch_prompt_tools.js"
INIT = PACKAGE_DIR / "__init__.py"
SCHEMAS = json.loads((PACKAGE_DIR / "data" / "schemas.json").read_text(encoding="utf-8"))
BUILTIN_OPTIONS = json.loads(
    (PACKAGE_DIR / "data" / "builtin_options.json").read_text(encoding="utf-8")
)["options"]


def frontend_source() -> str:
    return FRONTEND.read_text(encoding="utf-8")


def test_package_exposes_the_frontend_directory():
    assert 'WEB_DIRECTORY = "./web"' in INIT.read_text(encoding="utf-8")


def test_frontend_registers_only_the_six_focused_node_types():
    source = frontend_source()
    for node_type in (
        "ArchPtIdentity",
        "ArchPtPose",
        "ArchPtClothing",
        "ArchPtEnvironment",
        "ArchPtCamera",
        "ArchPtLighting",
    ):
        assert json.dumps(node_type) in source
    assert '"ArchPtCombine"' not in source
    assert "app.registerExtension" in source
    assert "beforeRegisterNodeDef" in source


def test_frontend_uses_serialized_hidden_state_and_one_dom_editor():
    source = frontend_source()
    assert 'findWidget(node, "state_json")' in source
    assert 'findWidget(node, "model_family")' in source
    assert "hideSerializedWidget" in source
    assert "serializeValue" in source
    assert "addDOMWidget" in source
    assert "_archPtEditorInstalled" in source
    assert "onConfigure" in source
    assert "setDirtyCanvas(true, true)" in source


def test_frontend_contract_includes_schema_controls_and_accessibility():
    source = frontend_source()
    assert '"/arch-prompt-tools/schema"' in source
    assert '"/arch-prompt-tools/options"' in source
    assert "model_family=" in source
    assert 'createElement("details")' in source
    assert 'createElement("summary")' in source
    assert 'createElement("button")' in source
    assert 'createElement("input")' in source
    assert 'input.type = "search"' in source
    assert '.type = "range"' in source
    assert '.type = "checkbox"' in source
    assert "aria-label" in source
    assert "Additional specifics" in source
    assert "Retry" in source
    assert '"quick_buttons"' not in source
    assert "controlKind(field.control)" in source


def test_frontend_supports_copied_chip_crud_user_option_crud_and_lora_state():
    source = frontend_source()
    assert "editFragmentText" in source
    assert "removeFragmentById" in source
    assert "toggleFragmentLora" in source
    assert '"POST"' in source
    assert '"PATCH"' in source
    assert '"DELETE"' in source
    assert "Duplicate" in source
    assert "New option" in source
    assert "Save option" in source
    assert "Edit option" in source
    assert "Delete option" in source
    assert "confirm(" in source
    assert "Built-in · protected" in source
    assert "renderOptionManagement" in source
    assert source.count("executeOptionMutation(") >= 3


def test_frontend_guards_async_restore_and_serializes_text_as_it_is_edited():
    source = frontend_source()
    assert "loadGeneration" in source
    assert 'addEventListener("input"' in source
    assert "allowReset" in source
    assert "export {" in source


def test_frontend_never_uses_html_parsing_for_catalog_or_user_strings():
    source = frontend_source()
    assert ".innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "outerHTML" not in source
    assert ".textContent" in source
    assert ".value" in source


def test_editor_degrades_without_hiding_raw_state_and_keeps_large_forms_scrollable():
    source = frontend_source()
    install = source.split("function installEditor", 1)[1].split(
        "function extendFocusedNode", 1
    )[0]
    assert install.index("typeof node.addDOMWidget") < install.index(
        "hideSerializedWidget"
    )
    assert "max-height:620px" in source
    assert "overflow:auto" in source
    assert "copiedPhrase" in source


def _core_source() -> str:
    source = frontend_source()
    start_marker = "// ARCH_PT_CORE_START"
    end_marker = "// ARCH_PT_CORE_END"
    assert source.count(start_marker) == 1
    assert source.count(end_marker) == 1
    return source.split(start_marker, 1)[1].split(end_marker, 1)[0]


def test_dom_free_state_core_behavior(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available for the portable frontend behavior test")

    script = (
        _core_source()
        + f"\nconst REAL_SCHEMA = {json.dumps(SCHEMAS, ensure_ascii=False)};\n"
        + r"""
import assert from "node:assert/strict";

function realField(nodeKey, fieldKey) {
  const node = REAL_SCHEMA.nodes.find((item) => item.key === nodeKey);
  return node.sections.flatMap((section) => section.fields).find((field) => field.key === fieldKey);
}
for (const [nodeKey, fieldKey] of [
  ["identity", "age_group"],
  ["identity", "height"],
  ["identity", "hair_color"],
  ["pose", "base_pose"],
]) {
  const field = realField(nodeKey, fieldKey);
  assert.equal(field.control, "buttons");
  assert.equal(controlKind(field.control), "buttons");
}
assert.equal(controlKind(realField("identity", "identity_specifics").control), "text");
assert.equal(controlKind(realField("identity", "body_snippets").control), "searchable");
assert.equal(controlKind(realField("environment", "scene_density").control), "spectrum");
assert.equal(focusedNodeKey("ArchPtIdentity"), "identity");
assert.equal(focusedNodeKey("ArchPtLighting"), "lighting");
assert.equal(focusedNodeKey("ArchPtCombine"), null);
assert.equal(focusedNodeKey("UnrelatedNode"), null);
assert.equal(
  optionsQuery("identity", "qwen", "hair color"),
  "node=identity&model_family=qwen&field=hair%20color",
);

const base = createEmptyState("identity", "flux");
assert.equal(serializeState(base), '{"version":1,"node":"identity","model_family":"flux","fields":{}}');

const fluxOption = {
  id: "identity.hair_color.auburn",
  label: "Auburn",
  node: "identity",
  field: "hair_color",
  group: "hair_color",
  phrases: {flux: "auburn hair", qwen: "give the subject auburn hair"},
  builtin: true,
  lora: {name: "auburn-helper", strength: 0.7},
  lora_enabled: true,
};
let state = toggleOption(base, fluxOption, "flux", "copy-1");
assert.equal(state.fields.hair_color.fragments[0].text, "auburn hair");
assert.equal(state.fields.hair_color.fragments[0].label, "Auburn");
assert.equal(state.fields.hair_color.fragments[0].source_option_id, fluxOption.id);
assert.deepEqual(state.fields.hair_color.fragments[0].lora, fluxOption.lora);
assert.notStrictEqual(state.fields.hair_color.fragments[0].lora, fluxOption.lora);
fluxOption.phrases.flux = "catalog changed";
fluxOption.label = "Catalog changed";
fluxOption.lora.name = "catalog-changed";
assert.equal(state.fields.hair_color.fragments[0].text, "auburn hair");
assert.equal(state.fields.hair_color.fragments[0].label, "Auburn");
assert.equal(state.fields.hair_color.fragments[0].lora.name, "auburn-helper");

const brown = {
  ...fluxOption,
  id: "identity.hair_color.brown",
  label: "Brown",
  phrases: {flux: "brown hair", qwen: "give the subject brown hair"},
  lora: null,
  lora_enabled: false,
};
state = toggleOption(state, brown, "flux", "copy-2");
assert.deepEqual(state.fields.hair_color.fragments.map((item) => item.text), ["brown hair"]);
state = toggleOption(state, brown, "flux", "unused-toggle-id");
assert.equal(state.fields.hair_color.fragments.length, 0);

const freckles = {
  id: "identity.body_snippets.freckles",
  label: "Freckles",
  node: "identity",
  field: "body_snippets",
  group: "freckles",
  phrases: {flux: "freckles", qwen: "add freckles"},
  builtin: true,
  lora: null,
  lora_enabled: false,
};
const scars = {
  ...freckles,
  id: "identity.body_snippets.scars",
  label: "Scars",
  group: "scars",
  phrases: {flux: "visible scars", qwen: "add visible scars"},
};
state = toggleOption(state, freckles, "flux", "copy-3");
state = toggleOption(state, scars, "flux", "copy-4");
assert.deepEqual(state.fields.body_snippets.fragments.map((item) => item.text), ["freckles", "visible scars"]);

const buttonState = toggleOption(createEmptyState("identity", "flux"), brown, "flux", "button-copy");
const buttonModels = buttonChoiceModels([brown], buttonState, "flux");
assert.deepEqual(buttonModels, [{
  id: brown.id,
  label: "Brown",
  phrase: "brown hair",
  selected: true,
  lora_associated: false,
}]);
const fakeDocument = {
  createElement(tag) {
    return {
      tagName: tag.toUpperCase(),
      attributes: {},
      listeners: {},
      setAttribute(name, value) { this.attributes[name] = String(value); },
      addEventListener(name, listener) { this.listeners[name] = listener; },
    };
  },
};
let clickedButton = null;
let clickedState = buttonState;
const renderedButtons = createChoiceButtons(fakeDocument, buttonModels, (id) => {
  clickedButton = id;
  clickedState = toggleOption(clickedState, brown, "flux", "unused-click-id");
});
assert.equal(renderedButtons[0].tagName, "BUTTON");
assert.equal(renderedButtons[0].textContent, "Brown");
assert.equal(renderedButtons[0].attributes["aria-pressed"], "true");
renderedButtons[0].listeners.click({preventDefault() {}, stopPropagation() {}});
assert.equal(clickedButton, brown.id);
assert.equal(clickedState.fields.hair_color.fragments.length, 0);

let emptyEdit = toggleOption(createEmptyState("identity", "flux"), freckles, "flux", "empty-copy");
emptyEdit = toggleOption(emptyEdit, scars, "flux", "kept-copy");
emptyEdit = editFragmentText(emptyEdit, "empty-copy", "   ");
const emptyRoundTrip = restoreState(serializeState(emptyEdit), "identity");
assert.equal(emptyRoundTrip.ok, true);
assert.equal(emptyRoundTrip.state.fields.body_snippets.fragments.length, 2);
assert.equal(emptyRoundTrip.state.fields.body_snippets.fragments[0].text, "");
assert.equal(emptyRoundTrip.state.fields.body_snippets.fragments[1].text, "visible scars");

state = editFragmentText(state, "copy-3", "  light   freckles  ");
assert.equal(state.fields.body_snippets.fragments[0].text, "light freckles");
state = toggleFragmentLora(state, "copy-3", true);
assert.equal(state.fields.body_snippets.fragments[0].lora_enabled, false);
state = removeFragmentById(state, "copy-4");
assert.deepEqual(state.fields.body_snippets.fragments.map((item) => item.instance_id), ["copy-3"]);
state = setSpecificsText(state, "hair_specifics", "  loose   strands  ");
assert.equal(state.fields.hair_specifics.specifics, "loose strands");
assert.equal(state.fields.body_snippets.fragments[0].text, "light freckles");

const spectrumField = {
  key: "brightness",
  spectrum: [
    {minimum: 0, maximum: 0.25, phrases: {flux: "dim", qwen: "make it dim"}},
    {minimum: 0.25, maximum: 0.75, phrases: {flux: "balanced", qwen: "use balanced light"}},
    {minimum: 0.75, maximum: 1, phrases: {flux: "bright", qwen: "make it bright"}},
  ],
};
let lighting = createEmptyState("lighting", "flux");
lighting = setSpectrum(lighting, spectrumField, "flux", true, 0.249, "spectrum-1");
assert.equal(lighting.fields.brightness.fragments[0].text, "dim");
assert.equal(spectrumValue(spectrumField, lighting.fields.brightness.fragments[0]), 0.125);
lighting = setSpectrum(lighting, spectrumField, "flux", true, 0.25, "ignored");
assert.equal(lighting.fields.brightness.fragments[0].text, "balanced");
assert.equal(lighting.fields.brightness.fragments[0].instance_id, "spectrum-1");
lighting = setSpectrum(lighting, spectrumField, "flux", true, 1, "ignored");
assert.equal(lighting.fields.brightness.fragments[0].text, "bright");
lighting = setSpecificsText(lighting, "brightness", "retain this");
lighting = setSpectrum(lighting, spectrumField, "flux", false, 1, "ignored");
assert.equal(lighting.fields.brightness.fragments.length, 0);
assert.equal(lighting.fields.brightness.specifics, "retain this");

state = toggleOption(createEmptyState("identity", "flux"), {
  ...brown,
  phrases: {flux: "original flux", qwen: "future qwen"},
}, "flux", "family-old");
state = setModelFamily(state, "qwen");
state = toggleOption(state, {
  ...freckles,
  phrases: {flux: "flux detail", qwen: "future qwen detail"},
}, "qwen", "family-new");
assert.equal(state.model_family, "qwen");
assert.equal(state.fields.hair_color.fragments[0].text, "original flux");
assert.equal(state.fields.hair_color.fragments[0].model_family, "flux");
assert.equal(state.fields.body_snippets.fragments[0].text, "future qwen detail");
assert.equal(state.fields.body_snippets.fragments[0].model_family, "qwen");

const goodRestore = restoreState(serializeState(state), "identity");
assert.equal(goodRestore.ok, true);
assert.deepEqual(goodRestore.state, state);
const blankRestore = restoreState('{"version":1,"node":"pose","model_family":"flux","fields":{}}', "pose");
assert.equal(blankRestore.ok, true);
assert.equal(serializeState(blankRestore.state), '{"version":1,"node":"pose","model_family":"flux","fields":{}}');
for (const [raw, expected] of [
  ["not json", "valid JSON"],
  ['{"version":2,"node":"identity","model_family":"flux","fields":{}}', "version"],
  ['{"version":1,"node":"pose","model_family":"flux","fields":{}}', "node"],
]) {
  const restored = restoreState(raw, "identity");
  assert.equal(restored.ok, false);
  assert.match(restored.error, new RegExp(expected));
  assert.equal(restored.state, null);
}
const invalidRaw = '{"version":2,"node":"identity","model_family":"flux","fields":{}}';
const invalidDecision = editorRestoreDecision(invalidRaw, "identity", "flux");
assert.equal(invalidDecision.ok, false);
assert.equal(invalidDecision.allow_reset, true);
assert.equal(invalidDecision.state, null);
assert.equal(invalidRaw, '{"version":2,"node":"identity","model_family":"flux","fields":{}}');
const mismatchDecision = editorRestoreDecision(
  '{"version":1,"node":"identity","model_family":"flux","fields":{}}',
  "identity",
  "qwen",
);
assert.equal(mismatchDecision.ok, false);
assert.equal(mismatchDecision.allow_reset, true);
assert.equal(mismatchDecision.state, null);

const payload = buildUserOptionPayload({
  label: " Phone pose ",
  node: "pose",
  field: "left_hand",
  group: "holding_phone",
  model_family: "qwen",
  phrase: " holds a phone ",
  lora: {name: "phone"},
  lora_enabled: true,
});
assert.deepEqual(payload, {
  label: "Phone pose",
  node: "pose",
  field: "left_hand",
  group: "holding_phone",
  model_family: "qwen",
  phrase: "holds a phone",
  builtin: false,
  lora: {name: "phone"},
  lora_enabled: true,
});
const createRequest = buildOptionMutation("create", null, payload, payload.field);
assert.equal(createRequest.method, "POST");
assert.equal(createRequest.path, "/arch-prompt-tools/options");
assert.deepEqual(createRequest.payload, payload);
assert.equal(createRequest.refresh_field, "left_hand");
const updateRequest = buildOptionMutation("update", "user.phone/pose", payload, payload.field);
assert.equal(updateRequest.method, "PATCH");
assert.equal(updateRequest.path, "/arch-prompt-tools/options/user.phone%2Fpose");
assert.equal(updateRequest.refresh_field, "left_hand");
const deleteRequest = buildOptionMutation("delete", "user.phone/pose", null, "left_hand");
assert.equal(deleteRequest.method, "DELETE");
assert.equal(deleteRequest.path, "/arch-prompt-tools/options/user.phone%2Fpose");
assert.equal(deleteRequest.payload, null);
assert.equal(deleteRequest.refresh_field, "left_hand");
"""
    )
    test_file = tmp_path / "frontend_core_test.mjs"
    test_file.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(test_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_actual_production_render_lifecycle_crud_and_reset_wiring(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available for the portable frontend integration test")

    source = frontend_source().replace(
        'import { app } from "/scripts/app.js";', ""
    ).replace('import { api } from "/scripts/api.js";', "")
    age_option = next(
        option
        for option in BUILTIN_OPTIONS
        if option["node"] == "identity" and option["field"] == "age_group"
    )
    script = (
        r"""
import assert from "node:assert/strict";

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.childNodes = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.classList = {
      toggle: (name, enabled) => {
        const names = new Set(this.className.split(/\s+/u).filter(Boolean));
        if (enabled) names.add(name); else names.delete(name);
        this.className = [...names].join(" ");
      },
    };
  }
  append(...children) {
    for (const child of children) {
      if (child?.tagName === "#FRAGMENT") this.childNodes.push(...child.childNodes);
      else this.childNodes.push(child);
    }
  }
  appendChild(child) { this.append(child); return child; }
  replaceChildren(...children) { this.childNodes = []; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}

const document = {
  createElement: (tag) => new FakeElement(tag),
  createDocumentFragment: () => new FakeElement("#fragment"),
};
const scheduled = [];
const setTimeout = (callback) => { scheduled.push(callback); return scheduled.length; };
const confirm = () => true;
const registeredExtensions = [];
const app = {
  canvas: {},
  registerExtension: (extension) => registeredExtensions.push(extension),
  extensionManager: {toast: {add() {}}},
};
let fetchCalls = [];
const api = {
  async fetchApi(path, options = {}) {
    fetchCalls.push({path, options});
    const payload = path.endsWith("/schema")
      ? REAL_SCHEMA
      : {version: 1, options: [ROUTE_OPTION]};
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      async json() { return payload; },
    };
  },
};

function all(root, predicate) {
  const found = [];
  const visit = (item) => {
    if (!item || typeof item !== "object") return;
    if (predicate(item)) found.push(item);
    for (const child of item.childNodes || []) visit(child);
  };
  visit(root);
  return found;
}
"""
        + f"\nconst REAL_SCHEMA = {json.dumps(SCHEMAS, ensure_ascii=False)};\n"
        + f"\nconst SOURCE_OPTION = {json.dumps(age_option, ensure_ascii=False)};\n"
        + r"""
const ROUTE_OPTION = {
  ...SOURCE_OPTION,
  builtin: true,
  lora: SOURCE_OPTION.lora || null,
  lora_enabled: Boolean(SOURCE_OPTION.lora),
};
"""
        + source
        + r"""

assert.equal(registeredExtensions.length, 1);
assert.equal(focusedNodeKey("ArchPtCombine"), null);

const ageField = REAL_SCHEMA.nodes
  .find((item) => item.key === "identity")
  .sections.flatMap((section) => section.fields)
  .find((field) => field.key === "age_group");
const hiddenState = {
  name: "state_json",
  value: serializeState(createEmptyState("identity", "flux")),
  callback() {},
};
const renderNode = {
  dirty: 0,
  setDirtyCanvas() { this.dirty += 1; },
};
const renderContext = {
  node: renderNode,
  nodeKey: "identity",
  stateWidget: hiddenState,
  familyWidget: {name: "model_family", value: "flux"},
  state: createEmptyState("identity", "flux"),
  family: "flux",
  options: new Map([["age_group", [ROUTE_OPTION]]]),
  schemaNode: {
    key: "identity",
    sections: [{key: "core", label: "Core", fields: [ageField]}],
  },
  body: new FakeElement("div"),
  status: new FakeElement("div"),
  invalid: false,
};
const renderedField = renderField(renderContext, ageField);
const quickButtons = all(
  renderedField,
  (item) => item.tagName === "BUTTON" && item.textContent === ROUTE_OPTION.label,
);
assert.ok(quickButtons.length >= 1);
assert.ok(all(renderedField, (item) => item.tagName === "SUMMARY" && item.textContent === "Manage choices").length);
quickButtons[0].listeners.click({preventDefault() {}, stopPropagation() {}});
const renderedState = JSON.parse(hiddenState.value);
assert.equal(renderedState.fields.age_group.fragments.length, 1);
assert.equal(renderedState.fields.age_group.fragments[0].source_option_id, ROUTE_OPTION.id);

function FakeNodeType() {
  this.widgets = [
    {name: "model_family", value: "flux", callback() {}},
    {
      name: "state_json",
      value: serializeState(createEmptyState("identity", "flux")),
      callback() {},
    },
  ];
  this.size = [420, 200];
  this.domWidgets = 0;
}
FakeNodeType.prototype.addDOMWidget = function () {
  this.domWidgets += 1;
  return {};
};
FakeNodeType.prototype.setDirtyCanvas = function () {};
FakeNodeType.prototype.setSize = function (size) { this.size = size; };
extendFocusedNode(FakeNodeType, "identity");
const lifecycleNode = new FakeNodeType();
lifecycleNode.onNodeCreated();
lifecycleNode.onNodeCreated();
assert.equal(lifecycleNode.domWidgets, 1);
await Promise.resolve();
await Promise.resolve();
lifecycleNode.onConfigure({});
assert.equal(scheduled.length, 1);
const fetchesBeforeConfigureReload = fetchCalls.length;
await scheduled.shift()();
assert.ok(fetchCalls.length > fetchesBeforeConfigureReload);
await Promise.resolve();
await Promise.resolve();
assert.equal(lifecycleNode.domWidgets, 1);

const mutationContext = {};
const requests = [];
const refreshes = [];
const dependencies = {
  request: async (path, options) => {
    requests.push({path, options});
    return {ok: true};
  },
  refresh: async (_context, field) => { refreshes.push(field); },
};
const optionPayload = buildUserOptionPayload({
  label: "Custom age",
  node: "identity",
  field: "age_group",
  group: "age_group",
  model_family: "flux",
  phrase: "an adult subject",
  lora: null,
  lora_enabled: false,
});
await executeOptionMutation(mutationContext, "create", null, optionPayload, "age_group", dependencies);
await executeOptionMutation(mutationContext, "update", "user.age/one", optionPayload, "age_group", dependencies);
await executeOptionMutation(mutationContext, "delete", "user.age/one", null, "age_group", dependencies);
assert.deepEqual(requests.map((item) => [item.options.method, item.path]), [
  ["POST", "/arch-prompt-tools/options"],
  ["PATCH", "/arch-prompt-tools/options/user.age%2Fone"],
  ["DELETE", "/arch-prompt-tools/options/user.age%2Fone"],
]);
assert.deepEqual(JSON.parse(requests[0].options.body), optionPayload);
assert.deepEqual(JSON.parse(requests[1].options.body), optionPayload);
assert.equal("body" in requests[2].options, false);
assert.deepEqual(refreshes, ["age_group", "age_group", "age_group"]);
let failureRefreshes = 0;
await assert.rejects(
  executeOptionMutation(
    mutationContext,
    "create",
    null,
    optionPayload,
    "age_group",
    {
      request: async () => { throw new Error("write failed"); },
      refresh: async () => { failureRefreshes += 1; },
    },
  ),
  /write failed/u,
);
assert.equal(failureRefreshes, 0);

const invalidRaw = '{"version":2,"node":"identity","model_family":"flux","fields":{}}';
let invalidWrites = 0;
const invalidContext = {
  node: {setDirtyCanvas() {}},
  nodeKey: "identity",
  stateWidget: {
    value: invalidRaw,
    callback() { invalidWrites += 1; },
  },
  familyWidget: {value: "flux"},
  family: "flux",
  state: null,
  schemaNode: null,
  options: new Map(),
  body: new FakeElement("div"),
  status: new FakeElement("div"),
  invalid: false,
  loadGeneration: 0,
};
await initializeContext(invalidContext);
assert.equal(invalidContext.stateWidget.value, invalidRaw);
assert.equal(invalidWrites, 0);
const resetButtons = all(
  invalidContext.body,
  (item) => item.tagName === "BUTTON" && item.textContent === "Reset saved state",
);
assert.equal(resetButtons.length, 1);
resetButtons[0].listeners.click({preventDefault() {}, stopPropagation() {}});
assert.equal(invalidWrites, 1);
assert.equal(
  invalidContext.stateWidget.value,
  '{"version":1,"node":"identity","model_family":"flux","fields":{}}',
);
"""
    )
    test_file = tmp_path / "production_frontend_integration.mjs"
    test_file.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(test_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
