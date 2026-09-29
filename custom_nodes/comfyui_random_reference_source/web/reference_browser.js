// The browser edits the selected node's existing widgets; it owns no separate
// source state and never copies or uploads reference images.
let actions;
let activeNode;
let browser;
const views = new Set();

function element(tag, className = "", text = "") {
  const item = document.createElement(tag);
  item.className = className;
  item.textContent = text;
  return item;
}

function button(text, action, className = "") {
  const item = element("button", className, text);
  item.type = "button";
  item.addEventListener("click", action);
  return item;
}

function field(label, control) {
  const wrapper = element("label", "rr-field");
  wrapper.append(element("span", "", label), control);
  return wrapper;
}

function textInput(value = "", placeholder = "") {
  const input = element("input");
  input.value = value;
  input.placeholder = placeholder;
  return input;
}

function nodeLabel(node) {
  return `${node.title || "Reference source"} · #${node.id}`;
}

function validNode(node) {
  return node && actions.nodes().includes(node);
}

function imagePaths(text) {
  return String(text || "").split(/\r?\n/).flatMap(line => {
    if (!line.trim() || line.trimStart().startsWith("#")) return [];
    const values = []; let value = "", quoted = false;
    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      if (char === '"') {
        if (quoted && line[i + 1] === '"') { value += '"'; i++; }
        else quoted = !quoted;
      } else if (char === "," && !quoted) { values.push(value.trim()); value = ""; }
      else value += char;
    }
    values.push(value.trim()); return values.filter(Boolean);
  });
}

function targetSelect(node, change) {
  const select = element("select");
  select.setAttribute("aria-label", "Target reference node");
  for (const candidate of actions.nodes()) {
    const option = element("option", "", nodeLabel(candidate));
    option.value = String(candidate.id);
    option.selected = candidate === node;
    select.append(option);
  }
  select.addEventListener("change", () => change(actions.nodes().find(n => String(n.id) === select.value)));
  return select;
}

function report(view, error) {
  view.status.textContent = String(error.message || error);
  view.status.classList.add("rr-error");
}

async function run(view, operation) {
  try { await operation(); }
  catch (error) { if (!view.disposed) report(view, error); }
}

async function favorites(view) {
  const node = view.node;
  const revision = ++view.favoriteRevision;
  const data = await actions.presets(node);
  if (view.disposed || revision !== view.favoriteRevision || view.node !== node) return;
  view.refreshPrompt?.();
  const draw = () => {
    view.favoriteObserver?.disconnect();
    if (typeof IntersectionObserver !== "undefined") {
      view.favoriteObserver = new IntersectionObserver(entries => {
        for (const item of entries) {
          if (!item.isIntersecting) continue;
          view.favoriteObserver.unobserve(item.target);
          actions.preview(node, {favorite: item.target.dataset.favorite, browse: true, max_images: 1})
            .then(preview => {
              if (view.disposed || revision !== view.favoriteRevision || !item.target.isConnected) return;
              const first = preview.images?.[0];
              if (!first) return;
              const image = element("img"); image.src = first.thumbnail_data_url; image.alt = "";
              item.target.classList.add("rr-has-thumb"); item.target.append(image);
            }).catch(() => {}); // A stale favorite remains selectable so its error can be inspected.
        }
      }, {root: view.favoriteList});
    }
    view.favoriteList.replaceChildren();
    const query = view.favoriteSearch.value.trim().toLocaleLowerCase();
    for (const [name, preset] of Object.entries(data).sort(([a], [b]) => a.localeCompare(b))) {
      if (!name.toLocaleLowerCase().includes(query)) continue;
      const entry = button("", () => run(view, () => actions.favorite(node, name)), "rr-favorite");
      entry.classList.toggle("rr-active", actions.payload(node).favorite === name);
      entry.dataset.favorite = name;
      entry.append(element("strong", "", name), element("small", "",
        preset.kind === "selection" ? `${preset.images.length} selected images` : preset.folder));
      view.favoriteList.append(entry);
      view.favoriteObserver?.observe(entry);
    }
    if (!view.favoriteList.childElementCount) view.favoriteList.append(element("p", "rr-muted", "No matching favorites"));
  };
  view.favoriteSearch.oninput = draw;
  draw();
}

