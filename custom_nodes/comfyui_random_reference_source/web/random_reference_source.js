import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { installReferenceBrowser, openReferenceBrowser, refreshReferenceBrowser, refreshReferencePrompt } from "./reference_browser.js";
import { buildCombinedPromptPreview } from "./prompt_preview.js";

const referenceNodes = new Set();

const NODE_NAME = "RandomReferenceImageSource";
const SELECTION_POLICIES = new Set([
  "random_each_queue",
  "seeded",
  "sequential",
]);
const CONTROL_MODES = new Set([
  "fixed",
  "increment",
  "decrement",
  "randomize",
]);

function notify(summary, severity = "info") {
  if (app.extensionManager?.toast?.add) {
    app.extensionManager.toast.add({ severity, summary, life: 3600 });
  } else {
    console.log(`[arch-Random Reference] ${summary}`);
  }
}

function findWidget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

// Push a value into a widget the same way a user edit would, so callbacks and
// the canvas stay in sync.
function setWidgetValue(node, widget, value) {
  if (!widget) return;
  widget.value = value;
  widget.callback?.(value, app.canvas, node);
  node.setDirtyCanvas(true, true);
}

function normalizeControlMode(value) {
  return CONTROL_MODES.has(value) ? value : "randomize";
}

function ensurePositiveSeed(node) {
  const seedWidget = findWidget(node, "seed");
  const seed = Number(seedWidget?.value);
  if (!Number.isFinite(seed) || seed < 1) {
    setWidgetValue(node, seedWidget, 1);
  }
}

function syncSequentialSeedControl(node) {
  const policy = findWidget(node, "selection_policy")?.value;
  if (policy === "random_each_queue") return;
  ensurePositiveSeed(node);
  setWidgetValue(node, findWidget(node, "control_after_generate"),
    policy === "sequential" ? "increment" : "fixed");
}

function promptContext(node) {
  const payload = referencePayload(node);
  return payload.favorite !== "None" ? JSON.stringify(["favorite", payload.favorite])
    : JSON.stringify(["source", payload.source_mode, payload.folder, payload.selected_images]);
}

function promptDrafts(node) {
  node.properties ||= {};
  return node.properties.archReferencePromptDrafts ||= {};
}

function rememberPromptDraft(node) {
  const key = promptContext(node);
  const drafts = promptDrafts(node);
  const text = findWidget(node, "favorite_prompt")?.value || "";
  drafts[key] ||= {text, name: ""};
  drafts[key].text = text;
  return drafts[key];
}

function promptState(node) {
  const draft = rememberPromptDraft(node);
  const favorite = referencePayload(node).favorite;
  const saved = node._archReferencePresets?.[favorite];
  const baseline = saved?.prompt_text || "";
  return {text: draft.text, name: draft.name, favorite,
    saved: Boolean(saved), modified: draft.text.trim() !== baseline.trim(), baseline};
}

function setPromptName(node, name) {
  rememberPromptDraft(node).name = name;
  node.graph?.change?.();
}

function applySource(node, values, {restoreDraft = true} = {}) {
  node._archSourceIntent = (node._archSourceIntent || 0) + 1;
  if (["favorite", "source_mode", "folder", "selected_images"].some(name => name in values))
    node._archSourceChoice = (node._archSourceChoice || 0) + 1;
  const oldKey = promptContext(node);
  rememberPromptDraft(node);
  // One atomic update: field callbacks must not detach a favorite midway
  // through applying that favorite or briefly preview a mixture of sources.
  node._archApplyingSource = (node._archApplyingSource || 0) + 1;
  try {
    for (const [name, value] of Object.entries(values)) {
      const widget = findWidget(node, name);
      if (widget) widget.value = value;
    }
    const nextKey = promptContext(node);
    const draft = promptDrafts(node)[nextKey];
    if (restoreDraft && nextKey !== oldKey && draft) findWidget(node, "favorite_prompt").value = draft.text;
  } finally {
    node._archApplyingSource--;
  }
  rememberPromptDraft(node);
  node.graph?.change?.();
  node.setDirtyCanvas(true, true);
  schedulePreview(node);
  refreshReferenceBrowser(node);
}

