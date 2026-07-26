import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

let schemaPromise = null;

// ARCH_PT_CORE_START
const FAMILY_SET = new Set(["flux", "qwen"]);
const FOCUSED_NODES = Object.freeze({
  "ArchPtIdentity": "identity",
  "ArchPtPose": "pose",
  "ArchPtClothing": "clothing",
  "ArchPtEnvironment": "environment",
  "ArchPtCamera": "camera",
  "ArchPtLighting": "lighting",
});

function focusedNodeKey(nodeType) {
  return FOCUSED_NODES[nodeType] || null;
}

function controlKind(control) {
  if (control === "buttons") return "buttons";
  if (control === "searchable_options") return "searchable";
  if (control === "semantic_spectrum") return "spectrum";
  if (control === "free_text") return "text";
  throw new Error(`unsupported schema control: ${control}`);
}

function userSelectionMode(field) {
  const mode = field?.user_selection || "grouped";
  if (!["grouped", "additive"].includes(mode)) {
    throw new Error(`unsupported user selection mode: ${mode}`);
  }
  return mode;
}

function normalizeText(value) {
  if (typeof value !== "string") throw new Error("text must be a string");
  return value.trim().replace(/\s+/gu, " ");
}

function jsonCopy(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function createEmptyState(node, modelFamily = "flux") {
  if (typeof node !== "string" || !node) throw new Error("node must be set");
  if (!FAMILY_SET.has(modelFamily)) throw new Error("unsupported model family");
  return { version: 1, node, model_family: modelFamily, fields: {} };
}

function canonicalFragment(fragment) {
  const result = {
    instance_id: fragment.instance_id,
    source_option_id: fragment.source_option_id,
    label: fragment.label,
    node: fragment.node,
    field: fragment.field,
    group: fragment.group,
    text: normalizeText(fragment.text),
    model_family: fragment.model_family,
    lora_enabled: Boolean(fragment.lora_enabled),
  };
  if (fragment.lora && typeof fragment.lora === "object" && !Array.isArray(fragment.lora)) {
    result.lora = jsonCopy(fragment.lora);
  }
  return result;
}

function canonicalState(state) {
  const fields = Object.create(null);
  for (const fieldKey of Object.keys(state.fields || {}).sort()) {
    const field = state.fields[fieldKey] || {};
    fields[fieldKey] = {
      fragments: (field.fragments || []).map(canonicalFragment),
      specifics: normalizeText(field.specifics || ""),
    };
  }
  return {
    version: 1,
    node: state.node,
    model_family: state.model_family,
    fields,
  };
}

function serializeState(state) {
  return JSON.stringify(canonicalState(state));
}

function validateFragment(fragment, node, field, seen) {
  if (!fragment || typeof fragment !== "object" || Array.isArray(fragment)) {
    throw new Error(`field ${field} contains an invalid fragment`);
  }
  for (const key of [
    "instance_id",
    "source_option_id",
    "label",
    "node",
    "field",
    "group",
    "model_family",
  ]) {
    if (typeof fragment[key] !== "string" || !fragment[key].trim()) {
      throw new Error(`fragment ${key} must be a non-empty string`);
    }
  }
  if (typeof fragment.text !== "string") {
    throw new Error("fragment text must be a string");
  }
  if (fragment.node !== node || fragment.field !== field) {
    throw new Error("fragment node and field must match restored state");
  }
  if (!FAMILY_SET.has(fragment.model_family)) {
    throw new Error("fragment model family is unsupported");
  }
  if (typeof fragment.lora_enabled !== "boolean") {
    throw new Error("fragment lora_enabled must be boolean");
  }
  if (
    fragment.lora !== undefined &&
    fragment.lora !== null &&
    (typeof fragment.lora !== "object" || Array.isArray(fragment.lora))
  ) {
    throw new Error("fragment LoRA metadata must be an object");
  }
  if (seen.has(fragment.instance_id)) {
    throw new Error(`duplicate fragment instance id: ${fragment.instance_id}`);
  }
  seen.add(fragment.instance_id);
}

function restoreState(raw, expectedNode) {
  try {
    let state;
    try {
      state = JSON.parse(raw);
    } catch (_error) {
      throw new Error("state must be valid JSON");
    }
    if (!state || typeof state !== "object" || Array.isArray(state)) {
      throw new Error("state must be an object");
    }
    if (state.version !== 1) throw new Error("unsupported state version");
    if (state.node !== expectedNode) throw new Error("restored state node does not match this node");
    if (!FAMILY_SET.has(state.model_family)) throw new Error("unsupported state model family");
    if (!state.fields || typeof state.fields !== "object" || Array.isArray(state.fields)) {
      throw new Error("state fields must be an object");
    }
    const seen = new Set();
    for (const [fieldKey, field] of Object.entries(state.fields)) {
      if (!fieldKey || !field || typeof field !== "object" || Array.isArray(field)) {
        throw new Error("restored field is invalid");
      }
      if (!Array.isArray(field.fragments)) throw new Error(`field ${fieldKey} fragments must be a list`);
      if (typeof field.specifics !== "string") throw new Error(`field ${fieldKey} specifics must be text`);
      for (const fragment of field.fragments) validateFragment(fragment, expectedNode, fieldKey, seen);
    }
    return { ok: true, state: canonicalState(state), error: "" };
  } catch (error) {
    return { ok: false, state: null, error: String(error.message || error) };
  }
}

function editorRestoreDecision(raw, expectedNode, selectedFamily) {
  const restored = restoreState(raw, expectedNode);
  if (!restored.ok) {
    return {
      ok: false,
      state: null,
      error: restored.error,
      allow_reset: true,
    };
  }
  if (restored.state.model_family !== selectedFamily) {
    return {
      ok: true,
      state: setModelFamily(restored.state, selectedFamily),
      error: "",
      allow_reset: false,
    };
  }
  return {
    ok: true,
    state: restored.state,
    error: "",
    allow_reset: false,
  };
}

function stateCopy(state) {
  return canonicalState(jsonCopy(state));
}

function fieldState(state, fieldKey) {
  if (!state.fields[fieldKey]) {
    state.fields[fieldKey] = { fragments: [], specifics: "" };
  }
  return state.fields[fieldKey];
}

function optionPhrase(option, modelFamily) {
  const phrase = option?.phrases?.[modelFamily];
  if (typeof phrase !== "string" || !phrase.trim()) {
    throw new Error(`option has no ${modelFamily} phrase`);
  }
  return normalizeText(phrase);
}

function optionFragment(option, modelFamily, instanceId) {
  if (!option || typeof option !== "object") throw new Error("option is invalid");
  for (const key of ["id", "label", "node", "field", "group"]) {
    if (typeof option[key] !== "string" || !option[key].trim()) {
      throw new Error(`option ${key} must be set`);
    }
  }
  if (typeof instanceId !== "string" || !instanceId) throw new Error("instance id must be set");
  const fragment = {
    instance_id: instanceId,
    source_option_id: option.id,
    label: option.label,
    node: option.node,
    field: option.field,
    group: option.group,
    text: optionPhrase(option, modelFamily),
    model_family: modelFamily,
    lora_enabled: Boolean(option.lora && option.lora_enabled),
  };
  if (option.lora && typeof option.lora === "object" && !Array.isArray(option.lora)) {
    fragment.lora = jsonCopy(option.lora);
  }
  return canonicalFragment(fragment);
}

function buttonChoiceModels(options, state, modelFamily) {
  return options.map((option) => ({
    id: option.id,
    label: option.label,
    phrase: optionPhrase(option, modelFamily),
    selected: Boolean(
      state.fields?.[option.field]?.fragments?.some(
        (fragment) =>
          fragment.source_option_id === option.id &&
          fragment.group === option.group,
      ),
    ),
    lora_associated: Boolean(option.lora),
  }));
}

function createChoiceButtons(documentRef, models, onSelect) {
  return models.map((model) => {
    const button = documentRef.createElement("button");
    button.type = "button";
    button.textContent = model.lora_associated
      ? `${model.label} · LoRA`
      : model.label;
    button.title = `${model.label}: ${model.phrase}`;
    button.setAttribute("aria-label", button.title);
    button.setAttribute("aria-pressed", String(model.selected));
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      onSelect(model.id);
    });
    return button;
  });
}