function favoriteColumn(view) {
  const aside = element("aside", "rr-favorites");
  view.favoriteSearch = textInput("", "Search favorites…");
  view.favoriteSearch.setAttribute("aria-label", "Search favorites");
  view.favoriteList = element("div", "rr-favorite-list");
  aside.append(element("h3", "", "Favorites"), view.favoriteSearch, view.favoriteList);
  return aside;
}

function installStyle() {
  if (document.getElementById("arch-reference-browser-style")) return;
  const style = element("style");
  style.id = "arch-reference-browser-style";
  style.textContent = `
    .rr-dialog{width:min(1600px,96vw);height:min(980px,92vh);max-width:98vw;max-height:94vh;
      padding:0;border:1px solid #505968;border-radius:12px;background:#181d25;color:#edf1f7;z-index:10000}
    .rr-dialog::backdrop{background:#000a}.rr-browser,.rr-sidebar{font:14px/1.4 system-ui;color:#edf1f7;box-sizing:border-box}
    .rr-browser{height:100%;display:flex;flex-direction:column}.rr-browser *,.rr-sidebar *{box-sizing:border-box}
    .rr-browser [hidden],.rr-sidebar [hidden]{display:none!important}
    .rr-head{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #39414e;flex-shrink:0}
    .rr-head h2{font-size:18px;margin:0}.rr-head select{flex:1;min-width:150px}
    .rr-browser button,.rr-sidebar button,.rr-browser input,.rr-sidebar input,.rr-browser select,.rr-sidebar select,.rr-browser textarea{
      font:inherit;color:inherit;background:#262e3a;border:1px solid #505b6d;border-radius:6px;padding:7px 10px}
    .rr-browser button,.rr-sidebar button{cursor:pointer}.rr-browser button:hover,.rr-sidebar button:hover{background:#35445b}
    .rr-browser button:disabled{opacity:.45;cursor:default}.rr-primary,.rr-active{border-color:#7ab8ff!important;background:#29476b!important}
    .rr-body{display:grid;grid-template-columns:210px minmax(260px,1fr) minmax(320px,390px);flex:1;min-height:0}
    .rr-favorites{display:flex;flex-direction:column;gap:10px;padding:14px;min-height:0;border-right:1px solid #39414e}
    .rr-favorites h3{margin:0;font-size:15px}.rr-favorites input{width:100%}
    .rr-favorite-list{overflow-y:auto;flex:1;min-height:0;overscroll-behavior:contain}
    .rr-favorite{width:100%;text-align:left;margin-bottom:8px;display:flex;flex-direction:column;gap:5px}
    .rr-favorite small{opacity:.7;overflow-wrap:anywhere}.rr-main{display:flex;flex-direction:column;min-height:0;min-width:0}
    .rr-has-thumb{display:grid;grid-template-columns:48px minmax(0,1fr)}
    .rr-has-thumb strong,.rr-has-thumb small{grid-column:2}.rr-has-thumb img{grid-column:1;grid-row:1/3;width:48px;height:48px;object-fit:cover;border-radius:4px}
    .rr-controls{padding:14px 18px;display:flex;flex-direction:column;gap:10px;flex-shrink:0;max-height:44%;overflow-y:auto}
    .rr-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.rr-row>input{flex:1;min-width:140px}
    .rr-field{display:flex;align-items:center;gap:8px}.rr-field span{opacity:.8}.rr-field textarea{width:100%;min-height:70px}
    .rr-paths{width:100%;height:72px;resize:vertical}.rr-controls details{border-top:1px solid #39414e;padding-top:8px}
    .rr-controls summary{cursor:pointer}.rr-controls details>.rr-row{margin-top:10px}
    .rr-status{padding:8px 18px;white-space:pre-wrap;overflow-wrap:anywhere;flex-shrink:0;color:#bfcce0;background:#202835}
    .rr-error{color:#ffb1a5}.rr-scroll{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:16px 18px}
    .rr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:14px}
    .rr-card{min-width:0;padding:7px!important;display:flex;flex-direction:column;gap:7px;text-align:left}
    .rr-card img{width:100%;height:155px;object-fit:contain;background:#10141b;border-radius:4px}
    .rr-card small{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
    .rr-card label{display:flex;gap:7px;align-items:center}.rr-card input{flex:none}
    .rr-more{display:block;margin:18px auto}.rr-footer{padding:10px 18px;border-top:1px solid #39414e;flex-shrink:0}
    .rr-muted{opacity:.7}.rr-sidebar{height:100%;min-height:0;display:flex;flex-direction:column;padding:10px;gap:10px}
    .rr-sidebar .rr-favorites{flex:1;min-height:0;padding:0;border:0}.rr-sidebar .rr-status{padding:8px}
    .rr-zoom{width:min(1500px,94vw);height:92vh}.rr-zoom img{width:100%;height:calc(100% - 70px);object-fit:contain}
    .rr-prompt-panel{min-width:0;min-height:0;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;border-left:1px solid #39414e;overscroll-behavior:contain}
    .rr-prompt-panel h3,.rr-prompt-panel p{margin:0}.rr-prompt-panel label{display:flex;flex-direction:column;gap:6px}
    .rr-prompt-editor{width:100%;min-height:210px;resize:vertical;line-height:1.5!important}
    .rr-prompt-status{font-weight:600;color:#a8d7ff}.rr-prompt-status.rr-error{color:#ffb1a5}
    .rr-prompt-panel .rr-row button{flex:1}.rr-prompt-panel input{width:100%;min-width:0}
    .rr-prompt-help{font-size:12px;color:#bfcce0}.rr-combined{border-top:1px solid #39414e;padding-top:12px;display:flex;flex-direction:column;gap:10px}
    .rr-combined textarea{width:100%;min-height:170px;resize:vertical;line-height:1.45!important}
    .rr-contribution{display:flex;justify-content:space-between;gap:8px;font-size:12px;padding:3px 0}.rr-contribution[data-enabled="false"]{opacity:.5}
    @media(max-width:1100px){.rr-body{grid-template-columns:160px minmax(230px,1fr) 300px}.rr-head{flex-wrap:wrap}}
    @media(max-width:800px){.rr-body{display:flex;flex-direction:column;overflow-y:auto}.rr-body>.rr-favorites{max-height:170px;min-height:130px;flex-shrink:0}.rr-main{min-height:420px;flex-shrink:0}.rr-prompt-panel{overflow:visible;flex-shrink:0;border-left:0;border-top:1px solid #39414e}.rr-controls{max-height:210px}}
  `;
  document.head.append(style);
}

