// The browser edits the selected node's existing widgets; it owns no separate
// source state. Explicit library saves copy images into the local library.
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
    if (!view.favoriteList.childElementCount) view.favoriteList.append(element("p", "rr-muted",
      Object.keys(data).length ? "No matching groups" : "No groups yet. Check photos and choose Save to favorite group…"));
  };
  view.favoriteSearch.oninput = draw;
  draw();
}

function favoriteColumn(view) {
  const aside = element("aside", "rr-favorites");
  view.favoriteSearch = textInput("", "Search favorites…");
  view.favoriteSearch.setAttribute("aria-label", "Search favorites");
  view.favoriteList = element("div", "rr-favorite-list");
  aside.append(element("h3", "", "Favorite groups"), element("p", "rr-prompt-help", "Click a group to use its photos for runs."), view.favoriteSearch, view.favoriteList);
  return aside;
}

function installStyle() {
  if (document.getElementById("arch-reference-browser-style")) return;
  const style = element("style");
  style.id = "arch-reference-browser-style";
  style.textContent = `
    .rr-dialog{width:calc(100vw - 16px);height:calc(100dvh - 16px);max-width:none;max-height:none;margin:auto;box-sizing:border-box;
      padding:0;border:1px solid #505968;border-radius:8px;background:#181d25;color:#edf1f7;z-index:10000}
    .rr-dialog::backdrop{background:#000a}.rr-browser,.rr-sidebar{font:14px/1.4 system-ui;color:#edf1f7;box-sizing:border-box}
    .rr-browser{height:100%;display:flex;flex-direction:column}.rr-browser *,.rr-sidebar *{box-sizing:border-box}
    .rr-browser [hidden],.rr-sidebar [hidden]{display:none!important}
    .rr-head{display:flex;align-items:center;gap:8px;padding:7px 10px;border-bottom:1px solid #39414e;flex-shrink:0}
    .rr-head h2{font-size:18px;margin:0}.rr-head select{flex:1;min-width:150px}
    .rr-browser button,.rr-sidebar button,.rr-browser input,.rr-sidebar input,.rr-browser select,.rr-sidebar select,.rr-browser textarea{
      font:inherit;color:inherit;background:#262e3a;border:1px solid #505b6d;border-radius:6px;padding:7px 10px}
    .rr-browser button,.rr-sidebar button{cursor:pointer}.rr-browser button:hover,.rr-sidebar button:hover{background:#35445b}
    .rr-browser button:disabled{opacity:.45;cursor:default}.rr-primary,.rr-active{border-color:#7ab8ff!important;background:#29476b!important}
    .rr-body{display:flex;position:relative;flex:1;min-height:0;min-width:0}
    .rr-body>.rr-main{flex:1}.rr-body>.rr-favorites{width:220px;flex-shrink:0}
    .rr-body>.rr-prompt-panel{width:320px;flex-shrink:0}
    .rr-favorites{display:flex;flex-direction:column;gap:10px;padding:14px;min-height:0;border-right:1px solid #39414e}
    .rr-favorites h3{margin:0;font-size:15px}.rr-favorites input{width:100%}
    .rr-favorite-list{overflow-y:auto;flex:1;min-height:0;overscroll-behavior:contain}
    .rr-favorite{width:100%;text-align:left;margin-bottom:8px;display:flex;flex-direction:column;gap:5px}
    .rr-favorite small{opacity:.7;overflow-wrap:anywhere}.rr-main{display:flex;flex-direction:column;min-height:0;min-width:0}
    .rr-has-thumb{display:grid;grid-template-columns:48px minmax(0,1fr)}
    .rr-has-thumb strong,.rr-has-thumb small{grid-column:2}.rr-has-thumb img{grid-column:1;grid-row:1/3;width:48px;height:48px;object-fit:cover;border-radius:4px}
    .rr-controls{padding:7px 10px;display:flex;align-items:center;gap:8px;flex-shrink:0;position:relative}
    .rr-toolbar{display:flex;align-items:center;gap:8px;flex:1;min-width:0}
    .rr-toolbar>input{flex:1;min-width:100px;width:100px}.rr-toolbar>button{flex-shrink:0;white-space:nowrap}
    .rr-settings>summary{cursor:pointer;white-space:nowrap;padding:7px 10px}
    .rr-controls>.rr-settings{border:0;padding:0}
    .rr-settings[open]>summary{background:#29476b;border-radius:6px}
    .rr-settings-panel{position:absolute;right:10px;top:100%;width:min(560px,calc(100vw - 36px));max-height:60vh;overflow:auto;background:#202835;border:1px solid #505968;border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:12px;z-index:3;box-shadow:0 6px 24px #0008}
    .rr-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.rr-row>input{flex:1;min-width:140px}
    .rr-field{display:flex;align-items:center;gap:8px}.rr-field span{opacity:.8}.rr-field textarea{width:100%;min-height:70px}
    .rr-paths{width:100%;height:72px;resize:vertical}.rr-controls details{border-top:1px solid #39414e;padding-top:8px}
    .rr-controls summary{cursor:pointer}.rr-controls details>.rr-row{margin-top:10px}
    .rr-status{padding:3px 10px;white-space:pre-wrap;overflow-wrap:anywhere;flex-shrink:0;color:#bfcce0;background:#202835;font-size:12px}
    .rr-source-summary{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .rr-error{color:#ffb1a5}.rr-pending{color:#ffdc94;font-weight:600}.rr-scroll{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:16px 18px}
    .rr-scroll{padding:3px}
    .rr-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:4px}
    .rr-card{min-width:0;padding:0!important;position:relative;line-height:0}
    .rr-card>button{display:block;width:100%;padding:0;border-radius:2px;overflow:hidden}
    .rr-card>.rr-enlarge{position:absolute;right:4px;bottom:4px;width:30px;height:30px;padding:2px;background:#10141bcc;font-size:20px;line-height:1}
    .rr-card img{display:block;width:100%;height:220px;object-fit:contain;background:#10141b}
    .rr-card label{position:absolute;top:4px;left:4px;padding:3px;background:#10141bcc;border-radius:3px}
    .rr-card input{margin:0;width:18px;height:18px;accent-color:#7ab8ff}
    .rr-card:has(input:checked)>button{outline:2px solid #7ab8ff;outline-offset:-2px}
    .rr-more{display:block;margin:18px auto}.rr-footer{padding:6px 10px;border-top:1px solid #39414e;flex-shrink:0;flex-wrap:nowrap!important;overflow-x:auto}
    .rr-footer>button{flex-shrink:0;white-space:nowrap}
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
    @media(max-width:900px){.rr-body>.rr-favorites,.rr-body>.rr-prompt-panel{position:absolute;top:0;bottom:0;z-index:4;background:#181d25;box-shadow:0 0 24px #0008}.rr-body>.rr-favorites{left:0}.rr-body>.rr-prompt-panel{right:0}.rr-head h2{font-size:14px}.rr-head select{min-width:80px}.rr-toolbar{overflow-x:auto}.rr-toolbar>input{min-width:120px}}
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
    selected_images: actions.encodePaths([image.path]), browse: false, max_images: 1, thumbnail_size: 1600});
  if (dialog.open && data.images[0]) img.src = data.images[0].thumbnail_data_url;
}

function selectionCount(view) {
  const applied = view.activeSelection && view.selected.size === view.activeSelection.size &&
    [...view.selected].every(path => view.activeSelection.has(path));
  if (view.selectionStatus) {
    view.selectionStatus.textContent = `${view.selected.size} checked · ` +
      (applied ? "matches active run source" : view.selected.size ? "not applied to runs" : "active run source unchanged");
    view.selectionStatus.classList.toggle("rr-pending", Boolean(view.selected.size && !applied));
  }
  if (view.sourceKey && !view.initializeSelection) {
    view.node._archBrowserChecks = {sourceKey: view.sourceKey, paths: [...view.selected]};
  }
  view.useSelection.textContent = `Use ${view.selected.size} checked image${view.selected.size === 1 ? "" : "s"}`;
  view.useSelection.disabled = !view.selected.size;
  if (view.saveCharacter) view.saveCharacter.disabled = !view.selected.size;
  if (view.saveGroup) view.saveGroup.disabled = !view.selected.size;
}

async function saveGroup(view) {
  const node = view.node, paths = [...view.selected];
  if (!paths.length) return;
  const dialog = element("dialog", "rr-dialog rr-browser");
  dialog.style.width = "520px"; dialog.style.height = "auto"; dialog.style.padding = "18px";
  const status = element("p", "rr-status", "Loading favorite groups…");
  const target = element("select"); target.setAttribute("aria-label", "Favorite group to update");
  const fresh = element("option", "", "Create a new group…"); fresh.value = ""; target.append(fresh);
  const name = textInput("", "Name this image group"); name.setAttribute("aria-label", "Favorite group name");
  const save = button("Create favorite group", async () => {
    const groupName = name.value.trim();
    if (!groupName) { status.textContent = "Enter a group name."; return; }
    save.disabled = target.disabled = name.disabled = true;
    try {
      if (!validNode(node)) throw new Error("The reference node was removed.");
      await actions.save(node, groupName, target.value ? "update" : "create", paths, target.value || null);
      if (dialog.open) dialog.close();
    } catch (error) {
      status.textContent = String(error.message || error); status.classList.add("rr-error");
    } finally { save.disabled = target.disabled = name.disabled = false; }
  }, "rr-primary");
  save.disabled = true;
  target.addEventListener("change", () => {
    name.value = target.value;
    save.textContent = target.value ? "Replace group with checked images" : "Create favorite group";
  });
  dialog.append(element("h3", "", "Save to favorite group"),
    element("p", "", `${paths.length} checked image(s). Groups store local paths and reference prompt text for reuse as a run source. Library saves copy images into subject or environment collections.`),
    target, name, status, save, button("Cancel", () => dialog.close()));
  dialog.addEventListener("close", () => dialog.remove(), {once: true});
  document.body.append(dialog); dialog.showModal();
  try {
    const groups = await actions.presets(node);
    if (!dialog.open) return;
    for (const groupName of Object.keys(groups).sort()) {
      const option = element("option", "", groupName); option.value = groupName; target.append(option);
    }
    target.value = ""; save.disabled = false;
    status.textContent = "Create a named group, or select an existing group to edit its name and replace its images with these checks. Saving selects the group for this node.";
  } catch (error) { status.textContent = String(error.message || error); }
}

function syncChecks(view) {
  for (const [path, check] of view.checks) check.checked = view.selected.has(path);
  selectionCount(view);
}

async function selectAll(view) {
  const node = view.node, request = view.request, revision = ++view.selectionRevision;
  view.selectAll.disabled = true;
  try {
    const data = await actions.preview(node, {paths_only: true, search: view.search.value});
    if (view.disposed || node !== view.node || request !== view.request || revision !== view.selectionRevision) return;
    for (const path of data.paths) view.selected.add(path);
    view.initializeSelection = false;
    syncChecks(view);
  } finally { if (!view.disposed) view.selectAll.disabled = false; }
}

async function saveCharacter(view) {
  const paths = [...view.selected];
  if (!paths.length) return;
  const dialog = element("dialog", "rr-dialog");
  dialog.style.width = "460px"; dialog.style.height = "auto"; dialog.style.padding = "18px";
  dialog.classList.add("rr-browser");
  const status = element("p", "rr-status", "Loading library…");
  const kind = element("select"); kind.setAttribute("aria-label", "Save collection kind");
  for (const [value, label] of [["subject", "Subject / Character"], ["environment", "Environment / Location"]]) {
    const option = element("option", "", label); option.value = value; kind.append(option);
  }
  kind.value = "subject";
  const select = element("select"); select.setAttribute("aria-label", "Destination collection");
  const name = textInput("", "New collection name"); name.setAttribute("aria-label", "New collection name");
  let collections = [], savedCollection;
  const open = button("Open saved collection", () => run(view, async () => {
    await actions.openLibrary(savedCollection); dialog.close(); browser?.close();
  }));
  open.disabled = true;
  const drawCollections = () => {
    select.replaceChildren();
    const fresh = element("option", "", "New collection…"); fresh.value = ""; select.append(fresh);
    for (const item of collections.filter(item => item.kind === kind.value)) {
      const option = element("option", "", item.name); option.value = item.id; select.append(option);
    }
    select.value = ""; name.hidden = false; save.disabled = false;
  };
  const save = button(`Save ${paths.length} image${paths.length === 1 ? "" : "s"}`, async () => {
    save.disabled = true; select.disabled = name.disabled = kind.disabled = true;
    try {
      let id = select.value;
      if (!id) {
        if (!name.value.trim()) throw new Error("Enter a collection name.");
        const created = await actions.library("/collections", {kind: kind.value, name: name.value.trim()});
        id = created.collection.id;
        collections.push(created.collection);
        const option = element("option", "", created.collection.name); option.value = id; select.append(option); select.value = id;
      }
      const result = await actions.library(`/collections/${encodeURIComponent(id)}/import-paths`, {paths});
      savedCollection = collections.find(item => item.id === id) || {id, kind: kind.value};
      open.disabled = false;
      status.textContent = `Saved ${result.imports.length} image(s) to the local reference library. Originals are unchanged.`;
      if (result.failures?.length) {
        status.textContent += `\n${result.failures.length} could not be saved:\n` + result.failures.map(item => `${item.path}: ${item.error}`).join("\n");
        save.disabled = false;
      }
      view.status.textContent = status.textContent;
    } catch (error) { status.textContent = String(error.message || error); save.disabled = false; }
    finally { select.disabled = name.disabled = kind.disabled = false; }
  }, "rr-primary");
  save.disabled = true;
  kind.addEventListener("change", drawCollections);
  select.addEventListener("change", () => { name.hidden = Boolean(select.value); save.disabled = false; });
  dialog.append(element("h3", "", "Save checked images to library"), kind, select, name, status, save, open,
    button("Close", () => dialog.close()));
  dialog.addEventListener("close", () => dialog.remove(), {once: true});
  document.body.append(dialog); dialog.showModal();
  try {
    const data = await actions.library("/bootstrap?kind=subject&page_size=1&orphan_page_size=1");
    if (!dialog.open) return;
    collections = data.collections;
    drawCollections();
    status.textContent = "Choose a collection or create one. Checked images will be copied into the local library.";
  } catch (error) { status.textContent = String(error.message || error); }
}

async function loadLibrary(view) {
  const node = view.node;
  const dialog = element("dialog", "rr-dialog rr-browser");
  dialog.style.cssText = "width:min(560px,94vw);height:auto;padding:18px;gap:12px";
  const status = element("p", "rr-status", "Loading collections…");
  const kind = element("select"); kind.setAttribute("aria-label", "Library collection kind");
  for (const [value, label] of [["subject", "Subjects / Characters"], ["environment", "Environments / Locations"]]) {
    const option = element("option", "", label); option.value = value; kind.append(option);
  }
  kind.value = "subject";
  const collection = element("select"); collection.setAttribute("aria-label", "Library collection");
  const profile = element("select"); profile.setAttribute("aria-label", "Library prompt profile");
  const filtered = element("input"); filtered.type = "checkbox"; filtered.checked = true;
  filtered.setAttribute("aria-label", "Use library tag filters");
  const includePrompt = element("input"); includePrompt.type = "checkbox";
  includePrompt.setAttribute("aria-label", "Use profile positive prompt");
  let collections = [], revision = 0, profilesLoading = false;
  const sourcePath = () => `/collections/${encodeURIComponent(collection.value)}/source?` +
    new URLSearchParams({filtered: String(filtered.checked), ...(profile.value ? {profile_id: profile.value} : {})});
  const inspect = async (refreshProfiles = false) => {
    if (profilesLoading && !refreshProfiles) return;
    const current = ++revision;
    use.disabled = true;
    if (refreshProfiles) {
      profile.replaceChildren(); profile.value = "";
      profilesLoading = true; profile.disabled = filtered.disabled = true;
    }
    if (!collection.value) { profilesLoading = false; status.textContent = "No collections of this kind yet. Save checked images to the library first."; return; }
    status.textContent = "Loading collection…";
    try {
      if (refreshProfiles) {
        const data = await actions.library(`/bootstrap?collection_id=${encodeURIComponent(collection.value)}&kind=${kind.value}&page_size=1&orphan_page_size=1`);
        if (!dialog.open || current !== revision) return;
        profile.replaceChildren();
        const defaultOption = element("option", "", "Default profile"); defaultOption.value = ""; profile.append(defaultOption);
        for (const item of data.detail?.profiles || []) {
          const option = element("option", "", item.name); option.value = item.id; profile.append(option);
        }
        profile.value = "";
      }
      const data = await actions.library(sourcePath());
      if (!dialog.open || current !== revision) return;
      status.textContent = `${data.pool_count} available of ${data.total_count} images. ` +
        (data.paths.length ? "Load creates a snapshot for this node; future library changes are not applied automatically." : "No images match. Try disabling tag filters or choose another collection.");
      use.disabled = !data.paths.length;
    } catch (error) { if (dialog.open && current === revision) status.textContent = String(error.message || error); }
    finally { if (current === revision) { profilesLoading = false; profile.disabled = filtered.disabled = false; } }
  };
  const drawCollections = () => {
    collection.replaceChildren();
    const items = collections.filter(item => item.kind === kind.value);
    for (const item of items) { const option = element("option", "", item.name); option.value = item.id; collection.append(option); }
    collection.value = items[0]?.id || "";
    inspect(true);
  };
  const use = button("Use collection images", async () => {
    const before = JSON.stringify(actions.payload(node)), current = ++revision;
    use.disabled = kind.disabled = collection.disabled = profile.disabled = filtered.disabled = includePrompt.disabled = true;
    try {
      const data = await actions.library(sourcePath());
      if (!dialog.open || view.disposed || node !== view.node || !validNode(node)) return;
      if (before !== JSON.stringify(actions.payload(node))) throw new Error("The source changed while loading. Choose the collection again.");
      if (!data.paths.length) throw new Error("This collection has no matching images.");
      actions.selectLibrary(node, data, includePrompt.checked);
      dialog.close();
    } catch (error) { if (dialog.open && current === revision) status.textContent = String(error.message || error); }
    finally { use.disabled = kind.disabled = collection.disabled = profile.disabled = filtered.disabled = includePrompt.disabled = false; }
  }, "rr-primary");
  use.disabled = true;
  const open = button("Open in Reference Library", () => run(view, async () => {
    const selected = collections.find(item => item.id === collection.value);
    if (!selected) return;
    await actions.openLibrary(selected); dialog.close(); browser?.close();
  }));
  kind.addEventListener("change", drawCollections);
  collection.addEventListener("change", () => inspect(true));
  profile.addEventListener("change", () => inspect());
  filtered.addEventListener("change", () => inspect());
  dialog.append(element("h3", "", "Load from Reference Library"), kind, collection,
    field("Use library tag filters", filtered), field("Prompt profile", profile),
    field("Replace this node's reference prompt with the profile's positive prompt", includePrompt),
    element("p", "rr-prompt-help", "Negative prompts and LoRAs are not applied here. Use the Reference Library selector and profile LoRA nodes for those outputs."),
    status, use, open, button("Cancel", () => dialog.close()));
  dialog.addEventListener("close", () => { revision++; dialog.remove(); }, {once: true});
  document.body.append(dialog); dialog.showModal();
  try {
    const data = await actions.library("/bootstrap?page_size=1&orphan_page_size=1");
    if (!dialog.open) return;
    collections = data.collections; drawCollections();
  } catch (error) { if (dialog.open) status.textContent = String(error.message || error); }
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
  const sourceSave = element("details");
  sourceSave.append(element("summary", "", "Save whole source + prompt as a new group"),
    element("p", "rr-prompt-help", "This saves the active run source. To save checked photos only, use Save to favorite group below the gallery."),
    field("New group name", name), newRow);
  panel.append(heading, target, status, editor, help, row, sourceSave, deleteButton, combined);
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
    view.checks.clear();
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
    if (view.initializeSelection) {
      view.activeSelection = data.mode === "folder" || !data.selection_paths?.length ? null : new Set(data.selection_paths);
      const savedChecks = node._archBrowserChecks;
      view.selected = new Set(savedChecks?.sourceKey === view.sourceKey ? savedChecks.paths : data.selection_paths || []);
      view.initializeSelection = false;
      selectionCount(view);
    }
    for (const image of data.images) {
      const card = element("div", "rr-card");
      card.title = image.name;
      const zoom = button("", () => {
        check.checked = !check.checked;
        view.selectionRevision++;
        if (check.checked) view.selected.add(image.path); else view.selected.delete(image.path);
        selectionCount(view);
      });
      zoom.setAttribute("aria-label", `Toggle selection of ${image.name}`);
      const img = element("img");
      img.src = image.thumbnail_data_url;
      img.alt = image.name;
      img.loading = "lazy";
      zoom.append(img);
      const check = element("input");
      check.type = "checkbox";
      check.checked = view.selected.has(image.path);
      view.checks.set(image.path, check);
      check.setAttribute("aria-label", `Select ${image.name}`);
      check.addEventListener("change", () => {
        view.selectionRevision++;
        if (check.checked) view.selected.add(image.path); else view.selected.delete(image.path);
        selectionCount(view);
      });
      const label = element("label");
      label.title = image.path;
      label.append(check);
      const expand = button("⤢", () => run(view, () => enlarge(view, image)), "rr-enlarge");
      expand.setAttribute("aria-label", `Enlarge ${image.name}`); expand.title = "Enlarge image";
      card.append(zoom, label, expand);
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
  const view = {node, request: 0, favoriteRevision: 0, offset: 0, selected: new Set(), checks: new Map(), selectionRevision: 0, disposed: false};
  const root = element("div", "rr-browser");
  const head = element("header", "rr-head");
  const groupsToggle = button("Groups", () => {
    aside.hidden = !aside.hidden;
    groupsToggle.setAttribute("aria-expanded", String(!aside.hidden));
  });
  const promptToggle = button("Prompt", () => {
    prompt.hidden = !prompt.hidden;
    promptToggle.setAttribute("aria-expanded", String(!prompt.hidden));
  });
  groupsToggle.setAttribute("aria-expanded", "false"); promptToggle.setAttribute("aria-expanded", "false");
  head.append(element("h2", "", "Reference Browser"), targetSelect(node, next => {
    activeNode = view.node = next;
    view.selected.clear();
    view.refresh();
  }), groupsToggle, promptToggle, button("Close", () => dialog.close()));
  const body = element("div", "rr-body");
  const aside = favoriteColumn(view);
  aside.hidden = true;
  const main = element("main", "rr-main");
  const controls = element("div", "rr-controls");
  const sourceRow = element("div", "rr-row");
  const pick = endpoint => run(view, async () => {
    if (view.picking) return;
    const target = view.node, before = JSON.stringify(actions.payload(target));
    view.picking = true;
    folderMode.disabled = imagesMode.disabled = true;
    view.status.textContent = "Choose in the native picker on this PC. Cancel keeps the current source.";
    try {
      const data = await actions.dialog(endpoint, actions.payload(target).folder);
      if (view.disposed || view.node !== target || !validNode(target) || before !== JSON.stringify(actions.payload(target))) return;
      if (data.path) actions.selectFolder(target, data.path);
      else if (data.paths?.length) { view.sourceKey = null; actions.selectImages(target, data.paths); }
      else view.status.textContent = "Picker cancelled. Source unchanged.";
    } finally { view.picking = false; folderMode.disabled = imagesMode.disabled = false; }
  });
  const pickFolder = () => pick("browse-folder");
  const folderMode = button("Load folder…", pickFolder);
  const pickImages = () => pick("pick-images");
  const imagesMode = button("Load images…", pickImages);
  sourceRow.append(folderMode, imagesMode, button("Load from library…", () => run(view, () => loadLibrary(view))));
  const folderRow = element("div", "rr-row");
  view.folder = textInput("", "Folder path…");
  view.folder.setAttribute("aria-label", "Reference folder");
  folderRow.append(view.folder, button("Load folder path", () => actions.selectFolder(view.node, view.folder.value.trim())));
  const imagesRow = element("div", "rr-row");
  const count = element("span", "rr-muted");
  imagesRow.append(count);
  const options = element("div", "rr-row");
  const policy = element("select");
  for (const [value, label] of [["random_each_queue", "Random each run"], ["seeded", "Repeatable seed"], ["sequential", "Next image in order"], ["shuffle_cycle", "Shuffle without repeats (per cycle)"]]) {
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
  view.search = textInput("", "Search image filenames…");
  view.search.setAttribute("aria-label", "Search image filenames");
  view.search.addEventListener("input", () => {
    clearTimeout(view.searchTimer);
    view.searchTimer = setTimeout(() => loadPage(view, true), 220);
  });
  const settings = element("details", "rr-settings");
  settings.append(element("summary", "", "Settings"));
  const settingsPanel = element("div", "rr-settings-panel");
  settingsPanel.append(folderRow, imagesRow, options, advanced,
    element("p", "rr-prompt-help", "Click photos to select. ⤢ enlarges. Use checked images applies them to runs; saving a group also selects it."));
  settings.append(settingsPanel);
  sourceRow.classList.add("rr-toolbar");
  sourceRow.append(view.search, button("Refresh", () => loadPage(view, true)));
  controls.append(sourceRow, settings);
  view.status = element("div", "rr-status"); view.status.setAttribute("role", "status");
  view.sourceSummary = element("div", "rr-status rr-source-summary"); view.sourceSummary.setAttribute("aria-label", "Active run source and image connection");
  view.scroll = element("div", "rr-scroll"); view.grid = element("div", "rr-grid");
  view.more = button("Load more images", () => loadPage(view), "rr-more");
  view.scroll.append(view.grid, view.more);
  view.scroll.addEventListener("scroll", () => {
    if (view.scroll.scrollHeight - view.scroll.scrollTop - view.scroll.clientHeight < 180) loadPage(view);
  });
  const footer = element("footer", "rr-footer rr-row");
  view.useSelection = button("Use checked images", () => actions.selectImages(view.node, [...view.selected]), "rr-primary");
  view.selectAll = button("Select all", () => run(view, () => selectAll(view)));
  view.selectAll.title = "Select every matching image, including unloaded pages";
  view.saveCharacter = button("Save to library…", () => run(view, () => saveCharacter(view)));
  view.saveGroup = button("Save to favorite group…", () => run(view, () => saveGroup(view)));
  footer.append(view.selectAll, button("Unselect all", () => {
    view.selectionRevision++; view.initializeSelection = false;
    view.selected.clear(); syncChecks(view);
  }), view.useSelection, view.saveGroup, view.saveCharacter);
  view.selectionStatus = element("div", "rr-status"); view.selectionStatus.setAttribute("aria-label", "Checked images status");
  view.selectionStatus.setAttribute("role", "status");
  main.append(controls, view.sourceSummary, view.status, view.scroll, view.selectionStatus, footer);
  const prompt = promptPanel(view); prompt.hidden = true;
  body.append(aside, main, prompt); root.append(head, body); dialog.append(root);
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
      view.selected = new Set();
      view.activeSelection = null;
      view.initializeSelection = true;
      view.selectionRevision++;
      view.sourceKey = sourceKey;
    }
    folderMode.classList.toggle("rr-active", mode === "folder");
    imagesMode.classList.toggle("rr-active", mode === "selection");
    folderRow.hidden = false;
    imagesRow.hidden = mode !== "selection";
    count.textContent = `${imagePaths(payload.selected_images).length} image path(s)`;
    const imageLinks = view.node.outputs?.find(output => output.type === "IMAGE")?.links?.length || 0;
    const sourceDescription = payload.favorite !== "None" ? `Favorite group “${payload.favorite}”`
      : mode === "folder" ? `Folder: ${payload.folder || "none chosen"}`
      : `${imagePaths(payload.selected_images).length} selected image(s)`;
    view.sourceSummary.textContent = `Run source: ${sourceDescription}. One image per run.\n` +
      (imageLinks ? `Image output has ${imageLinks} connection(s); downstream switches still control whether it is used.`
        : "Image output is disconnected. Connect IMAGE to the workflow to use these photos.");
    view.sourceSummary.title = view.sourceSummary.textContent;
    policy.value = payload.selection_policy; seed.value = payload.seed;
    seedField.hidden = payload.selection_policy === "random_each_queue";
    afterRunField.hidden = seedField.hidden;
    afterRunField.textContent = ["sequential", "shuffle_cycle"].includes(payload.selection_policy)
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