function selectFolder(node, folder) {
  applySource(node, {source_mode: "folder", folder, selected_images: "",
    favorite: "None"});
}

function encodeImagePaths(paths) {
  return paths.map(path => /[,"\n\r]/.test(path) ? `"${path.replaceAll('"', '""')}"` : path).join("\n");
}

function selectImages(node, paths) {
  applySource(node, {source_mode: "selection", folder: "", selected_images: encodeImagePaths(paths),
    include_subfolders: false, favorite: "None"});
}

function selectLibrary(node, data, includePrompt = false) {
  const values = {source_mode: "selection", folder: "", selected_images: encodeImagePaths(data.paths || []),
    include_subfolders: false, favorite: "None"};
  if (includePrompt) values.favorite_prompt = data.positive_prompt || "";
  applySource(node, values, {restoreDraft: false});
}

function updateLastUsed(node, metadata) {
  const valid = metadata && typeof metadata.selected_file === "string" && metadata.selected_file;
  node._archLastUsed = valid ? {selected_file: metadata.selected_file,
    selected_name: typeof metadata.selected_name === "string" ? metadata.selected_name
      : metadata.selected_file.split(/[\\/]/).pop()} : null;
  node.properties ||= {};
  if (node._archLastUsed) node.properties.archReferenceLastUsed = {...node._archLastUsed};
  else delete node.properties.archReferenceLastUsed;
  const button = findWidget(node, "Use this image again");
  if (button) { button.disabled = !valid; button.options ||= {}; button.options.disabled = !valid; }
  if (node._archLastUsedContainer) {
    node._archLastUsedContainer.textContent = `Last used: ${node._archLastUsed?.selected_name || "No execution yet"}`;
    node._archLastUsedContainer.title = node._archLastUsed?.selected_file || "";
  }
  node.setDirtyCanvas(true, true);
}

function compactWidgets(node) {
  const visible = new Set(["selection_policy"]);
  if (findWidget(node, "selection_policy")?.value !== "random_each_queue") visible.add("seed");
  for (const widget of node.widgets || []) {
    if (!widget._archOriginal) widget._archOriginal = {type: widget.type, computeSize: widget.computeSize};
    if (["lane", "source_mode", "favorite", "folder", "selected_images", "seed",
         "control_after_generate", "include_subfolders", "favorite_prompt"].includes(widget.name)) {
      const hidden = !visible.has(widget.name);
      // Current LiteGraph concrete widgets still draw when only their type is
      // changed. Its visibility flag excludes them from drawing and layout.
      widget.hidden = hidden;
      widget.type = hidden ? "hidden" : widget._archOriginal.type;
      widget.computeSize = hidden ? () => [0, -4] : widget._archOriginal.computeSize;
      if (widget.inputEl) widget.inputEl.style.display = hidden ? "none" : "";
      if (widget.element) widget.element.hidden = hidden;
    }
  }
  const policy = findWidget(node, "selection_policy");
  if (policy) policy.label = "Image selection";
  const seed = findWidget(node, "seed");
  if (seed) seed.label = findWidget(node, "selection_policy")?.value === "sequential" ? "Next image index" : "Repeatable seed";
}

// Older workflows were saved either as the original compact eight backend
// values, or with sparse holes from the two interleaved transient buttons.
// Restore those known shapes by backend widget name before they are resaved in
// the current dense order.
function migrateWorkflowWidgetValues(node, values) {
  if (!Array.isArray(values)) return false;

  let restored = null;
  if (
    values.length === 8 &&
    SELECTION_POLICIES.has(values[5]) &&
    Number.isFinite(Number(values[6]))
  ) {
    restored = {
      lane: values[0],
      source_mode: values[1],
      favorite: values[2],
      folder: values[3],
      selected_images: values[4],
      selection_policy: values[5],
      seed: Number(values[6]),
      control_after_generate: "randomize",
      include_subfolders: Boolean(values[7]),
    };
  } else if (
    values.length >= 11 &&
    values[4] == null &&
    values[6] == null &&
    SELECTION_POLICIES.has(values[7]) &&
    Number.isFinite(Number(values[8]))
  ) {
    // When a compact legacy workflow first encountered the interleaved
    // buttons, its include_subfolders value was consumed by the newly added
    // control widget and then resaved at slot 9. A real control mode is a
    // string; a boolean in that slot is therefore the displaced legacy value.
    const displacedInclude = typeof values[9] === "boolean" ? values[9] : null;
    restored = {
      lane: values[0],
      source_mode: values[1],
      favorite: values[2],
      folder: values[3],
      selected_images: values[5] ?? "",
      selection_policy: values[7],
      seed: Number(values[8]),
      control_after_generate: normalizeControlMode(values[9]),
      include_subfolders:
        displacedInclude === null ? Boolean(values[10]) : displacedInclude,
    };
  }

  if (!restored) return false;
  for (const [name, value] of Object.entries(restored)) {
    const widget = findWidget(node, name);
    if (widget) widget.value = value;
  }
  return true;
}

async function callDialog(endpoint, initialDir) {
  const response = await api.fetchApi(`/arch-random-reference/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initial_dir: initialDir || "" }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      data?.error || `Dialog request failed (${response.status})`,
    );
  }
  return data;
}

async function callPresetApi(path = "", options = {}) {
  const response = await api.fetchApi(`/arch-random-reference/presets${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data?.error || `Favorite request failed (${response.status})`);
  }
  return data;
}

function refreshFavoriteOptions(node, presets, preservePendingChoice = false) {
  node._archReferencePresets = presets || {};
  const widget = findWidget(node, "favorite");
  if (!widget) return;
  const values = [
    "None",
    ...Object.keys(node._archReferencePresets).sort((a, b) =>
      a.localeCompare(b, undefined, { sensitivity: "base" }),
    ),
  ];
  widget.options ||= {};
  widget.options.values = values;
  if (!values.includes(widget.value)) {
    const intent = node._archSourceIntent;
    const choice = node._archSourceChoice;
    applySource(node, {favorite: "None"}, {restoreDraft: false});
    if (preservePendingChoice) {
      node._archSourceIntent = intent;
      node._archSourceChoice = choice;
    }
  }
}

function applyFavorite(node) {
  const name = findWidget(node, "favorite")?.value || "None";
  const preset = node._archReferencePresets?.[name];
  if (!preset) {
    applySource(node, {favorite: "None"});
    return;
  }
  applySource(node, {favorite: name, source_mode: preset.kind || "folder",
    folder: preset.folder || "", selected_images: encodeImagePaths(preset.images || []),
    include_subfolders: Boolean(preset.include_subfolders), favorite_prompt:
      promptDrafts(node)[JSON.stringify(["favorite", name])]?.text ?? preset.prompt_text ?? ""});
}

async function refreshPresets(node, applyCurrent = false) {
  const data = await callPresetApi();
  refreshFavoriteOptions(node, data.presets);
  if (applyCurrent) applyFavorite(node);
}

async function loadSingleImage(node, file) {
  if (!file) return;
  const intent = node._archSourceIntent = (node._archSourceIntent || 0) + 1;
  node._archSourceChoice = (node._archSourceChoice || 0) + 1;
  const body = new FormData();
  body.append("image", file);
  body.append("type", "input");
  body.append("overwrite", "false");
  const response = await api.fetchApi("/upload/image", {method: "POST", body});
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.name) throw new Error(data.error || "Could not load the image.");
  if (!referenceNodes.has(node) || node._archSourceIntent !== intent) return;
  const path = [data.subfolder, data.name].filter(Boolean).join("/");
  selectImages(node, [path]);
}

function pickSingleImage(node) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.ppm";
  input.multiple = false;
  input.style.display = "none";
  input.addEventListener("cancel", () => input.remove(), {once: true});
  input.addEventListener("change", async () => {
    try { await loadSingleImage(node, input.files?.[0]); }
    catch (error) { notify(String(error.message || error), "error"); }
    finally { input.remove(); }
  }, {once: true});
  document.body.append(input);
  input.click();
}