async function enlarge(view, image) {
  const dialog = element("dialog", "rr-dialog rr-zoom");
  const head = element("div", "rr-head");
  head.append(element("span", "", image.name), button("Close", () => dialog.close()));
  const img = element("img");
  img.alt = image.name;
  img.src = image.thumbnail_data_url;
  dialog.append(head, img);
  dialog.addEventListener("close", () => dialog.remove(), {once: true});
  document.body.append(dialog);
  dialog.showModal();
  const data = await actions.preview(view.node, {source_mode: "selection", favorite: "None", folder: "",
    selected_images: image.path, browse: false, max_images: 1, thumbnail_size: 1600});
  if (dialog.open && data.images[0]) img.src = data.images[0].thumbnail_data_url;
}

function selectionCount(view) {
  view.useSelection.textContent = `Use ${view.selected.size} checked image${view.selected.size === 1 ? "" : "s"}`;
  view.useSelection.disabled = !view.selected.size;
}

function promptPanel(view) {
  const panel = element("aside", "rr-prompt-panel");
  panel.setAttribute("aria-label", "Prompt editor");
  const heading = element("h3", "", "Reference prompt");
  const target = element("p", "rr-prompt-help");
  const status = element("div", "rr-prompt-status"); status.setAttribute("role", "status");
  const editor = element("textarea", "rr-prompt-editor");
  editor.setAttribute("aria-label", "Reference prompt text");
  editor.placeholder = "Describe the identity, clothing, setting or style this reference should contribute…";
  editor.addEventListener("input", () => {
    view.promptError = "";
    actions.setField(view.node, "favorite_prompt", editor.value);
    view.refreshPrompt();
    view.scheduleCombined?.();
  });
  const help = element("p", "rr-prompt-help");
  const name = textInput("", "Name for a new favorite…"); name.setAttribute("aria-label", "New favorite name");
  name.addEventListener("input", () => { actions.setPromptName(view.node, name.value); view.promptError = ""; view.refreshPrompt(); });
  const save = async mode => {
    if (view.saving) return;
    const node = view.node;
    const state = actions.promptState(node);
    const favoriteName = mode === "create" ? name.value.trim() : state.favorite;
    if (!favoriteName || favoriteName === "None") {
      view.promptError = mode === "create" ? "Enter a name for the new favorite." : "Select a saved favorite first.";
      view.refreshPrompt(); return;
    }
    view.saving = true; view.promptError = ""; view.refreshPrompt();
    try { await actions.save(node, favoriteName, mode); }
    catch (error) { if (view.node === node) view.promptError = String(error.message || error); }
    finally { view.saving = false; if (!view.disposed) view.refreshPrompt(); }
  };
  const saveChanges = button("Save changes", () => save("update"), "rr-primary");
  const saveNew = button("Save as new", () => save("create"));
  const revert = button("Revert", () => {
    view.promptError = ""; actions.revertPrompt(view.node); view.refreshPrompt(); view.scheduleCombined?.();
  });
  const row = element("div", "rr-row"); row.append(saveChanges, revert);
  const newRow = element("div", "rr-row"); newRow.append(saveNew);
  const deleteButton = button("Delete saved favorite", () => run(view, async () => {
    const node = view.node, state = actions.promptState(node);
    if (state.saved && window.confirm(`Delete favorite “${state.favorite}”? Current images and text will stay on this node.`))
      await actions.delete(node, state.favorite);
  }));
  const combined = element("section", "rr-combined");
  combined.setAttribute("aria-label", "Live combined prompt preview");
  const results = element("div");
  combined.append(element("h3", "", "Combined prompt · live"),
    element("p", "rr-prompt-help", "Text from enabled references, in generation order. No generation is queued."), results);
  panel.append(heading, target, status, editor, help, row, field("Save a separate favorite", name), newRow, deleteButton, combined);
  view.refreshPrompt = () => {
    if (!validNode(view.node) || view.disposed) return;
    const state = actions.promptState(view.node);
    target.textContent = nodeLabel(view.node);
    if (editor.value !== state.text) editor.value = state.text;
    if (name.value !== state.name) name.value = state.name;
    status.textContent = view.promptError || (view.saving ? "Saving…" : state.saved
      ? `${state.modified ? "Modified · not saved to" : "Saved to"} “${state.favorite}”`
      : "Draft · not saved as a favorite");
    status.classList.toggle("rr-error", Boolean(view.promptError));
    saveChanges.disabled = view.saving || !state.saved || !state.modified;
    saveNew.disabled = view.saving || !name.value.trim();
    revert.disabled = view.saving || !state.modified;
    deleteButton.disabled = view.saving || !state.saved;
    const connected = view.node.outputs?.find(output => output.name === "prompt_with_favorite")?.links?.length;
    help.textContent = connected
      ? "Edits apply as you type. Optional references contribute only when enabled. Save stores the source and text; Revert restores saved text. Drafts travel with a saved workflow."
      : "Prompt output is disconnected. Connect prompt_with_favorite to the prompt chain to use this text. Drafts are preserved when switching sources; save the workflow to keep them across reloads.";
  };
  const updateCombined = async () => {
    if (view.disposed || !actions.combinedPreview) return;
    if (view.combinedLoading) return;
    view.combinedLoading = true;
    try {
      const data = await actions.combinedPreview();
      if (view.disposed) return;
      const signature = JSON.stringify(data);
      if (signature !== view.combinedSignature) {
        view.combinedSignature = signature; results.replaceChildren();
        if (!data.length) results.append(element("p", "rr-prompt-help", "Connect an arch-Reference Prompt Compose node to preview the full prompt here."));
        for (const item of data) {
          results.append(element("strong", "", item.title));
          if (item.error) { results.append(element("p", "rr-error", item.error)); continue; }
          for (const part of item.contributions) {
            const line = element("div", "rr-contribution"); line.dataset.enabled = String(part.enabled);
            line.append(element("span", "", part.label), element("span", "", !part.enabled ? "Off" : part.text ? "Included" : "Empty"));
            line.title = part.text; results.append(line);
          }
          const text = element("textarea"); text.readOnly = true; text.value = item.text;
          text.setAttribute("aria-label", `Combined prompt ${item.id}`); results.append(text);
        }
      }
    } catch (error) {
      if (!view.disposed) { view.combinedSignature = null; results.replaceChildren(element("p", "rr-error", String(error.message || error))); }
    } finally {
      view.combinedLoading = false;
      if (!view.disposed) { clearTimeout(view.combinedTimer); view.combinedTimer = setTimeout(updateCombined, 1000); }
    }
  };
  view.scheduleCombined = () => { clearTimeout(view.combinedTimer); view.combinedTimer = setTimeout(updateCombined, 200); };
  view.refreshPrompt();
  if (actions.combinedPreview) view.scheduleCombined();
  return panel;
}