function toggleOption(state, option, modelFamily, instanceId) {
  if (!FAMILY_SET.has(modelFamily)) throw new Error("unsupported model family");
  if (state.node !== option.node) throw new Error("option belongs to another node");
  const result = stateCopy(state);
  const field = fieldState(result, option.field);
  const isAlreadySelected = field.fragments.some(
    (fragment) =>
      fragment.source_option_id === option.id &&
      fragment.group === option.group,
  );
  if (isAlreadySelected) {
    field.fragments = field.fragments.filter(
      (fragment) =>
        !(
          fragment.source_option_id === option.id &&
          fragment.group === option.group
        ),
    );
    return result;
  }
  field.fragments = field.fragments.filter(
    (fragment) => fragment.group !== option.group,
  );
  field.fragments.push(optionFragment(option, modelFamily, instanceId));
  return result;
}

function editFragmentText(state, instanceId, text) {
  const result = stateCopy(state);
  for (const field of Object.values(result.fields)) {
    const fragment = field.fragments.find((item) => item.instance_id === instanceId);
    if (fragment) {
      fragment.text = normalizeText(text);
      return result;
    }
  }
  throw new Error(`unknown fragment: ${instanceId}`);
}

function removeFragmentById(state, instanceId) {
  const result = stateCopy(state);
  for (const field of Object.values(result.fields)) {
    const index = field.fragments.findIndex((item) => item.instance_id === instanceId);
    if (index >= 0) {
      field.fragments.splice(index, 1);
      return result;
    }
  }
  throw new Error(`unknown fragment: ${instanceId}`);
}

function toggleFragmentLora(state, instanceId, enabled) {
  const result = stateCopy(state);
  for (const field of Object.values(result.fields)) {
    const fragment = field.fragments.find((item) => item.instance_id === instanceId);
    if (fragment) {
      fragment.lora_enabled = Boolean(fragment.lora && enabled);
      return result;
    }
  }
  throw new Error(`unknown fragment: ${instanceId}`);
}

function setSpecificsText(state, fieldKey, text) {
  const result = stateCopy(state);
  fieldState(result, fieldKey).specifics = normalizeText(text);
  return result;
}

function setModelFamily(state, modelFamily) {
  if (!FAMILY_SET.has(modelFamily)) throw new Error("unsupported model family");
  const result = stateCopy(state);
  result.model_family = modelFamily;
  return result;
}

function spectrumSourceId(state, field) {
  return `spectrum.${state.node}.${field.key}`;
}

function spectrumStop(field, value) {
  if (!Array.isArray(field.spectrum) || !field.spectrum.length) {
    throw new Error("spectrum has no authored stops");
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) throw new Error("spectrum value must be finite");
  for (let index = 0; index < field.spectrum.length; index += 1) {
    const stop = field.spectrum[index];
    const final = index === field.spectrum.length - 1;
    if (
      numeric >= stop.minimum &&
      (numeric < stop.maximum || (final && numeric <= stop.maximum))
    ) {
      return stop;
    }
  }
  throw new Error("spectrum value is outside its authored range");
}

function spectrumValue(field, fragment = null) {
  if (!Array.isArray(field.spectrum) || !field.spectrum.length) {
    throw new Error("spectrum has no authored stops");
  }
  if (fragment) {
    const copiedText = normalizeText(fragment.text || "");
    const copiedFamily = fragment.model_family;
    const match = field.spectrum.find(
      (stop) =>
        typeof stop.phrases?.[copiedFamily] === "string" &&
        normalizeText(stop.phrases[copiedFamily]) === copiedText,
    );
    if (match) return (Number(match.minimum) + Number(match.maximum)) / 2;
  }
  return (
    Number(field.spectrum[0].minimum) +
    Number(field.spectrum[field.spectrum.length - 1].maximum)
  ) / 2;
}