async function chooseFavorite(node, name) {
  node._archSourceChoice = (node._archSourceChoice || 0) + 1;
  const intent = node._archSourceIntent = (node._archSourceIntent || 0) + 1;
  const data = await callPresetApi();
  if (!referenceNodes.has(node) || intent !== node._archSourceIntent) return;
  refreshFavoriteOptions(node, data.presets);
  const preset = node._archReferencePresets?.[name];
  if (!preset) throw new Error("That favorite no longer exists.");
  const draft = promptDrafts(node)[JSON.stringify(["favorite", name])];
  applySource(node, {favorite: name, source_mode: preset.kind || "folder",
    folder: preset.folder || "", selected_images: encodeImagePaths(preset.images || []),
    include_subfolders: Boolean(preset.include_subfolders), favorite_prompt: draft?.text ?? preset.prompt_text ?? ""});
}

function favoritePayload(node, name) {
  return {
    ...referencePayload(node),
    name,
    prompt_text: findWidget(node, "favorite_prompt")?.value || "",
  };
}

async function saveFavorite(node, name, mode = "update", paths = null, renamedFrom = null) {
  const originalKey = promptContext(node);
  const originalChoice = node._archSourceChoice || 0;
  const snapshot = favoritePayload(node, name);
  const originalText = snapshot.prompt_text;
  const originalFavorite = snapshot.favorite;
  const editedName = renamedFrom || name;
  const existing = node._archReferencePresets?.[editedName];
  // Changing membership is not a request to overwrite the target's text.
  if (paths !== null && existing) snapshot.prompt_text = existing.prompt_text || "";
  const peers = new Map([...referenceNodes].filter(source => source !== node).map(source => [source, {
    choice: source._archSourceChoice || 0,
    baseline: source._archReferencePresets?.[editedName]?.prompt_text || "",
  }]));
  if (paths) Object.assign(snapshot, {source_mode: "selection", folder: "",
    selected_images: encodeImagePaths(paths), include_subfolders: false, favorite: "None"});
  if (renamedFrom) snapshot.original_name = renamedFrom;
  const originalName = rememberPromptDraft(node).name;
  const data = await callPresetApi("", {
    method: "POST",
    body: JSON.stringify({...snapshot, save_mode: mode}),
  });
  // Renaming removes the old entry. Capture source intent before refreshing
  // options detaches that now-missing name, so the successful save still applies.
  const sameSource = referenceNodes.has(node) && promptContext(node) === originalKey && (node._archSourceChoice || 0) === originalChoice;
  const currentText = findWidget(node, "favorite_prompt")?.value || "";
  const currentName = rememberPromptDraft(node).name;
  if (referenceNodes.has(node)) refreshFavoriteOptions(node, data.presets, !sameSource);
  if (sameSource) {
    const membershipReplacement = paths !== null && existing;
    const editedDuringSave = currentText !== originalText;
    const modifiedTargetDraft = originalFavorite === editedName &&
      originalText.trim() !== (existing?.prompt_text || "").trim();
    const selectedText = membershipReplacement && !editedDuringSave && !modifiedTargetDraft
      ? data.presets?.[data.name]?.prompt_text || "" : currentText;
    const newKey = JSON.stringify(["favorite", data.name]);
    promptDrafts(node)[newKey] = {text: selectedText,
      name: mode === "create" && currentName === originalName ? "" : currentName};
    applySource(node, {favorite: data.name});
    applyFavorite(node);
    // A slow save must not erase text typed while the request was in flight.
    applySource(node, {favorite_prompt: selectedText});
  }
  for (const source of referenceNodes) {
    if (source !== node) {
      const before = peers.get(source);
      const follows = before && referencePayload(source).favorite === editedName &&
        (source._archSourceChoice || 0) === before.choice;
      const draft = follows ? {...rememberPromptDraft(source)} : null;
      const preset = data.presets?.[data.name];
      if (follows && preset) {
        const text = draft.text.trim() === before.baseline.trim() ? preset.prompt_text || "" : draft.text;
        promptDrafts(source)[JSON.stringify(["favorite", data.name])] = {...draft, text};
        // Apply the rename before refreshing options can detach the old name.
        applySource(source, {favorite: data.name, source_mode: preset.kind || "folder",
          folder: preset.folder || "", selected_images: encodeImagePaths(preset.images || []),
          include_subfolders: Boolean(preset.include_subfolders), favorite_prompt: text}, {restoreDraft: false});
      }
      refreshFavoriteOptions(source, data.presets, !follows);
    }
    refreshReferenceBrowser(source);
  }
  notify(`Saved favorite “${data.name}”.`);
}