async function loadPage(view, reset = false) {
  if (reset) {
    view.request++;
    view.offset = 0;
    view.loading = false;
    view.hasMore = true;
    view.grid.replaceChildren();
    view.scroll.scrollTop = 0;
  }
  if (view.loading || !view.hasMore || !validNode(view.node) || view.disposed) return;
  const node = view.node;
  const request = view.request;
  const payload = actions.payload(node);
  if (payload.favorite === "None" && !(payload.source_mode === "selection" ? payload.selected_images.trim() : view.folder.value.trim())) {
    view.status.textContent = "Choose a folder or select images to browse.";
    view.more.hidden = true;
    return;
  }
  view.loading = true;
  view.more.disabled = true;
  view.status.classList.remove("rr-error");
  view.status.textContent = "Loading references…";
  try {
    const data = await actions.preview(node, {browse: true, offset: view.offset,
      max_images: 24, search: view.search.value, thumbnail_size: 256});
    if (view.disposed || request !== view.request || node !== view.node) return;
    for (const image of data.images) {
      const card = element("div", "rr-card");
      const zoom = button("", () => run(view, () => enlarge(view, image)));
      zoom.setAttribute("aria-label", `Enlarge ${image.name}`);
      const img = element("img");
      img.src = image.thumbnail_data_url;
      img.alt = image.name;
      img.loading = "lazy";
      zoom.append(img);
      const check = element("input");
      check.type = "checkbox";
      check.checked = view.selected.has(image.path);
      check.addEventListener("change", () => {
        if (check.checked) view.selected.add(image.path); else view.selected.delete(image.path);
        selectionCount(view);
      });
      const label = element("label");
      label.title = image.path;
      label.append(check, element("small", "", image.name));
      card.append(zoom, label);
      view.grid.append(card);
    }
    view.offset += data.images.length;
    view.hasMore = data.has_more;
    view.more.hidden = !view.hasMore;
    view.status.textContent = `${view.offset} of ${data.filtered_size} shown · ${data.pool_size} in source · ${nodeLabel(node)}`;
    if (!data.filtered_size) view.status.textContent = "No images match this search.";
  } catch (error) {
    if (request === view.request && !view.disposed) report(view, error);
  } finally {
    if (request === view.request) { view.loading = false; view.more.disabled = false; }
  }
}

