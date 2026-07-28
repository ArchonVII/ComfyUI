import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/*
 * Prompt Composer frontend.
 *
 * Adds convenience UI on top of the Python nodes:
 *   - slot nodes (Clothing/Body/Environment) get a preset dropdown + Save/Delete
 *   - the Snippets node gets a library picker + a title/text snippet editor
 *
 * Everything degrades gracefully: if any of this throws, the underlying nodes
 * still run from their raw widget values.  All network calls go to the
 * /prompt_composer routes registered by store.py.
 */

const API = "/prompt_composer";
const SLOT_NODES = ["PromptComposerClothing", "PromptComposerBody", "PromptComposerEnvironment"];

let SCHEMA = {};        // node_id -> {category, slots:[{key,label}], garment_keys}
let LIBRARIES = {};     // name -> {title: text}

// ---------- tiny helpers ----------
function notify(text, severity = "info") {
  try {
    app.extensionManager?.toast?.add({ severity, summary: "Prompt Composer", detail: text, life: 3000 });
  } catch (_e) {
    console.log("[PromptComposer]", text);
  }
}

async function jget(url) {
  const r = await api.fetchApi(url);
  if (!r.ok) throw new Error(`GET ${url} -> ${r.status}`);
  return r.json();
}

async function jpost(url, body) {
  const r = await api.fetchApi(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `POST ${url} -> ${r.status}`);
  return data;
}

function getWidget(node, name) {
  return (node.widgets || []).find((w) => w.name === name);
}

function setWidgetValue(node, name, value) {
  const w = getWidget(node, name);
  if (!w) return;
  w.value = value;
  w.callback?.(value);
}

function makeTransient(widget) {
  if (!widget) return widget;
  widget.serialize = false;
  widget.serializeValue = () => undefined;
  return widget;
}

// Hide a Python widget from view but keep it functional/serialized.
function hideWidget(node, name) {
  const w = getWidget(node, name);
  if (!w || w._pcHidden) return;
  w._pcHidden = true;
  w._pcType = w.type;
  w.type = "pc_hidden";
  w.computeSize = () => [0, -4];
}

// NOTE: we deliberately do NOT reorder node.widgets. The serialized Python
// widgets must keep their original indices so a saved workflow restores its
// widget values correctly across ComfyUI frontend versions. JS-added controls
// (all serialize:false) therefore stay appended after the Python widgets.

function element(tag, role, styles = {}) {
  const el = document.createElement(tag);
  if (role) el.dataset.pcRole = role;
  Object.assign(el.style, styles);
  return el;
}

function compactRow(role) {
  return element("div", role, {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "3px",
  });
}

function button(text, title, role, onClick) {
  const el = element("button", role, {
    cursor: "pointer",
    border: "1px solid var(--border-color, #555)",
    borderRadius: "999px",
    background: "var(--comfy-input-bg, #222)",
    color: "var(--input-text, #ddd)",
    padding: "2px 7px",
    lineHeight: "1.3",
    font: "11px sans-serif",
    maxWidth: "100%",
  });
  el.type = "button";
  el.textContent = text;
  el.title = title || text;
  el.addEventListener("click", (event) => {
    event.stopPropagation?.();
    onClick?.(event);
  });
  return el;
}

function paintBadge(el, { active = false, selected = false, filled = false } = {}) {
  el.style.borderColor = active
    ? "var(--p-primary-color, #6aa9ff)"
    : "var(--border-color, #555)";
  el.style.background = selected
    ? "var(--p-primary-700, #245b92)"
    : filled
      ? "var(--p-surface-700, #3a3a3a)"
      : "var(--comfy-input-bg, #222)";
  el.style.opacity = selected || filled || active ? "1" : "0.82";
}

function shortLabel(label) {
  return String(label || "").split(" (", 1)[0];
}

function shortValue(value, max = 24) {
  const text = String(value || "").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function forwardWheelToCanvas(root) {
  root.addEventListener("wheel", (event) => {
    const canvas = app.canvas?.canvas;
    if (!canvas?.dispatchEvent || typeof WheelEvent !== "function") return;
    event.preventDefault?.();
    event.stopPropagation?.();
    canvas.dispatchEvent(new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      deltaX: event.deltaX || 0,
      deltaY: event.deltaY || 0,
      deltaZ: event.deltaZ || 0,
      deltaMode: event.deltaMode || 0,
      clientX: event.clientX || 0,
      clientY: event.clientY || 0,
      ctrlKey: Boolean(event.ctrlKey),
      shiftKey: Boolean(event.shiftKey),
      altKey: Boolean(event.altKey),
      metaKey: Boolean(event.metaKey),
    }));
  }, { passive: false });
}