async function deleteFavorite(node, name) {
  const data = await callPresetApi("", {
    method: "DELETE",
    body: JSON.stringify({ name }),
  });
  for (const source of referenceNodes) refreshFavoriteOptions(source, data.presets);
  refreshReferenceBrowser(node);
  notify(`Deleted favorite “${name}”.`);
}

function referencePayload(node) {
  return {
    lane: findWidget(node, "lane")?.value || "",
    source_mode: findWidget(node, "source_mode")?.value || "auto",
    favorite: findWidget(node, "favorite")?.value || "None",
    folder: findWidget(node, "folder")?.value ?? "",
    selected_images: findWidget(node, "selected_images")?.value || "",
    selection_policy:
      findWidget(node, "selection_policy")?.value || "random_each_queue",
    seed: findWidget(node, "seed")?.value || 0,
    include_subfolders: Boolean(findWidget(node, "include_subfolders")?.value),
  };
}

async function fetchPreview(node, options = {}) {
  const payload = {...referencePayload(node), ...options};
  const response = await api.fetchApi("/arch-random-reference/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data?.error || `Preview failed (${response.status})`);
  }
  const folderName = String(payload.folder).split(/[\\/]/).filter(Boolean).pop() || "Input folder";
  return {...data, source_label: payload.favorite !== "None" ? payload.favorite
    : payload.source_mode === "folder" ? folderName : "Selected images"};
}