function browserView(dialog, node) {
  const view = {node, request: 0, favoriteRevision: 0, offset: 0, selected: new Set(), disposed: false};
  const root = element("div", "rr-browser");
  const head = element("header", "rr-head");
  head.append(element("h2", "", "Reference Browser"), targetSelect(node, next => {
    activeNode = view.node = next;
    view.selected.clear();
    view.refresh();
  }), button("Close", () => dialog.close()));
  const body = element("div", "rr-body");
  const aside = favoriteColumn(view);
  const main = element("main", "rr-main");
  const controls = element("div", "rr-controls");
  const sourceRow = element("div", "rr-row");
  const pickFolder = () => run(view, async () => {
    const target = view.node;
    const data = await actions.dialog("browse-folder", actions.payload(target).folder);
    if (data.path && validNode(target)) actions.selectFolder(target, data.path);
  });
  const folderMode = button("Folder", pickFolder);
  const pickImages = () => run(view, async () => {
    const target = view.node;
    const data = await actions.dialog("pick-images", actions.payload(target).folder);
    if (data.paths?.length && validNode(target)) actions.selectImages(target, data.paths);
  });
  const imagesMode = button("Selected images", pickImages);
  sourceRow.append(folderMode, imagesMode);
  const folderRow = element("div", "rr-row");
  view.folder = textInput("", "Folder path…");
  view.folder.setAttribute("aria-label", "Reference folder");
  view.folder.addEventListener("change", () => actions.selectFolder(view.node, view.folder.value.trim()));
  folderRow.append(view.folder, button("Browse folder…", pickFolder));
  const imagesRow = element("div", "rr-row");
  const count = element("span", "rr-muted");
  imagesRow.append(button("Pick images…", pickImages), count);
  const options = element("div", "rr-row");
  const policy = element("select");
  for (const [value, label] of [["random_each_queue", "Random each run"], ["seeded", "Repeatable seed"], ["sequential", "Next image in order"]]) {
    const option = element("option", "", label); option.value = value; policy.append(option);
  }
  policy.addEventListener("change", () => actions.setField(view.node, "selection_policy", policy.value));
  const seed = textInput(); seed.type = "number"; seed.min = "1"; seed.step = "1";
  seed.addEventListener("change", () => actions.setField(view.node, "seed", Math.max(1, Number(seed.value) || 1)));
  const seedField = field("Seed / index", seed);
  const afterRunField = element("span", "rr-muted");
  const recursive = element("input"); recursive.type = "checkbox";
  recursive.addEventListener("change", () => actions.setField(view.node, "include_subfolders", recursive.checked));
  options.append(field("Choose", policy), seedField, afterRunField, field("Include subfolders", recursive));
  const advanced = element("details");
  advanced.append(element("summary", "", "Image paths"));
  const paths = element("textarea", "rr-paths"); paths.setAttribute("aria-label", "Selected image paths");
  paths.placeholder = "One absolute image path per line";
  paths.addEventListener("change", () => actions.selectImages(view.node, paths.value.split("\n").map(p => p.trim()).filter(Boolean)));
  advanced.append(paths);
  const searchRow = element("div", "rr-row");
  view.search = textInput("", "Search image filenames…");
  view.search.setAttribute("aria-label", "Search image filenames");
  view.search.addEventListener("input", () => {
    clearTimeout(view.searchTimer);
    view.searchTimer = setTimeout(() => loadPage(view, true), 220);
  });
  searchRow.append(view.search, button("Refresh", () => loadPage(view, true)));
  controls.append(sourceRow, folderRow, imagesRow, options, advanced, searchRow);
  view.status = element("div", "rr-status"); view.status.setAttribute("role", "status");
  view.scroll = element("div", "rr-scroll"); view.grid = element("div", "rr-grid");
  view.more = button("Load more images", () => loadPage(view), "rr-more");
  view.scroll.append(view.grid, view.more);
  view.scroll.addEventListener("scroll", () => {
    if (view.scroll.scrollHeight - view.scroll.scrollTop - view.scroll.clientHeight < 180) loadPage(view);
  });
  const footer = element("footer", "rr-footer rr-row");
  view.useSelection = button("Use checked images", () => actions.selectImages(view.node, [...view.selected]), "rr-primary");
  footer.append(view.useSelection, button("Clear checks", () => {
    view.selected.clear(); selectionCount(view); loadPage(view, true);
  }), element("span", "rr-muted", "Click a thumbnail to enlarge. Scroll for more images."));
  main.append(controls, view.status, view.scroll, footer);
  body.append(aside, main, promptPanel(view)); root.append(head, body); dialog.append(root);
  root.addEventListener("wheel", event => event.stopPropagation());
  root.addEventListener("keydown", event => event.stopPropagation());
  view.refresh = () => {
    if (!validNode(view.node)) { report(view, "The target node was removed. Reopen from another reference node."); return; }
    const payload = actions.payload(view.node);
    view.folder.value = payload.folder === "." ? "." : payload.folder || "";
    const mode = payload.source_mode === "auto" ? (payload.selected_images.trim() ? "selection" : "folder") : payload.source_mode;
    const sourceKey = JSON.stringify([payload.source_mode, payload.folder, payload.selected_images, payload.favorite]);
    const sourceChanged = view.sourceKey !== sourceKey || view.sourceNode !== view.node;
    const poolChanged = sourceChanged || view.recursive !== payload.include_subfolders;
    if (view.sourceNode !== view.node) view.promptError = "";
    view.sourceNode = view.node;
    view.recursive = payload.include_subfolders;
    if (sourceChanged) {
      view.search.value = "";
      view.selected = new Set(mode === "selection" ? imagePaths(payload.selected_images) : []);
      view.sourceKey = sourceKey;
    }
    folderMode.classList.toggle("rr-active", mode === "folder");
    imagesMode.classList.toggle("rr-active", mode === "selection");
    folderRow.hidden = mode !== "folder";
    imagesRow.hidden = mode !== "selection";
    count.textContent = `${imagePaths(payload.selected_images).length} image path(s)`;
    policy.value = payload.selection_policy; seed.value = payload.seed;
    seedField.hidden = payload.selection_policy === "random_each_queue";
    afterRunField.hidden = seedField.hidden;
    afterRunField.textContent = payload.selection_policy === "sequential"
      ? "Index advances automatically after each run."
      : "Seed stays fixed between runs.";
    recursive.checked = payload.include_subfolders;
    recursive.disabled = mode !== "folder";
    paths.value = imagePaths(payload.selected_images).join("\n");
    view.refreshPrompt();
    view.scheduleCombined?.();
    selectionCount(view);
    run(view, () => favorites(view));
    if (poolChanged) loadPage(view, true);
  };
  views.add(view);
  dialog.addEventListener("close", () => {
    view.disposed = true; view.request++; clearTimeout(view.searchTimer); clearTimeout(view.combinedTimer); view.favoriteObserver?.disconnect(); views.delete(view);
    dialog.remove(); if (browser === dialog) browser = undefined;
  }, {once: true});
  view.refresh();
}