function compactRoot(role) {
  const root = element("div", role, {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    width: "100%",
    padding: "3px",
    boxSizing: "border-box",
    color: "var(--input-text, #ddd)",
    font: "11px sans-serif",
  });
  forwardWheelToCanvas(root);
  return root;
}

function attachCompactWidget(node, name, root) {
  if (typeof node.addDOMWidget !== "function") {
    notify("This ComfyUI build lacks DOM widgets.", "warn");
    return null;
  }
  const widget = node.addDOMWidget(name, "div", root, { serialize: false });
  makeTransient(widget);
  widget.computeSize = () => [
    Math.max(300, node.size?.[0] || 300),
    Math.max(38, root.scrollHeight + 6),
  ];
  return widget;
}

// ---------- data ----------
async function loadSchema() {
  try {
    SCHEMA = await jget(`${API}/schema`);
  } catch (e) {
    console.error("[PromptComposer] schema load failed", e);
    SCHEMA = {};
  }
}

async function loadLibraries() {
  try {
    LIBRARIES = await jget(`${API}/libraries`);
  } catch (e) {
    console.error("[PromptComposer] libraries load failed", e);
    LIBRARIES = {};
  }
  return LIBRARIES;
}

async function getPresets(category) {
  try {
    return await jget(`${API}/presets?category=${encodeURIComponent(category)}`);
  } catch (e) {
    console.error("[PromptComposer] presets load failed", e);
    return {};
  }
}

// ==========================================================================
//  Slot nodes: preset bar
// ==========================================================================
function setupSlotNode(nodeType, nodeId) {
  const onCreated = nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated = function () {
    onCreated?.apply(this, arguments);
    try {
      buildPresetBar(this, nodeId);
    } catch (e) {
      console.error("[PromptComposer] preset bar failed", e);
    }
  };

  const onConfigure = nodeType.prototype.onConfigure;
  nodeType.prototype.onConfigure = function () {
    onConfigure?.apply(this, arguments);
    const node = this;
    setTimeout(() => {
      try {
        node._pcRenderSlots?.();
      } catch (e) {
        console.error("[PromptComposer] slot restore failed", e);
      }
    }, 0);
  };
}