function renderPreview(container, data) {
  const image = data?.images?.[0];
  container.replaceChildren();
  const source = document.createElement("div");
  source.style.cssText = "font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
  source.textContent = data?.source_label || "No source selected";
  container.append(source);
  if (image) {
    const img = document.createElement("img");
    img.src = image.thumbnail_data_url;
    img.alt = image.name;
    img.style.cssText = "width:100%;height:70px;object-fit:contain;border-radius:4px";
    container.append(img);
  }
  const status = document.createElement("div");
  status.style.cssText = "font-size:11px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
  status.textContent = image
    ? `${data.pool_size} image(s) · ${data.preview_is_exact_next ? "Next: " + image.name : "Pool preview · chosen at run time"}`
    : "Choose a folder or images in Reference Browser";
  container.append(status);
  container.title = data?.source_folder || "";
}

function schedulePreview(node) {
  clearTimeout(node._archReferencePreviewTimer);
  const revision = (node._archPreviewRevision || 0) + 1;
  node._archPreviewRevision = revision;
  compactWidgets(node);
  node._archReferencePreviewTimer = setTimeout(async () => {
    const container = node._archReferencePreviewContainer;
    if (!container) return;
    try {
      const payload = referencePayload(node);
      if (payload.favorite === "None" && !String(findWidget(node,
          payload.source_mode === "selection" ? "selected_images" : "folder")?.value || "").trim()) {
        renderPreview(container, null);
        return;
      }
      const data = await fetchPreview(node, {max_images: 1});
      if (revision !== node._archPreviewRevision) return;
      renderPreview(container, data);
    } catch (err) {
      if (revision !== node._archPreviewRevision) return;
      container.textContent = String(err.message || err);
    }
    node.setDirtyCanvas(true, true);
  }, 200);
}

