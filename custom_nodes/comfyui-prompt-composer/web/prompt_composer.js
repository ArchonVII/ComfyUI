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
}

async function buildPresetBar(node, nodeId) {
  const info = SCHEMA[nodeId];
  if (!info) return;
  const category = info.category;
  const slotKeys = info.slots.map((s) => s.key);

  let presets = await getPresets(category);
  const names = () => ["(select preset…)", ...Object.keys(presets)];

  const fillFrom = (name) => {
    const data = presets[name];
    if (!data) return;
    // Clear every slot first so a preset never leaves stale values behind.
    for (const key of slotKeys) setWidgetValue(node, key, "");
    for (const [key, val] of Object.entries(data)) setWidgetValue(node, key, val);
    node.setDirtyCanvas(true, true);
  };

  const presetWidget = makeTransient(node.addWidget(
    "combo",
    "📋 preset",
    "(select preset…)",
    (v) => {
      if (v && v !== "(select preset…)") fillFrom(v);
    },
    { values: names(), serialize: false }
  ));

  const refresh = async (selectName) => {
    presets = await getPresets(category);
    presetWidget.options.values = names();
    presetWidget.value = selectName || "(select preset…)";
    node.setDirtyCanvas(true, true);
  };

  const saveBtn = makeTransient(node.addWidget("button", "💾 save preset", null, async () => {
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
  }, { serialize: false }));

  const deleteBtn = makeTransient(node.addWidget("button", "🗑 delete preset", null, async () => {
    const name = presetWidget.value;
    if (!name || name === "(select preset…)") {
      notify("Pick a preset to delete first.", "warn");
      return;
    }
    if (!confirm(`Delete preset “${name}”?`)) return;
    try {
      await jpost(`${API}/presets/delete`, { category, name });
      await refresh();
      notify(`Deleted “${name}”.`);
    } catch (e) {
      notify(`Delete failed: ${e.message}`, "error");
    }
  }, { serialize: false }));

  const clearBtn = makeTransient(node.addWidget("button", "✖ clear slots", null, () => {
    for (const key of slotKeys) setWidgetValue(node, key, "");
    presetWidget.value = "(select preset…)";
    node.setDirtyCanvas(true, true);
  }, { serialize: false }));

  // (preset bar widgets are appended after the slots; see moveToTop note)
  void saveBtn; void deleteBtn; void clearBtn;
  node.setDirtyCanvas(true, true);
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

  // --- DOM widget (checklist + preview) ---------------------------------
  const root = document.createElement("div");
  Object.assign(root.style, {
    display: "flex", flexDirection: "column", gap: "4px",
    font: "12px sans-serif", color: "var(--input-text, #ddd)",
    padding: "4px", boxSizing: "border-box",
  });

  const list = document.createElement("div");
  Object.assign(list.style, {
    display: "flex", flexDirection: "column", gap: "2px",
    maxHeight: "220px", overflowY: "auto",
    background: "var(--comfy-input-bg, #222)", borderRadius: "4px", padding: "4px",
  });

  const preview = document.createElement("div");
  Object.assign(preview.style, {
    opacity: "0.75", fontStyle: "italic", whiteSpace: "normal",
    wordBreak: "break-word", borderTop: "1px solid #444", paddingTop: "4px",
  });

  root.appendChild(list);
  root.appendChild(preview);

  let domWidget = null;
  if (typeof node.addDOMWidget === "function") {
    domWidget = node.addDOMWidget("pc_snippet_editor", "div", root, { serialize: false });
  } else {
    notify("This ComfyUI build lacks DOM widgets — type the library/selected fields directly.", "warn");
  }

  // --- rendering --------------------------------------------------------
  const renderList = (preserveSelected) => {
    const snippets = currentSnippets();
    const titles = Object.keys(snippets);
    let selected = readSelected();
    if (!preserveSelected) selected = selected.filter((t) => titles.includes(t));

    list.innerHTML = "";
    if (!titles.length) {
      const empty = document.createElement("div");
      empty.textContent = "No snippets yet — use ➕ Add snippet.";
      empty.style.opacity = "0.6";
      list.appendChild(empty);
    }

    for (const title of titles) {
      const row = document.createElement("div");
      Object.assign(row.style, { display: "flex", alignItems: "center", gap: "6px" });

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selected.includes(title);
      cb.onchange = () => {
        // Keep selection in library order so chained output is deterministic.
        const chosen = Object.keys(currentSnippets()).filter((t) =>
          t === title ? cb.checked : readSelected().includes(t)
        );
        writeSelected(chosen);
        renderPreview();
      };

      const label = document.createElement("span");
      label.textContent = title;
      label.title = snippets[title];
      Object.assign(label.style, { flex: "1", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
      label.onclick = () => { cb.checked = !cb.checked; cb.onchange(); };

      const edit = mkBtn("✎", "Edit snippet", async () => {
        const newText = prompt(`Edit text for “${title}”:`, snippets[title]);
        if (newText == null) return;
        const lib = { ...currentSnippets(), [title]: newText };
        await persistLibrary(lib);
      });

      const del = mkBtn("✕", "Delete snippet", async () => {
        if (!confirm(`Delete snippet “${title}”?`)) return;
        const lib = { ...currentSnippets() };
        delete lib[title];
        await persistLibrary(lib);
      });

      row.append(cb, label, edit, del);
      list.appendChild(row);
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

  const sizeWidget = () => {
    if (domWidget) domWidget.computeSize = () => [node.size[0], Math.min(320, 60 + list.scrollHeight)];
    node.setDirtyCanvas(true, true);
  };

  // --- persistence ------------------------------------------------------
  const persistLibrary = async (snippets) => {
    const name = currentLib();
    if (!name) { notify("Create a library first.", "warn"); return; }
    try {
      const res = await jpost(`${API}/libraries/save`, { name, snippets });
      LIBRARIES = res.libraries || LIBRARIES;
      renderList(true);
    } catch (e) {
      notify(`Save failed: ${e.message}`, "error");
    }
  };

  // --- library picker + action buttons (litegraph widgets) --------------
  const libCombo = makeTransient(node.addWidget("combo", "📚 library", currentLib() || "(none)",
    (v) => {
      setWidgetValue(node, "library", v);
      writeSelected([]);
      renderList(false);
    },
    { values: libNames().length ? libNames() : ["(none)"], serialize: false }));

  const refreshCombo = (select) => {
    libCombo.options.values = libNames().length ? libNames() : ["(none)"];
    if (select) { libCombo.value = select; setWidgetValue(node, "library", select); }
  };

  const addSnippetBtn = makeTransient(node.addWidget("button", "➕ add snippet", null, async () => {
    if (!currentLib()) { notify("Create a library first.", "warn"); return; }
    const title = prompt("Snippet title:");
    if (!title) return;
    const text = prompt(`Text for “${title}”:`);
    if (text == null) return;
    await persistLibrary({ ...currentSnippets(), [title.trim()]: text });
  }, { serialize: false }));

  const newLibBtn = makeTransient(node.addWidget("button", "🗂 new library", null, async () => {
    const name = prompt("New library name:");
    if (!name) return;
    try {
      const res = await jpost(`${API}/libraries/save`, { name: name.trim(), snippets: {} });
      LIBRARIES = res.libraries || LIBRARIES;
      refreshCombo(name.trim());
      setWidgetValue(node, "library", name.trim());
      writeSelected([]);
      renderList(false);
      notify(`Created library “${name.trim()}”.`);
    } catch (e) {
      notify(`Create failed: ${e.message}`, "error");
    }
  }, { serialize: false }));

  const delLibBtn = makeTransient(node.addWidget("button", "🗑 delete library", null, async () => {
    const name = currentLib();
    if (!name) return;
    if (!confirm(`Delete the entire library “${name}”?`)) return;
    try {
      const res = await jpost(`${API}/libraries/delete`, { name });
      LIBRARIES = res.libraries || {};
      const next = libNames()[0] || "";
      refreshCombo(next);
      setWidgetValue(node, "library", next);
      writeSelected([]);
      renderList(false);
      notify(`Deleted “${name}”.`);
    } catch (e) {
      notify(`Delete failed: ${e.message}`, "error");
    }
  }, { serialize: false }));

  const reloadBtn = makeTransient(node.addWidget("button", "↻ reload", null, async () => {
    await loadLibraries();
    refreshCombo(currentLib());
    renderList(true);
  }, { serialize: false }));

  // expose a re-render hook for onConfigure (workflow load restores `library`)
  node._pcRender = (preserve) => {
    refreshCombo(currentLib());
    renderList(preserve);
  };

  void addSnippetBtn; void newLibBtn; void delLibBtn; void reloadBtn;
  renderList(true);
}

function mkBtn(text, title, onClick) {
  const b = document.createElement("button");
  b.textContent = text;
  b.title = title;
  Object.assign(b.style, {
    cursor: "pointer", border: "none", borderRadius: "3px",
    background: "var(--comfy-menu-bg, #333)", color: "inherit",
    padding: "1px 6px", lineHeight: "1.4",
  });
  b.onclick = (e) => { e.stopPropagation(); onClick(); };
  return b;
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