async function buildPresetBar(node, nodeId) {
  const info = SCHEMA[nodeId];
  if (!info) return;
  const category = info.category;
  const slotKeys = info.slots.map((s) => s.key);

  for (const key of [...slotKeys, "separator"]) hideWidget(node, key);
  if (category === "clothing") {
    hideWidget(node, "nude");
    hideWidget(node, "nude_text");
  }

  let presets = await getPresets(category);
  let activeKey = slotKeys[0] || "";
  let activePreset = "";

  const root = compactRoot("slot-root");
  const presetGrid = compactRow("preset-grid");
  const fieldGrid = compactRow("field-grid");
  const editorRow = element("div", "field-editor-row", {
    display: "flex",
    alignItems: "center",
    gap: "4px",
  });
  const editorLabel = element("span", "field-editor-label", {
    flex: "0 0 auto",
    opacity: "0.72",
  });
  const editor = element("input", "field-editor", {
    flex: "1 1 auto",
    minWidth: "80px",
    border: "1px solid var(--border-color, #555)",
    borderRadius: "4px",
    background: "var(--comfy-input-bg, #222)",
    color: "var(--input-text, #ddd)",
    padding: "3px 5px",
    font: "11px sans-serif",
  });
  editor.type = "text";
  editorRow.append(editorLabel, editor);

  const actions = compactRow("slot-actions");
  root.append(presetGrid, fieldGrid, editorRow, actions);
  const domWidget = attachCompactWidget(node, "pc_compact_slots", root);

  const fieldButtons = new Map();

  const sizeWidget = () => {
    if (domWidget) {
      domWidget.computeSize = () => [
        Math.max(300, node.size?.[0] || 300),
        Math.max(38, root.scrollHeight + 6),
      ];
    }
    node.setDirtyCanvas(true, true);
  };

  const renderFields = () => {
    for (const { key, label } of info.slots) {
      const value = getWidget(node, key)?.value || "";
      const badge = fieldButtons.get(key);
      if (!badge) continue;
      const compact = shortValue(value);
      badge.textContent = compact ? `${shortLabel(label)}: ${compact}` : shortLabel(label);
      badge.title = value ? `${label}\n${value}` : label;
      paintBadge(badge, { active: key === activeKey, filled: Boolean(String(value).trim()) });
    }
    const nudeButton = fieldButtons.get("__nude");
    if (nudeButton) {
      const nude = Boolean(getWidget(node, "nude")?.value);
      nudeButton.textContent = nude ? "Nude ✓" : "Nude";
      paintBadge(nudeButton, { selected: nude });
    }
  };

  const selectField = (key) => {
    activeKey = key;
    const slot = info.slots.find((item) => item.key === key);
    const value = getWidget(node, key)?.value || "";
    editor.dataset.slotKey = key;
    editor.value = value;
    editor.placeholder = slot?.label || key;
    editor.title = slot?.label || key;
    editorLabel.textContent = `${shortLabel(slot?.label || key)}:`;
    renderFields();
    editor.focus?.();
  };

  for (const { key, label } of info.slots) {
    const badge = button(shortLabel(label), label, "field-badge", () => selectField(key));
    badge.dataset.slotKey = key;
    fieldButtons.set(key, badge);
    fieldGrid.appendChild(badge);
  }

  if (category === "clothing") {
    const nudeButton = button("Nude", "Toggle nude mode", "state-badge", () => {
      const widget = getWidget(node, "nude");
      setWidgetValue(node, "nude", !Boolean(widget?.value));
      renderFields();
    });
    fieldButtons.set("__nude", nudeButton);
    fieldGrid.appendChild(nudeButton);
  }

  editor.addEventListener("input", () => {
    if (!activeKey) return;
    setWidgetValue(node, activeKey, editor.value);
    activePreset = "";
    renderFields();
    renderPresets();
    sizeWidget();
  });

  const fillFrom = (name) => {
    const data = presets[name];
    if (!data) return;
    // Clear every slot first so a preset never leaves stale values behind.
    for (const key of slotKeys) setWidgetValue(node, key, "");
    for (const [key, val] of Object.entries(data)) setWidgetValue(node, key, val);
    activePreset = name;
    selectField(activeKey);
    renderPresets();
    sizeWidget();
  };

  const renderPresets = () => {
    presetGrid.innerHTML = "";
    for (const name of Object.keys(presets)) {
      const preset = button(name, `Apply ${name}`, "preset-badge", () => fillFrom(name));
      preset.dataset.presetName = name;
      paintBadge(preset, { selected: name === activePreset });
      presetGrid.appendChild(preset);
    }
  };

  const refresh = async (selectName = "") => {
    presets = await getPresets(category);
    activePreset = selectName;
    renderPresets();
    sizeWidget();
  };

  actions.appendChild(button("+ preset", "Save current fields as a preset", "preset-save", async () => {
    const name = prompt("Save current slots as preset named:");
    if (!name) return;
    const data = {};
    for (const key of slotKeys) {
      const w = getWidget(node, key);
      const val = (w?.value || "").trim();
      if (val) data[key] = val;
    }
    if (!Object.keys(data).length) {
      notify("All slots are empty — nothing to save.", "warn");
      return;
    }
    try {
      await jpost(`${API}/presets/save`, { category, name: name.trim(), data });
      await refresh(name.trim());
      notify(`Saved preset “${name.trim()}”.`);
    } catch (e) {
      notify(`Save failed: ${e.message}`, "error");
    }
  }));

  actions.appendChild(button("delete preset", "Delete the last applied preset", "preset-delete", async () => {
    if (!activePreset) {
      notify("Click a preset to select it first.", "warn");
      return;
    }
    const name = activePreset;
    if (!confirm(`Delete preset “${name}”?`)) return;
    try {
      await jpost(`${API}/presets/delete`, { category, name });
      await refresh();
      notify(`Deleted “${name}”.`);
    } catch (e) {
      notify(`Delete failed: ${e.message}`, "error");
    }
  }));

  actions.appendChild(button("clear", "Clear every field", "slot-clear", () => {
    for (const key of slotKeys) setWidgetValue(node, key, "");
    activePreset = "";
    selectField(activeKey);
    renderPresets();
    sizeWidget();
  }));

  node._pcRenderSlots = () => {
    selectField(activeKey);
    renderPresets();
    sizeWidget();
  };

  renderPresets();
  selectField(activeKey);
  sizeWidget();
}