function installPreviewWidget(node) {
  if (!node.addDOMWidget || node._archReferencePreviewContainer) return;

  const container = document.createElement("div");
  container.style.width = "100%";
  container.style.minHeight = "112px";
  container.style.boxSizing = "border-box";
  container.style.padding = "6px 2px";
  container.style.overflow = "hidden";
  node._archReferencePreviewContainer = container;

  const previewWidget = node.addDOMWidget("reference_preview", "div", container, {
    serialize: false,
    getMinHeight: () => 112,
    getMaxHeight: () => 126,
    getValue: () => "",
    setValue: () => {},
  });
  if (previewWidget) {
    previewWidget.serialize = false;
    previewWidget.serializeValue = () => undefined;
  }

  const watchedWidgets = [
    "source_mode",
    "favorite",
    "folder",
    "selected_images",
    "selection_policy",
    "seed",
    "include_subfolders",
    "favorite_prompt",
  ];
  for (const name of watchedWidgets) {
    const widget = findWidget(node, name);
    if (!widget || widget._archReferencePreviewWrapped) continue;
    widget._archReferencePreviewWrapped = true;
    const callback = widget.callback;
    widget.callback = function () {
      const result = callback?.apply(this, arguments);
      // DOMWidgetImpl.value invokes callbacks even for programmatic writes.
      // These writes belong to one source transaction, not manual field edits.
      if (node._archApplyingSource) return result;
      if (name === "selection_policy") syncSequentialSeedControl(node);
      if (name === "favorite_prompt") {
        node._archSourceIntent = (node._archSourceIntent || 0) + 1;
        rememberPromptDraft(node);
        node.graph?.change?.();
        refreshReferencePrompt(node);
        return result;
      }
      if (name === "favorite") applyFavorite(node);
      if (name === "folder") selectFolder(node, widget.value);
      if (name === "selected_images") applySource(node, {source_mode: "selection", favorite: "None"});
      if (name === "source_mode") {
        if (widget.value === "folder") selectFolder(node, "");
        if (widget.value === "selection") selectImages(node, []);
      }
      if (name === "include_subfolders" && findWidget(node, "favorite")?.value !== "None") {
        applySource(node, {favorite: "None"});
      }
      refreshReferenceBrowser(node);
      schedulePreview(node);
      return result;
    };
  }

  setTimeout(() => schedulePreview(node), 100);
}