function setSpectrum(state, field, modelFamily, enabled, value, instanceId) {
  if (!FAMILY_SET.has(modelFamily)) throw new Error("unsupported model family");
  const result = stateCopy(state);
  const current = fieldState(result, field.key);
  const sourceId = spectrumSourceId(result, field);
  const existing = current.fragments.find(
    (fragment) => fragment.source_option_id === sourceId,
  );
  if (!enabled) {
    current.fragments = current.fragments.filter(
      (fragment) => fragment.source_option_id !== sourceId,
    );
    return result;
  }
  const stop = spectrumStop(field, value);
  const phrase = normalizeText(stop.phrases?.[modelFamily] || "");
  if (!phrase) throw new Error(`spectrum has no ${modelFamily} phrase`);
  const fragment = canonicalFragment({
    instance_id: existing?.instance_id || instanceId,
    source_option_id: sourceId,
    label: phrase,
    node: result.node,
    field: field.key,
    group: field.key,
    text: phrase,
    model_family: modelFamily,
    lora_enabled: false,
  });
  current.fragments = current.fragments.filter(
    (item) => item.source_option_id !== sourceId,
  );
  current.fragments.push(fragment);
  return result;
}

function buildUserOptionPayload(input) {
  const payload = {
    label: normalizeText(input.label),
    node: normalizeText(input.node),
    field: normalizeText(input.field),
    model_family: normalizeText(input.model_family),
    phrase: normalizeText(input.phrase),
    builtin: false,
    lora_enabled: Boolean(input.lora && input.lora_enabled),
  };
  if (input.group !== undefined && input.group !== null) {
    payload.group = normalizeText(input.group);
  }
  if (!payload.label || !payload.node || !payload.field || !payload.phrase) {
    throw new Error("label, location, and phrase are required");
  }
  if ("group" in payload && !payload.group) {
    throw new Error("selection group is required when provided");
  }
  if (!FAMILY_SET.has(payload.model_family)) throw new Error("unsupported model family");
  if (input.lora !== undefined && input.lora !== null) {
    if (typeof input.lora !== "object" || Array.isArray(input.lora)) {
      throw new Error("LoRA metadata must be an object");
    }
    payload.lora = jsonCopy(input.lora);
  }
  return payload;
}

function optionsQuery(nodeKey, modelFamily, fieldKey = "") {
  const fieldFilter = fieldKey
    ? `&field=${encodeURIComponent(fieldKey)}`
    : "";
  return (
    `node=${encodeURIComponent(nodeKey)}` +
    `&model_family=${encodeURIComponent(modelFamily)}` +
    fieldFilter
  );
}

function buildOptionMutation(action, optionId, payload, fieldKey) {
  const suffix =
    action === "create" ? "" : `/${encodeURIComponent(optionId || "")}`;
  const methods = { create: "POST", update: "PATCH", delete: "DELETE" };
  const method = methods[action];
  if (!method) throw new Error(`unsupported option action: ${action}`);
  if (action !== "create" && !optionId) throw new Error("option id is required");
  if (action !== "delete" && (!payload || typeof payload !== "object")) {
    throw new Error("option payload is required");
  }
  if (typeof fieldKey !== "string" || !fieldKey) {
    throw new Error("affected field is required");
  }
  return {
    method,
    path: `/arch-prompt-tools/options${suffix}`,
    payload: action === "delete" ? null : payload,
    refresh_field: fieldKey,
  };
}
// ARCH_PT_CORE_END

function findWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function hideSerializedWidget(node, name) {
  const widget = findWidget(node, name);
  if (!widget || widget._archPtHidden) return widget;
  widget._archPtHidden = true;
  widget.type = "hidden";
  widget.options ||= {};
  widget.options.hidden = true;
  widget.hidden = true;
  widget.computeLayoutSize = () => ({
    minHeight: 0,
    maxHeight: 0,
    minWidth: 0,
  });
  widget.computeSize = () => [0, 0];
  for (const element of new Set([widget.element, widget.inputEl])) {
    if (!element) continue;
    element.hidden = true;
    element.style ||= {};
    element.style.display = "none";
    element.setAttribute?.("aria-hidden", "true");
    element.setAttribute?.("tabindex", "-1");
  }
  const originalSerializeValue = widget.serializeValue;
  widget.serializeValue = function () {
    return originalSerializeValue
      ? originalSerializeValue.apply(this, arguments)
      : this.value;
  };
  return widget;
}

function makeElement(tag, text = "", className = "") {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function makeButton(text, title, action, className = "") {
  const button = document.createElement("button");
  button.textContent = text;
  if (className) button.className = className;
  button.type = "button";
  button.title = title;
  button.setAttribute("aria-label", title);
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    action();
  });
  return button;
}

function editorStyles() {
  const style = document.createElement("style");
  style.textContent = `
    .arch-pt-editor { box-sizing:border-box; color:var(--input-text,#ddd); font:12px/1.35 sans-serif; padding:6px; display:grid; gap:6px; width:100%; max-height:620px; overflow:auto; }
    .arch-pt-editor * { box-sizing:border-box; }
    .arch-pt-toolbar,.arch-pt-row,.arch-pt-actions,.arch-pt-chip { display:flex; align-items:center; gap:5px; flex-wrap:wrap; }
    .arch-pt-toolbar { position:sticky; top:0; z-index:2; background:var(--comfy-menu-bg,#252525); padding:4px; border-radius:4px; }
    .arch-pt-status { flex:1; opacity:.82; min-width:120px; }
    .arch-pt-error { color:#ffaaa0; white-space:normal; }
    .arch-pt-editor details { border:1px solid rgba(255,255,255,.13); border-radius:5px; background:var(--comfy-input-bg,#202020); }
    .arch-pt-editor summary { cursor:pointer; font-weight:700; padding:6px; }
    .arch-pt-section { padding:0 6px 7px; display:grid; gap:8px; }
    .arch-pt-field { border-top:1px solid rgba(255,255,255,.09); padding-top:7px; display:grid; gap:5px; }
    .arch-pt-label { font-weight:650; }
    .arch-pt-editor button,.arch-pt-editor input,.arch-pt-editor textarea { color:inherit; background:var(--comfy-input-bg,#181818); border:1px solid rgba(255,255,255,.18); border-radius:4px; font:inherit; }
    .arch-pt-editor button { cursor:pointer; padding:3px 7px; }
    .arch-pt-editor button[aria-pressed="true"] { border-color:#80bfff; background:#234766; }
    .arch-pt-editor input[type="text"],.arch-pt-editor input[type="search"],.arch-pt-editor textarea { padding:5px; width:100%; }
    .arch-pt-editor textarea { min-height:46px; resize:vertical; }
    .arch-pt-chip { padding:4px; border-radius:5px; background:rgba(90,140,190,.16); }
    .arch-pt-chip input[type="text"] { flex:1; min-width:140px; width:auto; }
    .arch-pt-note { opacity:.68; font-size:11px; }
    .arch-pt-search-results { display:grid; gap:3px; max-height:190px; overflow:auto; }
    .arch-pt-option { padding:4px; border-left:2px solid rgba(255,255,255,.14); }
    .arch-pt-option-main { flex:1; text-align:left; min-width:110px; }
    .arch-pt-option-meta { opacity:.6; font-size:10px; }
    .arch-pt-form { display:grid; gap:5px; border:1px dashed rgba(255,255,255,.2); border-radius:4px; padding:6px; }
  `;
  return style;
}