export function openReferenceBrowser(node = activeNode) {
  if (!validNode(node)) return;
  installStyle();
  browser?.close();
  activeNode = node;
  browser = element("dialog", "rr-dialog");
  document.body.append(browser);
  browserView(browser, node);
  browser.showModal();
}

export function refreshReferenceBrowser(node) {
  for (const view of views) if (view.node === node && !view.disposed) view.refresh();
}

export function refreshReferencePrompt(node) {
  for (const view of views) if (view.node === node && !view.disposed) {
    view.refreshPrompt?.(); view.scheduleCombined?.();
  }
}

export function installReferenceBrowser(app, hooks) {
  actions = hooks;
  installStyle();
  app.extensionManager.registerSidebarTab({
    id: "arch-random-reference-browser", icon: "pi pi-images", title: "Reference Favorites", type: "custom",
    render(container) {
      const root = element("div", "rr-sidebar");
      const node = validNode(activeNode) ? activeNode : actions.nodes()[0];
      if (!node) {
        root.append(element("p", "", "Add or open a workflow with an arch-Random Reference Image Source node."));
        container.replaceChildren(root); return;
      }
      const view = {node, favoriteRevision: 0};
      root.append(targetSelect(node, next => { activeNode = view.node = next; view.refresh(); }),
        button("Open Reference Browser…", () => openReferenceBrowser(view.node), "rr-primary"), favoriteColumn(view));
      view.status = element("div", "rr-status"); root.append(view.status);
      view.refresh = () => {
        if (!root.isConnected) { view.disposed = true; view.favoriteObserver?.disconnect(); views.delete(view); return; }
        view.status.textContent = `Applies to ${nodeLabel(view.node)}`;
        run(view, () => favorites(view));
      };
      container.replaceChildren(root); views.add(view); view.refresh();
    },
  });
}