app.registerExtension({
  name: "arch.RandomReferenceSource",
  setup() {
    installReferenceBrowser(app, {
      nodes: () => [...referenceNodes].filter(node => node.graph),
      payload: referencePayload, preview: fetchPreview, selectFolder, selectImages,
      encodePaths: encodeImagePaths, selectLibrary,
      openLibrary(collection) {
        const library = globalThis.__archReferenceLibrary;
        if (!library?.openCollection) throw new Error("Reference Library is unavailable. Reload ComfyUI with the Reference Library extension enabled.");
        return library.openCollection(collection);
      },
      async library(path, body) {
        const response = await api.fetchApi(`/arch-reference-library${path}`, body === undefined ? {} : {
          method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
        });
        const text = await response.text();
        if (!response.ok) throw new Error(text || "Could not save character references.");
        const data = JSON.parse(text);
        return data;
      },
      promptState, setPromptName,
      revertPrompt(node) { applySource(node, {favorite_prompt: promptState(node).baseline}); },
      async combinedPreview() {
        const {output} = await app.graphToPrompt(app.rootGraph || app.graph);
        return buildCombinedPromptPreview(output);
      },
      setField(node, name, value) { setWidgetValue(node, findWidget(node, name), value); },
      async presets(node) { await refreshPresets(node); return node._archReferencePresets; },
      favorite: chooseFavorite,
      save: saveFavorite, delete: deleteFavorite, dialog: callDialog,
    });
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    const onConfigure = nodeType.prototype.onConfigure;
    const configure = nodeType.prototype.configure;
    nodeType.prototype.configure = function () {
      // LiteGraph restores DOM widget values before calling onConfigure.
      // Treat the complete restore as a transaction so saved folder sources
      // and favorites aren't detached by the selected_images setter.
      this._archApplyingSource = (this._archApplyingSource || 0) + 1;
      try { return configure?.apply(this, arguments); }
      finally { this._archApplyingSource--; }
    };
    const onRemoved = nodeType.prototype.onRemoved;
    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const result = onExecuted?.apply(this, arguments);
      const metadata = message?.arch_reference_last_used?.[0];
      if (metadata) updateLastUsed(this, metadata);
      return result;
    };
    nodeType.prototype.onRemoved = function () {
      clearTimeout(this._archReferencePreviewTimer);
      this._archPreviewRevision = (this._archPreviewRevision || 0) + 1;
      referenceNodes.delete(this);
      return onRemoved?.apply(this, arguments);
    };
    nodeType.prototype.onConfigure = function (info) {
      const result = onConfigure?.apply(this, arguments);
      migrateWorkflowWidgetValues(this, info?.widgets_values);
      ensurePositiveSeed(this);
      syncSequentialSeedControl(this);
      updateLastUsed(this, this.properties?.archReferenceLastUsed);
      schedulePreview(this);
      return result;
    };

    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated?.apply(this, arguments);
      const node = this;
      referenceNodes.add(node);

      // LiteGraph persists widgets positionally. Keep every transient control
      // appended after the Python widgets so skipped values cannot create
      // sparse holes that shift backend fields during workflow restoration.
      const addTransientButton = (label, callback) => {
        const button = node.addWidget("button", label, null, callback);
        button.serialize = false;
        button.serializeValue = () => undefined;
        return button;
      };

      addTransientButton("Load image…", () => pickSingleImage(node));
      addTransientButton("Browse folder…", async () => {
        try {
          const data = await callDialog("browse-folder", findWidget(node, "folder")?.value);
          if (data.path && referenceNodes.has(node)) selectFolder(node, data.path);
        } catch (error) {
          notify(String(error.message || error), "error");
        }
      });
      addTransientButton("Open Reference Browser…", () => openReferenceBrowser(node));

      addTransientButton("Use this image again", () => {
        if (node._archLastUsed?.selected_file) selectImages(node, [node._archLastUsed.selected_file]);
      });
      if (node.addDOMWidget) {
        const lastUsed = document.createElement("div");
        lastUsed.style.cssText = "font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:100%";
        node._archLastUsedContainer = lastUsed;
        const widget = node.addDOMWidget("reference_last_used", "div", lastUsed,
          {serialize: false, getMinHeight: () => 22, getMaxHeight: () => 22});
        widget.serialize = false;
        widget.serializeValue = () => undefined;
      }
      updateLastUsed(node, node.properties?.archReferenceLastUsed);

      installPreviewWidget(node);
      compactWidgets(node);
      // Keep the compact node usable in existing saved workflows.
      const size = node.computeSize();
      node.setSize([
        Math.max(260, size[0]),
        Math.max(320, size[1]),
      ]);
      setTimeout(() => {
        refreshPresets(node).catch((err) =>
          notify(String(err.message || err), "error"),
        );
      }, 0);

      return result;
    };
  },
});