function toast(message, severity = "info") {
  try {
    app.extensionManager?.toast?.add({
      severity,
      summary: "arch-pt Prompt Builder",
      detail: message,
      life: 4000,
    });
  } catch (_error) {
    console.log("[arch-pt]", message);
  }
}

async function requestJson(path, options = undefined) {
  const response = await api.fetchApi(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
  return data;
}

async function loadSchema() {
  if (!schemaPromise) {
    schemaPromise = requestJson("/arch-prompt-tools/schema").catch((error) => {
      schemaPromise = null;
      throw error;
    });
  }
  return schemaPromise;
}

async function loadOptions(nodeKey, modelFamily, fieldKey = "") {
  const optionsRoute = "/arch-prompt-tools/options";
  const query = optionsQuery(nodeKey, modelFamily, fieldKey);
  const payload = await requestJson(`${optionsRoute}?${query}`);
  return Array.isArray(payload.options) ? payload.options : [];
}

function newInstanceId() {
  if (globalThis.crypto?.randomUUID) return `copy.${globalThis.crypto.randomUUID()}`;
  return `copy.${Date.now().toString(36)}.${Math.random().toString(36).slice(2)}`;
}

function markDirty(context, nextState) {
  context.state = canonicalState(nextState);
  context.stateWidget.value = serializeState(context.state);
  context.stateWidget.callback?.(context.stateWidget.value, app.canvas, context.node);
  context.node.setDirtyCanvas(true, true);
}

function setStatus(context, message, isError = false) {
  context.status.textContent = message;
  context.status.classList.toggle("arch-pt-error", isError);
}

function ensureUiState(context) {
  context.uiState ||= {
    openSections: new Set(),
    searches: new Map(),
    focusKey: null,
  };
  return context.uiState;
}

function trackUsefulFocus(context, element, key) {
  element.dataset.uiKey = key;
  element.addEventListener("focus", () => {
    ensureUiState(context).focusKey = key;
  });
  return element;
}

function findUiKey(root, key) {
  if (!root || !key) return null;
  if (root.dataset?.uiKey === key) return root;
  for (const child of root.childNodes || []) {
    const match = findUiKey(child, key);
    if (match) return match;
  }
  return null;
}

function restoreUsefulFocus(context) {
  const key = ensureUiState(context).focusKey;
  const element = findUiKey(context.body, key);
  element?.focus?.({ preventScroll: true });
}

function configureDisclosure(context, details, key) {
  const state = ensureUiState(context);
  details.dataset.section = key;
  details.open = state.openSections.has(key);
  details.addEventListener("toggle", () => {
    if (details.open) state.openSections.add(key);
    else state.openSections.delete(key);
  });
}

function optionsByField(options) {
  const grouped = new Map();
  for (const option of options) {
    if (!grouped.has(option.field)) grouped.set(option.field, []);
    grouped.get(option.field).push(option);
  }
  return grouped;
}

function mergeFullOptions(context, knownFields, options, refreshTokenSnapshot) {
  const fullOptions = optionsByField(options);
  const merged = new Map();
  for (const fieldKey of knownFields) {
    const tokenAtStart = refreshTokenSnapshot.get(fieldKey) || 0;
    const currentToken = context.refreshTokens.get(fieldKey) || 0;
    merged.set(
      fieldKey,
      currentToken === tokenAtStart
        ? fullOptions.get(fieldKey) || []
        : context.options.get(fieldKey) || [],
    );
  }
  return merged;
}

async function refreshFieldOptions(
  context,
  fieldKey,
  dependencies = {},
) {
  const loader = dependencies.loader || loadOptions;
  context.refreshTokens ||= new Map();
  const token = (context.refreshTokens.get(fieldKey) || 0) + 1;
  context.refreshTokens.set(fieldKey, token);
  const family = context.family;
  const loadGeneration = context.loadGeneration;
  const stale = () =>
    context.family !== family ||
    context.loadGeneration !== loadGeneration ||
    context.refreshTokens.get(fieldKey) !== token;
  let fresh;
  try {
    fresh = await loader(context.nodeKey, family, fieldKey);
  } catch (error) {
    if (stale()) return { applied: false, stale: true };
    throw error;
  }
  if (stale()) return { applied: false, stale: true };
  context.options.set(fieldKey, fresh);
  return { applied: true, stale: false };
}

async function executeOptionMutation(
  context,
  action,
  optionId,
  payload,
  fieldKey,
  dependencies = {},
) {
  const mutation = buildOptionMutation(
    action,
    optionId,
    payload,
    fieldKey,
  );
  const request = dependencies.request || requestJson;
  const refresh = dependencies.refresh || refreshFieldOptions;
  const requestOptions = { method: mutation.method };
  if (mutation.payload !== null) {
    requestOptions.headers = { "Content-Type": "application/json" };
    requestOptions.body = JSON.stringify(mutation.payload);
  }
  const response = await request(mutation.path, requestOptions);
  try {
    const refreshResult = await refresh(context, mutation.refresh_field);
    return {
      committed: true,
      refresh_ok: true,
      refresh_field: mutation.refresh_field,
      refresh_result: refreshResult,
      response,
    };
  } catch (refreshError) {
    return {
      committed: true,
      refresh_ok: false,
      refresh_field: mutation.refresh_field,
      refresh_error: refreshError,
      response,
    };
  }
}

async function runMutationAction(context, key, button, action) {
  context.pendingMutations ||= new Set();
  if (context.pendingMutations.has(key)) return { skipped: true };
  context.pendingMutations.add(key);
  button.disabled = true;
  try {
    return await action();
  } finally {
    context.pendingMutations.delete(key);
    button.disabled = false;
  }
}

function reportMutationResult(context, result, committedMessage) {
  if (!result.committed) return;
  if (!result.refresh_ok) {
    context.pendingRefreshField = result.refresh_field;
    if (context.retryRefreshButton) context.retryRefreshButton.hidden = false;
    setStatus(
      context,
      `${committedMessage} Choice refresh failed; use Retry choices. ${
        result.refresh_error?.message || ""
      }`.trim(),
      true,
    );
    return;
  }
  context.pendingRefreshField = null;
  if (context.retryRefreshButton) context.retryRefreshButton.hidden = true;
  setStatus(context, committedMessage);
  if (result.refresh_result?.applied !== false) renderSections(context);
}

async function retryPendingRefresh(context) {
  const fieldKey = context.pendingRefreshField;
  if (!fieldKey) return;
  try {
    const result = await refreshFieldOptions(context, fieldKey);
    if (result.applied) {
      context.pendingRefreshField = null;
      context.retryRefreshButton.hidden = true;
      setStatus(context, "Choices refreshed.");
      renderSections(context);
    }
  } catch (error) {
    setStatus(context, `Choice refresh still unavailable: ${error.message}`, true);
  }
}

function renderError(context, message, allowReset = false) {
  context.body.replaceChildren();
  const box = makeElement("div", message, "arch-pt-error");
  const actions = makeElement("div", "", "arch-pt-actions");
  actions.append(makeButton("Retry", "Retry loading the editor", () => initializeContext(context)));
  if (allowReset) {
    actions.append(makeButton("Reset saved state", "Explicitly replace invalid state with a blank state", () => {
      const family = String(context.familyWidget.value || "flux");
      markDirty(context, createEmptyState(context.nodeKey, family));
      initializeContext(context);
    }));
  }
  context.body.append(box, actions);
  setStatus(context, "Editor needs attention", true);
}

function currentFamily(context) {
  return String(context.familyWidget.value || "flux");
}

function wrapFamilyWidget(context) {
  const widget = context.familyWidget;
  if (widget._archPtWrapped) return;
  widget._archPtWrapped = true;
  const callback = widget.callback;
  widget.callback = function (value) {
    const result = callback?.apply(this, arguments);
    if (!FAMILY_SET.has(value)) return result;
    context.family = value;
    const restored = restoreState(
      String(context.stateWidget.value || ""),
      context.nodeKey,
    );
    if (restored.ok) {
      markDirty(context, setModelFamily(restored.state, value));
      setStatus(context, `New selections use ${value}; existing copies are unchanged.`);
    }
    initializeContext(context);
    return result;
  };
}

function fieldFragments(context, fieldKey) {
  return context.state.fields[fieldKey]?.fragments || [];
}

function commitAndRender(context, state) {
  markDirty(context, state);
  renderSections(context);
}

function renderChips(context, field, target) {
  for (const fragment of fieldFragments(context, field.key)) {
    const chip = makeElement("div", "", "arch-pt-chip");
    const text = document.createElement("input");
    text.type = "text";
    text.value = fragment.text;
    text.title = `Copied from ${fragment.label}; edit affects this workflow only`;
    text.setAttribute("aria-label", `Edit copied ${fragment.label} text`);
    trackUsefulFocus(context, text, `chip:${fragment.instance_id}`);
    text.addEventListener("input", () => {
      try {
        markDirty(context, editFragmentText(context.state, fragment.instance_id, text.value));
      } catch (error) {
        setStatus(context, error.message, true);
      }
    });
    text.addEventListener("change", () => {
      try {
        commitAndRender(context, editFragmentText(context.state, fragment.instance_id, text.value));
      } catch (error) {
        setStatus(context, error.message, true);
      }
    });
    chip.append(text);
    if (fragment.lora) {
      const indicator = makeElement("span", "LoRA linked", "arch-pt-note");
      indicator.title = JSON.stringify(fragment.lora);
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = fragment.lora_enabled;
      toggle.title = "Request this associated LoRA (metadata only in this phase)";
      toggle.setAttribute("aria-label", `Enable LoRA associated with ${fragment.label}`);
      trackUsefulFocus(context, toggle, `lora:${fragment.instance_id}`);
      toggle.addEventListener("change", () =>
        commitAndRender(
          context,
          toggleFragmentLora(context.state, fragment.instance_id, toggle.checked),
        ),
      );
      chip.append(indicator, toggle);
    }
    chip.append(
      makeButton("Remove", `Remove copied ${fragment.label}`, () =>
        commitAndRender(context, removeFragmentById(context.state, fragment.instance_id)),
      ),
    );
    target.append(chip);
  }
}

function optionSelected(context, option) {
  return fieldFragments(context, option.field).some(
    (fragment) =>
      fragment.source_option_id === option.id && fragment.group === option.group,
  );
}

function selectOption(context, option) {
  try {
    commitAndRender(
      context,
      toggleOption(context.state, option, context.family, newInstanceId()),
    );
  } catch (error) {
    setStatus(context, error.message, true);
  }
}

function renderButtonOptions(context, field, target) {
  const row = makeElement("div", "", "arch-pt-row");
  const options = context.options.get(field.key) || [];
  const models = buttonChoiceModels(options, context.state, context.family);
  const buttons = createChoiceButtons(
    document,
    models,
    (optionId) => {
      const option = options.find((item) => item.id === optionId);
      if (option) selectOption(context, option);
    },
  );
  for (const [index, button] of buttons.entries()) {
    trackUsefulFocus(context, button, `option:${field.key}:${models[index].id}`);
    row.append(button);
  }
  if (!row.childNodes.length) row.append(makeElement("span", "No choices saved for this field.", "arch-pt-note"));
  target.append(row);
}

function renderOptionManagement(context, field, target) {
  const details = document.createElement("details");
  configureDisclosure(context, details, `manage:${field.key}`);
  const summary = document.createElement("summary");
  summary.textContent = "Manage choices";
  summary.title = `Create, duplicate, edit, or delete ${field.label} choices`;
  const body = makeElement("div", "", "arch-pt-section");
  const editorTarget = makeElement("div");
  body.append(
    makeButton("New option", `Create a user option for ${field.label}`, () =>
      showOptionEditor(context, field, editorTarget),
    ),
  );
  for (const option of context.options.get(field.key) || []) {
    body.append(optionRow(context, field, option, editorTarget));
  }
  body.append(editorTarget);
  details.append(summary, body);
  target.append(details);
}

function readableGroupLabel(group) {
  const words = group.replace(/[_-]+/gu, " ");
  return words.charAt(0).toLocaleUpperCase() + words.slice(1);
}

function showOptionEditor(context, field, target, sourceOption = null) {
  target.replaceChildren();
  const form = makeElement("div", "", "arch-pt-form");
  const editingUser = sourceOption && !sourceOption.builtin;
  const duplicate = sourceOption && sourceOption.builtin;
  form.append(makeElement("strong", editingUser ? "Edit user option" : duplicate ? "Duplicate built-in" : "New option"));

  const label = document.createElement("input");
  label.type = "text";
  label.placeholder = "Option label";
  label.setAttribute("aria-label", "User option label");
  label.value = sourceOption?.label || "";
  const phrase = document.createElement("textarea");
  phrase.placeholder = `${context.family} prompt phrase`;
  phrase.setAttribute("aria-label", "User option prompt phrase");
  phrase.value = sourceOption?.phrases?.[context.family] || "";
  const selectionMode = userSelectionMode(field);
  let groupControl;
  let groupSelect = null;
  if (selectionMode === "additive") {
    groupControl = makeElement(
      "div",
      "Stacks with other selections · selection group is assigned automatically",
      "arch-pt-note",
    );
  } else {
    groupControl = makeElement("label", "", "arch-pt-row");
    groupSelect = document.createElement("select");
    groupSelect.setAttribute("aria-label", "User option selection group");
    for (const groupId of field.groups || []) {
      const option = document.createElement("option");
      option.value = groupId;
      option.textContent = readableGroupLabel(groupId);
      groupSelect.append(option);
    }
    const requestedGroup = sourceOption?.group;
    groupSelect.value = field.groups?.includes(requestedGroup)
      ? requestedGroup
      : field.groups?.[0] || "";
    groupControl.append(
      makeElement("span", "Selection group"),
      groupSelect,
    );
  }
  const lora = document.createElement("textarea");
  lora.placeholder = 'Optional LoRA metadata JSON, for example {"name":"phone.safetensors","strength":0.8}';
  lora.setAttribute("aria-label", "Optional LoRA metadata JSON");
  lora.value = sourceOption?.lora ? JSON.stringify(sourceOption.lora) : "";
  const loraRow = makeElement("label", "", "arch-pt-row");
  const loraEnabled = document.createElement("input");
  loraEnabled.type = "checkbox";
  loraEnabled.checked = Boolean(sourceOption?.lora && sourceOption?.lora_enabled);
  loraEnabled.setAttribute("aria-label", "Enable copied LoRA association by default");
  loraRow.append(loraEnabled, makeElement("span", "LoRA association enabled by default"));

  const actions = makeElement("div", "", "arch-pt-actions");
  const mutationKey = editingUser
    ? `update:${sourceOption.id}`
    : `create:${field.key}`;
  const saveButton = makeButton("Save option", "Save option explicitly", async () => {
    try {
      const parsedLora = lora.value.trim() ? JSON.parse(lora.value) : null;
      const payload = buildUserOptionPayload({
        label: label.value,
        node: context.nodeKey,
        field: field.key,
        group: groupSelect?.value,
        model_family: context.family,
        phrase: phrase.value,
        lora: parsedLora,
        lora_enabled: loraEnabled.checked,
      });
      const result = await runMutationAction(
        context,
        mutationKey,
        saveButton,
        () =>
          executeOptionMutation(
            context,
            editingUser ? "update" : "create",
            editingUser ? sourceOption.id : null,
            payload,
            field.key,
          ),
      );
      if (!result.skipped) {
        reportMutationResult(
          context,
          result,
          editingUser ? "User option updated." : "User option saved.",
        );
      }
    } catch (error) {
      setStatus(context, `Save failed: ${error.message}`, true);
    }
  });
  actions.append(
    saveButton,
    makeButton("Cancel", "Cancel option editing", () => target.replaceChildren()),
  );
  form.append(label, phrase, groupControl, lora, loraRow, actions);
  target.append(form);
}

function optionRow(context, field, option, editorTarget) {
  const row = makeElement("div", "", "arch-pt-row arch-pt-option");
  const choose = makeButton(option.label, `Copy ${option.label} into this workflow`, () =>
    selectOption(context, option),
    "arch-pt-option-main",
  );
  trackUsefulFocus(context, choose, `search-option:${field.key}:${option.id}`);
  choose.setAttribute("aria-pressed", String(optionSelected(context, option)));
  const protection = makeElement(
    "span",
    option.builtin ? "Built-in · protected" : "User option",
    "arch-pt-option-meta",
  );
  const copiedPhrase = makeElement(
    "span",
    optionPhrase(option, context.family),
    "arch-pt-option-meta",
  );
  copiedPhrase.title = optionPhrase(option, context.family);
  row.append(choose, copiedPhrase, protection);
  if (option.lora) {
    const lora = makeElement("span", "LoRA", "arch-pt-option-meta");
    lora.title = JSON.stringify(option.lora);
    row.append(lora);
  }
  if (option.builtin) {
    row.append(
      makeButton("Duplicate", `Duplicate ${option.label} as a user option`, () =>
        showOptionEditor(context, field, editorTarget, option),
      ),
    );
  } else {
    const deleteButton = makeButton("Delete option", `Delete saved option ${option.label}`, async () => {
      if (!confirm(`Delete user option “${option.label}”? Existing workflow copies will remain.`)) return;
      try {
        const result = await runMutationAction(
          context,
          `delete:${option.id}`,
          deleteButton,
          () =>
            executeOptionMutation(
              context,
              "delete",
              option.id,
              null,
              field.key,
            ),
        );
        if (!result.skipped) {
          reportMutationResult(
            context,
            result,
            "User option deleted; existing copied chips were not changed.",
          );
        }
      } catch (error) {
        setStatus(context, `Delete failed: ${error.message}`, true);
      }
    });
    row.append(
      makeButton("Edit option", `Edit saved option ${option.label}`, () =>
        showOptionEditor(context, field, editorTarget, option),
      ),
      deleteButton,
    );
  }
  return row;
}

function renderSearchable(context, field, target) {
  const input = document.createElement("input");
  input.type = "search";
  input.value = ensureUiState(context).searches.get(field.key) || "";
  input.placeholder = `Search ${field.label.toLowerCase()}…`;
  input.setAttribute("aria-label", `Search ${field.label} options`);
  trackUsefulFocus(context, input, `search:${field.key}`);
  const results = makeElement("div", "", "arch-pt-search-results");
  const editorTarget = makeElement("div");
  const renderResults = () => {
    const needle = normalizeText(input.value).toLocaleLowerCase();
    const matches = (context.options.get(field.key) || [])
      .filter((option) =>
        `${option.label} ${optionPhrase(option, context.family)}`
          .toLocaleLowerCase()
          .includes(needle),
      )
      .slice(0, 40);
    results.replaceChildren(...matches.map((option) => optionRow(context, field, option, editorTarget)));
    if (!matches.length) results.append(makeElement("span", "No matching choices.", "arch-pt-note"));
  };
  input.addEventListener("input", () => {
    ensureUiState(context).searches.set(field.key, input.value);
    renderResults();
  });
  const actions = makeElement("div", "", "arch-pt-actions");
  actions.append(
    makeButton("New option", `Create a user option for ${field.label}`, () =>
      showOptionEditor(context, field, editorTarget),
    ),
  );
  target.append(input, actions, results, editorTarget);
  renderResults();
}

function spectrumFragment(context, field) {
  const sourceId = spectrumSourceId(context.state, field);
  return fieldFragments(context, field.key).find(
    (fragment) => fragment.source_option_id === sourceId,
  );
}

function spectrumDescriptionId(context, field) {
  const editorId = String(context.editorId || context.nodeKey || "editor")
    .replace(/[^A-Za-z0-9_-]/gu, "-");
  return `arch-pt-spectrum-${editorId}-${field.key}`;
}

function authoredSpectrumPhrase(field, family, value) {
  return normalizeText(spectrumStop(field, Number(value)).phrases?.[family] || "");
}

function renderSpectrum(context, field, target) {
  const row = makeElement("div", "", "arch-pt-row");
  const currentFragment = spectrumFragment(context, field);
  const enabled = document.createElement("input");
  enabled.type = "checkbox";
  enabled.checked = Boolean(currentFragment);
  enabled.setAttribute("aria-label", `Enable ${field.label}`);
  trackUsefulFocus(context, enabled, `spectrum-enable:${field.key}`);
  const slider = document.createElement("input");
  slider.type = "range";
  slider.min = String(field.spectrum[0].minimum);
  slider.max = String(field.spectrum[field.spectrum.length - 1].maximum);
  slider.step = "0.001";
  slider.value = String(spectrumValue(field, currentFragment));
  slider.disabled = !enabled.checked;
  slider.setAttribute("aria-label", `${field.label} semantic level`);
  trackUsefulFocus(context, slider, `spectrum-slider:${field.key}`);
  const phraseText =
    currentFragment?.text || "Disabled — contributes nothing";
  const phrase = makeElement(
    "span",
    phraseText,
    "arch-pt-note",
  );
  phrase.id = spectrumDescriptionId(context, field);
  slider.setAttribute("aria-describedby", phrase.id);
  slider.setAttribute("aria-valuetext", phraseText);
  slider.addEventListener("input", () => {
    const semanticPhrase = authoredSpectrumPhrase(
      field,
      context.family,
      slider.value,
    );
    phrase.textContent = semanticPhrase;
    slider.setAttribute("aria-valuetext", semanticPhrase);
  });
  const apply = () => {
    try {
      commitAndRender(
        context,
        setSpectrum(
          context.state,
          field,
          context.family,
          enabled.checked,
          Number(slider.value),
          newInstanceId(),
        ),
      );
    } catch (error) {
      setStatus(context, error.message, true);
    }
  };
  enabled.addEventListener("change", apply);
  slider.addEventListener("change", apply);
  row.append(enabled, makeElement("span", "Enable"), slider, phrase);
  target.append(row);
}

function renderSpecifics(context, field, target) {
  const label = makeElement(
    "label",
    field.control === "free_text" ? field.label : "Additional specifics",
    "arch-pt-note",
  );
  const input = document.createElement("textarea");
  input.value = context.state.fields[field.key]?.specifics || "";
  input.placeholder =
    field.control === "free_text"
      ? `Type ${field.label.toLowerCase()}…`
      : `Optional details not covered by ${field.label.toLowerCase()} choices…`;
  input.setAttribute("aria-label", `Additional specifics for ${field.label}`);
  trackUsefulFocus(context, input, `specifics:${field.key}`);
  input.addEventListener("input", () => {
    try {
      markDirty(context, setSpecificsText(context.state, field.key, input.value));
    } catch (error) {
      setStatus(context, error.message, true);
    }
  });
  input.addEventListener("change", () => {
    try {
      commitAndRender(context, setSpecificsText(context.state, field.key, input.value));
    } catch (error) {
      setStatus(context, error.message, true);
    }
  });
  target.append(label, input);
}

function renderField(context, field) {
  const wrapper = makeElement("div", "", "arch-pt-field");
  const label = makeElement("div", field.label, "arch-pt-label");
  label.title =
    field.control === "semantic_spectrum"
      ? "Disabled by default; uses authored descriptive phrases rather than numbers."
      : "Selections are copied into this workflow and can be edited below.";
  wrapper.append(label);
  const kind = controlKind(field.control);
  if (kind === "buttons") {
    renderButtonOptions(context, field, wrapper);
    renderOptionManagement(context, field, wrapper);
  }
  if (kind === "searchable") renderSearchable(context, field, wrapper);
  if (kind === "spectrum") renderSpectrum(context, field, wrapper);
  renderChips(context, field, wrapper);
  renderSpecifics(context, field, wrapper);
  return wrapper;
}

function renderSections(context) {
  if (context.invalid || !context.schemaNode || !context.state) return;
  const fragment = document.createDocumentFragment();
  for (const section of context.schemaNode.sections) {
    const details = document.createElement("details");
    configureDisclosure(context, details, section.key);
    const summary = document.createElement("summary");
    summary.textContent = section.label;
    summary.title = `Show or hide ${section.label}`;
    const body = makeElement("div", "", "arch-pt-section");
    for (const field of section.fields) body.append(renderField(context, field));
    details.append(summary, body);
    fragment.append(details);
  }
  context.body.replaceChildren(fragment);
  restoreUsefulFocus(context);
  context.node.setDirtyCanvas(true, true);
}

async function initializeContext(context) {
  context.loadGeneration += 1;
  const loadGeneration = context.loadGeneration;
  context.refreshTokens ||= new Map();
  const refreshTokenSnapshot = new Map(context.refreshTokens);
  context.invalid = false;
  setStatus(context, "Loading schema and choices…");
  context.body.replaceChildren(makeElement("div", "Loading…", "arch-pt-note"));
  try {
    context.family = currentFamily(context);
    const restored = editorRestoreDecision(
      String(context.stateWidget.value || ""),
      context.nodeKey,
      context.family,
    );
    if (!restored.ok) {
      context.invalid = true;
      renderError(
        context,
        `Saved prompt state is invalid: ${restored.error}. It was not overwritten.`,
        restored.allow_reset,
      );
      return;
    }
    const [schema, options] = await Promise.all([
      loadSchema(),
      loadOptions(context.nodeKey, context.family),
    ]);
    if (loadGeneration !== context.loadGeneration) return;
    const schemaNode = schema.nodes?.find((node) => node.key === context.nodeKey);
    if (!schemaNode) throw new Error(`schema does not define ${context.nodeKey}`);
    if (!schema.families?.includes(context.family)) {
      throw new Error(`schema does not support ${context.family}`);
    }
    const knownFields = new Set(
      schemaNode.sections.flatMap((section) => section.fields.map((field) => field.key)),
    );
    const unknownField = Object.keys(restored.state.fields).find((key) => !knownFields.has(key));
    if (unknownField) {
      context.invalid = true;
      renderError(context, `Saved state contains unknown field ${unknownField}. It was not overwritten.`, true);
      return;
    }
    context.state = restored.state;
    context.schemaNode = schemaNode;
    context.options = mergeFullOptions(
      context,
      knownFields,
      options,
      refreshTokenSnapshot,
    );
    setStatus(
      context,
      `Ready · ${context.family} affects future selections only · ${options.length} choices`,
    );
    renderSections(context);
  } catch (error) {
    if (loadGeneration !== context.loadGeneration) return;
    renderError(context, `Could not load the prompt editor: ${error.message}`);
  }
}

function installEditor(node, nodeKey) {
  if (node._archPtEditorInstalled) return;
  node._archPtEditorInstalled = true;
  const rawStateWidget = findWidget(node, "state_json");
  const familyWidget = findWidget(node, "model_family");
  if (!rawStateWidget || !familyWidget || typeof node.addDOMWidget !== "function") {
    toast("This ComfyUI build cannot add the arch-pt editor; serialized backend fields remain available.", "warn");
    return;
  }
  const stateWidget = hideSerializedWidget(node, "state_json");

  const root = makeElement("div", "", "arch-pt-editor");
  root.append(editorStyles());
  const toolbar = makeElement("div", "", "arch-pt-toolbar");
  const status = makeElement("div", "", "arch-pt-status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const retryRefreshButton = makeButton(
    "Retry choices",
    "Retry refreshing the last saved field without repeating the mutation",
    () => retryPendingRefresh(context),
  );
  retryRefreshButton.hidden = true;
  toolbar.append(
    status,
    retryRefreshButton,
    makeButton("Retry", "Retry loading schema and choices", () => initializeContext(context)),
  );
  const body = makeElement("div");
  root.append(toolbar, body);

  const context = {
    node,
    nodeKey,
    stateWidget,
    familyWidget,
    root,
    body,
    status,
    retryRefreshButton,
    state: null,
    schemaNode: null,
    options: new Map(),
    family: currentFamily({ familyWidget }),
    invalid: false,
    loadGeneration: 0,
    refreshTokens: new Map(),
    pendingMutations: new Set(),
    pendingRefreshField: null,
    editorId: newInstanceId(),
  };
  node._archPtEditorContext = context;
  const domWidget = node.addDOMWidget("arch_pt_editor", "div", root, {
    serialize: false,
    getMinHeight: () => 260,
    getMaxHeight: () => 680,
    getValue: () => "",
    setValue: () => {},
  });
  if (domWidget) {
    domWidget.serialize = false;
    domWidget.serializeValue = () => undefined;
    domWidget.computeSize = () => [Math.max(node.size?.[0] || 420, 420), 560];
  }
  wrapFamilyWidget(context);
  node.setSize?.([Math.max(node.size?.[0] || 420, 420), Math.max(node.size?.[1] || 0, 640)]);
  initializeContext(context);
}

function extendFocusedNode(nodeType, nodeKey) {
  if (nodeType.prototype._archPtExtended) return;
  nodeType.prototype._archPtExtended = true;
  const onNodeCreated = nodeType.prototype.onNodeCreated;
  const onConfigure = nodeType.prototype.onConfigure;
  nodeType.prototype.onNodeCreated = function () {
    const result = onNodeCreated?.apply(this, arguments);
    try {
      installEditor(this, nodeKey);
    } catch (error) {
      console.error("[arch-pt] editor setup failed", error);
    }
    return result;
  };
  nodeType.prototype.onConfigure = function () {
    const result = onConfigure?.apply(this, arguments);
    const node = this;
    setTimeout(() => {
      if (node._archPtEditorContext) initializeContext(node._archPtEditorContext);
    }, 0);
    return result;
  };
}

app.registerExtension({
  name: "arch-pt.prompt-tools",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const nodeKey = focusedNodeKey(nodeData?.name);
    if (nodeKey) extendFocusedNode(nodeType, nodeKey);
  },
});

export {
  buildOptionMutation,
  buildUserOptionPayload,
  buttonChoiceModels,
  controlKind,
  createChoiceButtons,
  createEmptyState,
  editFragmentText,
  editorRestoreDecision,
  executeOptionMutation,
  focusedNodeKey,
  optionsQuery,
  removeFragmentById,
  restoreState,
  serializeState,
  setModelFamily,
  setSpecificsText,
  setSpectrum,
  spectrumValue,
  toggleFragmentLora,
  toggleOption,
};