// ==========================================================================
//  Snippets node: library picker + editor
// ==========================================================================
function setupSnippetNode(nodeType) {
  const onCreated = nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated = function () {
    onCreated?.apply(this, arguments);
    try {
      buildSnippetUI(this);
    } catch (e) {
      console.error("[PromptComposer] snippet UI failed", e);
    }
  };

  // Rebuild the checklist after a saved workflow restores widget values.
  const onConfigure = nodeType.prototype.onConfigure;
  nodeType.prototype.onConfigure = function () {
    onConfigure?.apply(this, arguments);
    const node = this;
    setTimeout(() => {
      try {
        if (node._pcRender) node._pcRender(true);
      } catch (e) {
        console.error("[PromptComposer] snippet restore failed", e);
      }
    }, 0);
  };
}

async function buildSnippetUI(node) {
  hideWidget(node, "library");
  hideWidget(node, "selected");
  hideWidget(node, "separator");

  await loadLibraries();

  const libNames = () => Object.keys(LIBRARIES);
  const currentLib = () => getWidget(node, "library")?.value || libNames()[0] || "";
  const currentSnippets = () => LIBRARIES[currentLib()] || {};

  const readSelected = () => {
    try {
      const v = JSON.parse(getWidget(node, "selected")?.value || "[]");
      return Array.isArray(v) ? v : [];
    } catch (_e) {
      return [];
    }
  };
  const writeSelected = (titles) => {
    setWidgetValue(node, "selected", JSON.stringify(titles));
    node.setDirtyCanvas(true, true);
  };

  const root = compactRoot("snippet-root");
  const libraryGrid = compactRow("library-grid");
  const snippetGrid = compactRow("snippet-grid");
  const libraryActions = compactRow("library-actions");
  const snippetActions = compactRow("snippet-actions");
  const preview = element("div", "snippet-preview", {
    opacity: "0.78",
    whiteSpace: "normal",
    wordBreak: "break-word",
    borderTop: "1px solid var(--border-color, #444)",
    paddingTop: "3px",
  });
  root.append(libraryGrid, libraryActions, snippetGrid, snippetActions, preview);
  const domWidget = attachCompactWidget(node, "pc_snippet_editor", root);
  let activeSnippet = "";

  const sizeWidget = () => {
    if (domWidget) {
      domWidget.computeSize = () => [
        Math.max(300, node.size?.[0] || 300),
        Math.max(38, root.scrollHeight + 6),
      ];
    }
    node.setDirtyCanvas(true, true);
  };

  const renderLibraries = () => {
    libraryGrid.innerHTML = "";
    for (const name of libNames()) {
      const badge = button(name, `Show ${name}`, "library-badge", () => {
        setWidgetValue(node, "library", name);
        writeSelected([]);
        activeSnippet = "";
        renderLibraries();
        renderSnippets(false);
      });
      badge.dataset.libraryName = name;
      paintBadge(badge, { selected: name === currentLib() });
      libraryGrid.appendChild(badge);
    }
  };

  const renderSnippets = (preserveSelected) => {
    const snippets = currentSnippets();
    const titles = Object.keys(snippets);
    let selected = readSelected();
    if (!preserveSelected) selected = selected.filter((t) => titles.includes(t));
    if (activeSnippet && !titles.includes(activeSnippet)) activeSnippet = "";
    snippetGrid.innerHTML = "";
    if (!titles.length) {
      const empty = element("div", "snippet-empty");
      empty.textContent = "No snippets yet — use ➕ Add snippet.";
      empty.style.opacity = "0.6";
      snippetGrid.appendChild(empty);
    }

    for (const title of titles) {
      const badge = button(title, snippets[title], "snippet-badge", () => {
        activeSnippet = title;
        const wasSelected = readSelected().includes(title);
        const chosen = Object.keys(currentSnippets()).filter((candidate) =>
          candidate === title ? !wasSelected : readSelected().includes(candidate)
        );
        writeSelected(chosen);
        renderSnippets(true);
        renderPreview();
      });
      badge.dataset.snippetTitle = title;
      paintBadge(badge, {
        active: title === activeSnippet,
        selected: selected.includes(title),
      });
      snippetGrid.appendChild(badge);
    }
    renderPreview();
    sizeWidget();
  };

  const renderPreview = () => {
    const snippets = currentSnippets();
    const sep = getWidget(node, "separator")?.value || ", ";
    const text = readSelected().filter((t) => t in snippets).map((t) => snippets[t]).join(sep);
    preview.textContent = text ? `→ ${text}` : "→ (nothing selected)";
  };

  const persistLibrary = async (snippets) => {
    const name = currentLib();
    if (!name) { notify("Create a library first.", "warn"); return; }
    try {
      const res = await jpost(`${API}/libraries/save`, { name, snippets });
      LIBRARIES = res.libraries || LIBRARIES;
      renderLibraries();
      renderSnippets(true);
    } catch (e) {
      notify(`Save failed: ${e.message}`, "error");
    }
  };

  snippetActions.appendChild(button("+ snippet", "Add a snippet", "snippet-add", async () => {
    if (!currentLib()) { notify("Create a library first.", "warn"); return; }
    const title = prompt("Snippet title:");
    if (!title) return;
    const text = prompt(`Text for “${title}”:`);
    if (text == null) return;
    activeSnippet = title.trim();
    await persistLibrary({ ...currentSnippets(), [title.trim()]: text });
  }));

  snippetActions.appendChild(button("edit", "Edit the last clicked snippet", "snippet-edit", async () => {
    if (!activeSnippet || !(activeSnippet in currentSnippets())) {
      notify("Click a snippet to edit it first.", "warn");
      return;
    }
    const newText = prompt(`Edit text for “${activeSnippet}”:`, currentSnippets()[activeSnippet]);
    if (newText == null) return;
    await persistLibrary({ ...currentSnippets(), [activeSnippet]: newText });
  }));

  snippetActions.appendChild(button("delete", "Delete the last clicked snippet", "snippet-delete", async () => {
    if (!activeSnippet || !(activeSnippet in currentSnippets())) {
      notify("Click a snippet to delete it first.", "warn");
      return;
    }
    if (!confirm(`Delete snippet “${activeSnippet}”?`)) return;
    const lib = { ...currentSnippets() };
    delete lib[activeSnippet];
    activeSnippet = "";
    await persistLibrary(lib);
  }));

  libraryActions.appendChild(button("+ library", "Create a library", "library-add", async () => {
    const name = prompt("New library name:");
    if (!name) return;
    try {
      const res = await jpost(`${API}/libraries/save`, { name: name.trim(), snippets: {} });
      LIBRARIES = res.libraries || LIBRARIES;
      setWidgetValue(node, "library", name.trim());
      writeSelected([]);
      activeSnippet = "";
      renderLibraries();
      renderSnippets(false);
      notify(`Created library “${name.trim()}”.`);
    } catch (e) {
      notify(`Create failed: ${e.message}`, "error");
    }
  }));

  libraryActions.appendChild(button("delete library", "Delete the selected library", "library-delete", async () => {
    const name = currentLib();
    if (!name) return;
    if (!confirm(`Delete the entire library “${name}”?`)) return;
    try {
      const res = await jpost(`${API}/libraries/delete`, { name });
      LIBRARIES = res.libraries || {};
      const next = libNames()[0] || "";
      setWidgetValue(node, "library", next);
      writeSelected([]);
      activeSnippet = "";
      renderLibraries();
      renderSnippets(false);
      notify(`Deleted “${name}”.`);
    } catch (e) {
      notify(`Delete failed: ${e.message}`, "error");
    }
  }));

  libraryActions.appendChild(button("reload", "Reload libraries", "library-reload", async () => {
    await loadLibraries();
    renderLibraries();
    renderSnippets(true);
  }));

  // expose a re-render hook for onConfigure (workflow load restores `library`)
  node._pcRender = (preserve) => {
    renderLibraries();
    renderSnippets(preserve);
  };

  renderLibraries();
  renderSnippets(true);
}

// ==========================================================================
app.registerExtension({
  name: "PromptComposer",
  async setup() {
    await Promise.all([loadSchema(), loadLibraries()]);
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const id = nodeData?.name;
    if (SLOT_NODES.includes(id)) {
      // Schema may not be fetched yet at registration time; fetch lazily so
      // it's certainly present by onNodeCreated (which fires after setup()).
      if (!SCHEMA[id]) await loadSchema();
      setupSlotNode(nodeType, id);
    } else if (id === "PromptComposerSnippets") {
      setupSnippetNode(nodeType);
    }
  },
});
