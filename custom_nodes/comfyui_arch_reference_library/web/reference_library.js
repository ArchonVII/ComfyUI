import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const ROOT = "/arch-reference-library";
const SIDEBAR_ID = "arch.reference-library";
const SELECTOR_KINDS = {
  ArchSubjectReferenceSelector: "subject",
  ArchEnvironmentReferenceSelector: "environment",
};

function installCss() {
  if (document.querySelector?.("link[data-arch-reference-library-css]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.dataset.archReferenceLibraryCss = "true";
  link.href = new URL("./reference_library.css", import.meta.url).href;
  document.head.append(link);
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action, className) {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function labeled(labelText, control) {
  const label = element("label", undefined, "arch-ref-field");
  label.append(element("span", labelText), control);
  return label;
}

function textInput(value = "", placeholder = "") {
  const input = element("input");
  input.type = "text";
  input.value = value ?? "";
  input.placeholder = placeholder;
  return input;
}

function selectInput(options, value) {
  const select = element("select");
  for (const item of options) {
    const option = element("option", item.label ?? item.name ?? String(item));
    option.value = item.value ?? item.id ?? String(item);
    select.append(option);
  }
  if (value !== undefined && value !== null) select.value = value;
  return select;
}

async function responseJson(response) {
  const copy = typeof response.clone === "function" ? response.clone() : response;
  const data = await copy.json().catch(() => ({}));
  if (!response.ok) {
    const text = typeof response.text === "function" ? await response.text().catch(() => "") : "";
    throw new Error(data.error || data.message || text || `request failed (${response.status})`);
  }
  return data;
}

async function request(path, { method = "GET", body } = {}) {
  const options = { method };
  if (body !== undefined) {
    if (body instanceof FormData) {
      options.body = body;
    } else {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
  }
  return responseJson(await api.fetchApi(`${ROOT}${path}`, options));
}

function normalizeFilters(value = {}) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("filters must be an object");
  const unknown = Object.keys(value).filter((key) => !["include_all", "include_any", "exclude"].includes(key));
  if (unknown.length) throw new Error(`unknown filter fields: ${unknown.join(", ")}`);
  const result = {};
  for (const key of ["include_all", "include_any", "exclude"]) {
    const raw = value[key] ?? [];
    if (!Array.isArray(raw) || raw.some((item) => typeof item !== "string" || !item)) throw new Error(`${key} must be an array of IDs`);
    result[key] = [...new Set(raw)];
  }
  return result;
}

function batchTagPayload(collectionId, imageIds, tagId, action) {
  if (!collectionId || !tagId || !Array.isArray(imageIds) || !imageIds.length) throw new Error("select a collection, images, and tag");
  if (!new Set(["add", "remove"]).has(action)) throw new Error("batch tag action must be add or remove");
  return {
    collection_id: collectionId,
    image_ids: [...new Set(imageIds)],
    add_tag_ids: action === "add" ? [tagId] : [],
    remove_tag_ids: action === "remove" ? [tagId] : [],
  };
}

function pinSlot(slots, slotNumber, imageId) {
  if (!Array.isArray(slots) || ![1, 2, 3, 4].includes(slotNumber) || !imageId) throw new Error("choose a valid slot and image");
  const result = slots.map((slot) => ({ slot: slot.slot, image_id: slot.image_id ?? null, pinned: Boolean(slot.pinned) }));
  for (const slot of result) {
    if (slot.image_id === imageId) {
      slot.image_id = null;
      slot.pinned = false;
    }
    if (slot.slot === slotNumber) {
      slot.image_id = imageId;
      slot.pinned = true;
    }
  }
  return result;
}

function safe(status, operation) {
  return async (...args) => {
    try {
      status.textContent = "Working…";
      const result = await operation(...args);
      status.textContent = "Ready";
      return result;
    } catch (error) {
      status.textContent = `Error: ${String(error.message || error)}`;
      return undefined;
    }
  };
}

function collectionOptions(data, kind) {
  return (data?.collections ?? [])
    .filter((item) => item.kind === kind)
    .map((item) => ({ value: item.id, label: item.name }));
}

function activeCollectionId(state) {
  return state.collectionId || state.data?.active?.[state.kind]?.id || "";
}

function selectedDetail(state) {
  return state.data?.detail?.collection?.id === activeCollectionId(state) ? state.data.detail : null;
}

function renderCollectionControls(parent, state, status, refresh) {
  const section = element("section", undefined, "arch-ref-section");
  section.append(element("h3", "Collection"));
  const options = collectionOptions(state.data, state.kind);
  const chooser = selectInput([{ value: "", label: `Choose ${state.kind}` }, ...options], activeCollectionId(state));
  chooser.setAttribute("aria-label", `Active ${state.kind}`);
  chooser.addEventListener("change", safe(status, async () => {
    if (!chooser.value) return;
    await request(`/active/${state.kind}`, { method: "PUT", body: { collection_id: chooser.value } });
    state.collectionId = chooser.value;
    state.selectedImages.clear();
    await refresh();
  }));
  section.append(labeled(`Active ${state.kind}`, chooser));

  const createRow = element("div", undefined, "arch-ref-row");
  const name = textInput("", `${state.kind} name`);
  const description = textInput("", "optional description");
  createRow.append(name, description, button("Add collection", safe(status, async () => {
    const created = await request("/collections", { method: "POST", body: { kind: state.kind, name: name.value, description: description.value } });
    await request(`/active/${state.kind}`, { method: "PUT", body: { collection_id: created.collection.id } });
    state.collectionId = created.collection.id;
    await refresh();
  })));
  section.append(createRow);

  const detail = selectedDetail(state);
  if (detail) {
    const editRow = element("div", undefined, "arch-ref-row");
    const editName = textInput(detail.collection.name);
    const editDescription = textInput(detail.collection.description, "description");
    editRow.append(
      editName,
      editDescription,
      button("Save collection", safe(status, async () => {
        await request(`/collections/${detail.collection.id}`, { method: "PATCH", body: { name: editName.value, description: editDescription.value } });
        await refresh();
      })),
      button("Delete collection", safe(status, async () => {
        if (globalThis.confirm && !globalThis.confirm(`Delete ${detail.collection.name}? Managed images will be kept.`)) return;
        await request(`/collections/${detail.collection.id}`, { method: "DELETE" });
        state.collectionId = "";
        state.selectedImages.clear();
        await refresh();
      }), "danger"),
    );
    section.append(editRow);

    const importRow = element("div", undefined, "arch-ref-row");
    const fileInput = element("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = "image/png,image/jpeg,image/webp,image/bmp,image/tiff,image/gif";
    const upload = button("Import images", safe(status, async () => {
      if (!fileInput.files?.length) throw new Error("choose at least one image");
      const form = new FormData();
      for (const file of fileInput.files) form.append("files", file, file.name);
      await request(`/import/${detail.collection.id}`, { method: "POST", body: form });
      fileInput.value = "";
      await refresh();
    }));
    importRow.append(fileInput, upload);
    section.append(importRow);
  }
  parent.append(section);
}

function filterMode(filters, tagId) {
  if (filters.include_all.includes(tagId)) return "all";
  if (filters.include_any.includes(tagId)) return "any";
  if (filters.exclude.includes(tagId)) return "exclude";
  return "off";
}

function filtersWithMode(filters, tagId, mode) {
  const next = normalizeFilters(filters);
  for (const key of Object.keys(next)) next[key] = next[key].filter((id) => id !== tagId);
  if (mode === "all") next.include_all.push(tagId);
  if (mode === "any") next.include_any.push(tagId);
  if (mode === "exclude") next.exclude.push(tagId);
  return next;
}

function renderTagsAndFilters(parent, state, status, refresh) {
  const detail = selectedDetail(state);
  if (!detail) return;
  const section = element("section", undefined, "arch-ref-section");
  section.append(element("h3", "Tags and smart filters"));
  const addRow = element("div", undefined, "arch-ref-row");
  const tagName = textInput("", "tag name");
  const tagGroup = textInput("", "group, e.g. framing");
  addRow.append(tagName, tagGroup, button("Add tag", safe(status, async () => {
    await request("/tags", { method: "POST", body: { name: tagName.value, group_name: tagGroup.value } });
    await refresh();
  })));
  section.append(addRow);

  const filters = normalizeFilters(detail.selection.filters);
  const vocabulary = element("div", undefined, "arch-ref-tag-list");
  for (const tag of state.data.tags ?? []) {
    const row = element("div", undefined, "arch-ref-tag-row");
    const name = textInput(tag.name);
    const group = textInput(tag.group_name, "group");
    const mode = selectInput([
      { value: "off", label: "not filtered" },
      { value: "all", label: "must have" },
      { value: "any", label: "may have" },
      { value: "exclude", label: "exclude" },
    ], filterMode(filters, tag.id));
    mode.addEventListener("change", safe(status, async () => {
      await request(`/selections/${detail.collection.id}`, { method: "PUT", body: { filters: filtersWithMode(filters, tag.id, mode.value) } });
      await refresh();
    }));
    row.append(
      name,
      group,
      mode,
      button("Save tag", safe(status, async () => {
        await request(`/tags/${tag.id}`, { method: "PATCH", body: { name: name.value, group_name: group.value } });
        await refresh();
      })),
      button("Delete tag", safe(status, async () => {
        if (globalThis.confirm && !globalThis.confirm(`Delete tag ${tag.name}?`)) return;
        await request(`/tags/${tag.id}`, { method: "DELETE" });
        await refresh();
      }), "danger"),
    );
    vocabulary.append(row);
  }
  section.append(vocabulary);
  parent.append(section);
}

function renderLockedSelection(parent, state, status, refresh) {
  const detail = selectedDetail(state);
  if (!detail) return;
  const section = element("section", undefined, "arch-ref-section");
  section.append(element("h3", "Locked references"));
  const slots = element("div", undefined, "arch-ref-slots");
  const images = new Map(detail.images.map((image) => [image.id, image]));
  for (const slot of detail.selection.slots) {
    const card = element("article", undefined, "arch-ref-slot");
    card.append(element("strong", `Slot ${slot.slot}${slot.pinned ? " · pinned" : " · automatic"}`));
    if (slot.image_id) {
      const image = element("img");
      image.src = `${ROOT}/images/${encodeURIComponent(slot.image_id)}/thumbnail`;
      image.alt = images.get(slot.image_id)?.original_filename || `Reference slot ${slot.slot}`;
      card.append(image, button("Unpin", safe(status, async () => {
        const next = detail.selection.slots.map((item) => item.slot === slot.slot ? { ...item, pinned: false } : item);
        await request(`/selections/${detail.collection.id}`, { method: "PUT", body: { slots: next } });
        await refresh();
      })));
    } else {
      card.append(element("span", "Empty"));
    }
    slots.append(card);
  }
  section.append(slots);
  const controls = element("div", undefined, "arch-ref-row");
  const policy = selectInput(["random", "seeded", "sequential"].map((value) => ({ value, label: value })), detail.selection.policy);
  const seed = element("input");
  seed.type = "number";
  seed.min = "0";
  seed.step = "1";
  seed.value = String(detail.selection.seed);
  controls.append(
    labeled("Policy", policy),
    labeled("Seed", seed),
    button("Reroll references", safe(status, async () => {
      await request(`/selections/${detail.collection.id}`, { method: "PUT", body: { policy: policy.value, seed: Number(seed.value) } });
      await request(`/selections/${detail.collection.id}/reroll`, { method: "POST", body: {} });
      await refresh();
    })),
  );
  section.append(controls);
  parent.append(section);
}

function renderGallery(parent, state, status, refresh) {
  const detail = selectedDetail(state);
  if (!detail) return;
  const section = element("section", undefined, "arch-ref-section");
  section.append(element("h3", `Filtered images (${detail.images.length})`));
  const batch = element("div", undefined, "arch-ref-row");
  const tagSelect = selectInput([{ value: "", label: "Choose tag" }, ...(state.data.tags ?? []).map((tag) => ({ value: tag.id, label: `${tag.group_name ? `${tag.group_name}: ` : ""}${tag.name}` }))]);
  batch.append(
    tagSelect,
    button("Apply tag", safe(status, async () => {
      await request("/membership-tags", { method: "PATCH", body: batchTagPayload(detail.collection.id, [...state.selectedImages], tagSelect.value, "add") });
      await refresh();
    })),
    button("Remove tag", safe(status, async () => {
      await request("/membership-tags", { method: "PATCH", body: batchTagPayload(detail.collection.id, [...state.selectedImages], tagSelect.value, "remove") });
      await refresh();
    })),
  );
  section.append(batch);
  const gallery = element("div", undefined, "arch-ref-gallery");
  for (const record of detail.images) {
    const card = element("article", undefined, "arch-ref-card");
    const image = element("img");
    image.src = `${ROOT}/images/${encodeURIComponent(record.id)}/thumbnail`;
    image.alt = record.original_filename;
    const select = element("input");
    select.type = "checkbox";
    select.checked = state.selectedImages.has(record.id);
    select.setAttribute("aria-label", `Select ${record.original_filename}`);
    select.addEventListener("change", () => select.checked ? state.selectedImages.add(record.id) : state.selectedImages.delete(record.id));
    const tags = element("small", record.tags.map((tag) => tag.name).join(", ") || "untagged");
    const pinControls = element("div", undefined, "arch-ref-pin-row");
    for (let slot = 1; slot <= 4; slot += 1) {
      pinControls.append(button(`Pin ${slot}`, safe(status, async () => {
        await request(`/selections/${detail.collection.id}`, { method: "PUT", body: { slots: pinSlot(detail.selection.slots, slot, record.id) } });
        await refresh();
      })));
    }
    card.append(
      image,
      select,
      element("strong", record.original_filename),
      tags,
      pinControls,
      button("Remove from collection", safe(status, async () => {
        if (globalThis.confirm && !globalThis.confirm(`Remove ${record.original_filename} from this collection?`)) return;
        await request(`/collections/${detail.collection.id}/images/${record.id}`, { method: "DELETE" });
        state.selectedImages.delete(record.id);
        await refresh();
      }), "danger"),
    );
    gallery.append(card);
  }
  section.append(gallery);
  parent.append(section);
}

function normalizeLoraDraft(item) {
  return {
    name: item.name,
    strength_model: Number(item.strength_model),
    strength_clip: Number(item.strength_clip),
    enabled: Boolean(item.enabled),
  };
}

function renderProfiles(parent, state, status, refresh) {
  const detail = selectedDetail(state);
  if (!detail) return;
  const section = element("section", undefined, "arch-ref-section");
  section.append(element("h3", "Prompt and LoRA profiles"));
  const chooser = selectInput(detail.profiles.map((profile) => ({ value: profile.id, label: `${profile.name} · ${profile.model_family}` })), detail.active_profile.id);
  chooser.addEventListener("change", safe(status, async () => {
    await request(`/active/${state.kind}`, { method: "PUT", body: { collection_id: detail.collection.id, profile_id: chooser.value } });
    await refresh();
  }));
  section.append(labeled("Active profile", chooser));

  const createRow = element("div", undefined, "arch-ref-row");
  const newName = textInput("", "profile name");
  const newFamily = textInput("default", "model family");
  createRow.append(newName, newFamily, button("Add profile", safe(status, async () => {
    const created = await request("/profiles", { method: "POST", body: { collection_id: detail.collection.id, name: newName.value, model_family: newFamily.value, positive_prompt: "", negative_prompt: "", loras: [] } });
    await request(`/active/${state.kind}`, { method: "PUT", body: { collection_id: detail.collection.id, profile_id: created.profile.id } });
    await refresh();
  })));
  section.append(createRow);

  const profile = detail.active_profile;
  const name = textInput(profile.name);
  name.disabled = profile.name.toLowerCase() === "default";
  const family = textInput(profile.model_family);
  const positive = element("textarea");
  positive.value = profile.positive_prompt;
  positive.rows = 3;
  const negative = element("textarea");
  negative.value = profile.negative_prompt;
  negative.rows = 3;
  section.append(labeled("Profile name", name), labeled("Model family", family), labeled("Positive prompt addition", positive), labeled("Negative prompt addition", negative));

  const loraRows = element("div", undefined, "arch-ref-loras");
  let draft = profile.loras.map(normalizeLoraDraft);
  const drawLoras = () => {
    loraRows.replaceChildren();
    draft.forEach((item, index) => {
      const row = element("div", undefined, "arch-ref-lora-row");
      const enabled = element("input");
      enabled.type = "checkbox";
      enabled.checked = item.enabled;
      enabled.addEventListener("change", () => { item.enabled = enabled.checked; });
      const modelStrength = element("input");
      modelStrength.type = "number";
      modelStrength.step = "0.01";
      modelStrength.value = String(item.strength_model);
      modelStrength.addEventListener("change", () => { item.strength_model = Number(modelStrength.value); });
      const clipStrength = element("input");
      clipStrength.type = "number";
      clipStrength.step = "0.01";
      clipStrength.value = String(item.strength_clip);
      clipStrength.addEventListener("change", () => { item.strength_clip = Number(clipStrength.value); });
      row.append(
        enabled,
        element("span", item.name),
        labeled("Model", modelStrength),
        labeled("CLIP", clipStrength),
        button("↑", () => { if (index > 0) { [draft[index - 1], draft[index]] = [draft[index], draft[index - 1]]; drawLoras(); } }),
        button("↓", () => { if (index < draft.length - 1) { [draft[index + 1], draft[index]] = [draft[index], draft[index + 1]]; drawLoras(); } }),
        button("Remove", () => { draft.splice(index, 1); drawLoras(); }, "danger"),
      );
      loraRows.append(row);
    });
  };
  drawLoras();
  section.append(loraRows);
  const addLoraRow = element("div", undefined, "arch-ref-row");
  const loraSelect = selectInput([{ value: "", label: "Choose local LoRA" }, ...(state.data.loras ?? []).map((value) => ({ value, label: value }))]);
  addLoraRow.append(loraSelect, button("Add LoRA", () => {
    if (!loraSelect.value || draft.some((item) => item.name === loraSelect.value)) return;
    draft.push({ name: loraSelect.value, strength_model: 1, strength_clip: 1, enabled: true });
    drawLoras();
  }));
  section.append(addLoraRow);
  const actions = element("div", undefined, "arch-ref-row");
  actions.append(
    button("Save profile", safe(status, async () => {
      await request(`/profiles/${profile.id}`, { method: "PATCH", body: { name: name.value, model_family: family.value, positive_prompt: positive.value, negative_prompt: negative.value, loras: draft.map(normalizeLoraDraft) } });
      await refresh();
    })),
  );
  if (profile.name.toLowerCase() !== "default") {
    actions.append(button("Delete profile", safe(status, async () => {
      if (globalThis.confirm && !globalThis.confirm(`Delete profile ${profile.name}?`)) return;
      await request(`/profiles/${profile.id}`, { method: "DELETE" });
      await refresh();
    }), "danger"));
  }
  section.append(actions);
  parent.append(section);
}

function renderOrphans(parent, state, status, refresh) {
  const orphans = state.data?.orphans ?? [];
  if (!orphans.length) return;
  const section = element("section", undefined, "arch-ref-section");
  section.append(
    element("h3", "Unassigned managed images"),
    element("p", "These local copies no longer belong to a collection. Permanent deletion cannot be undone."),
  );
  const gallery = element("div", undefined, "arch-ref-gallery");
  for (const record of orphans) {
    const card = element("article", undefined, "arch-ref-card");
    const image = element("img");
    image.src = `${ROOT}/images/${encodeURIComponent(record.id)}/thumbnail`;
    image.alt = record.original_filename;
    card.append(
      image,
      element("strong", record.original_filename),
      button("Permanently delete", safe(status, async () => {
        if (globalThis.confirm && !globalThis.confirm(`Permanently delete the managed copy of ${record.original_filename}?`)) return;
        await request(`/images/${record.id}`, { method: "DELETE", body: { confirmation: "DELETE" } });
        await refresh();
      }), "danger"),
    );
    gallery.append(card);
  }
  section.append(gallery);
  parent.append(section);
}

function renderPanel(container) {
  installCss();
  const state = { kind: "subject", collectionId: "", data: null, selectedImages: new Set() };
  const status = element("p", "Loading…", "arch-ref-status");
  status.setAttribute("aria-live", "polite");

  const refresh = async () => {
    const query = new URLSearchParams({ kind: state.kind });
    if (state.collectionId) query.set("collection_id", state.collectionId);
    state.data = await request(`/bootstrap?${query}`);
    const available = new Set((state.data.detail?.images ?? []).map((item) => item.id));
    state.selectedImages = new Set([...state.selectedImages].filter((id) => available.has(id)));
    draw();
  };

  const draw = () => {
    const root = element("div", undefined, "arch-ref-library");
    root.append(element("h2", "Reference Library"));
    const tabs = element("div", undefined, "arch-ref-tabs");
    for (const kind of ["subject", "environment"]) {
      const tab = button(kind === "subject" ? "Subjects / Characters" : "Environments / Locations", safe(status, async () => {
        state.kind = kind;
        state.collectionId = "";
        state.selectedImages.clear();
        await refresh();
      }), state.kind === kind ? "active" : "");
      tabs.append(tab);
    }
    root.append(tabs, status);
    renderCollectionControls(root, state, status, refresh);
    renderTagsAndFilters(root, state, status, refresh);
    renderLockedSelection(root, state, status, refresh);
    renderGallery(root, state, status, refresh);
    renderProfiles(root, state, status, refresh);
    renderOrphans(root, state, status, refresh);
    container.replaceChildren(root);
  };

  safe(status, refresh)();
}

function findWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function setWidget(node, name, value) {
  const widget = findWidget(node, name);
  if (!widget) return;
  widget.value = value;
  widget.callback?.(value, app.canvas, node);
  node.setDirtyCanvas?.(true, true);
}

async function nodePreview(node, kind) {
  if (!node._archReferenceLibraryPreview) return;
  const mode = findWidget(node, "selection_mode")?.value || "follow_sidebar";
  const collectionId = findWidget(node, "collection_id")?.value || "";
  const query = new URLSearchParams({ kind });
  if (mode === "pinned" && collectionId) query.set("collection_id", collectionId);
  const data = await request(`/bootstrap?${query}`);
  const container = node._archReferenceLibraryPreview;
  container.replaceChildren();
  if (!data.detail) {
    container.append(element("small", `No active ${kind}. Open Reference Library.`));
    return;
  }
  container.append(element("strong", `${data.detail.collection.name} · ${data.detail.active_profile.name}`));
  const row = element("div", undefined, "arch-ref-node-images");
  for (const slot of data.detail.selection.slots) {
    if (!slot.image_id) continue;
    const image = element("img");
    image.src = `${ROOT}/images/${encodeURIComponent(slot.image_id)}/thumbnail`;
    image.alt = `Reference ${slot.slot}`;
    row.append(image);
  }
  container.append(row);
}

function scheduleNodePreview(node, kind) {
  clearTimeout(node._archReferenceLibraryTimer);
  node._archReferenceLibraryTimer = setTimeout(() => nodePreview(node, kind).catch((error) => {
    node._archReferenceLibraryPreview?.replaceChildren(element("small", `Error: ${String(error.message || error)}`));
  }), 150);
}

function enhanceSelector(nodeType, kind) {
  const created = nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated = function () {
    const result = created?.apply(this, arguments);
    const node = this;
    const transientButton = (label, action) => {
      const widget = node.addWidget("button", label, null, action);
      widget.serialize = false;
      widget.serializeValue = () => undefined;
      return widget;
    };
    transientButton("Pin current sidebar selection", async () => {
      const data = await request(`/bootstrap?${new URLSearchParams({ kind })}`);
      if (!data.detail) return;
      setWidget(node, "selection_mode", "pinned");
      setWidget(node, "collection_id", data.detail.collection.id);
      setWidget(node, "profile_id", data.detail.active_profile.id);
      scheduleNodePreview(node, kind);
    });
    transientButton("Use sidebar selection", () => {
      setWidget(node, "selection_mode", "follow_sidebar");
      setWidget(node, "collection_id", "");
      setWidget(node, "profile_id", "");
      scheduleNodePreview(node, kind);
    });
    transientButton("Open Reference Library", () => {
      if (app.extensionManager?.sidebarTab) app.extensionManager.sidebarTab.activeSidebarTabId = SIDEBAR_ID;
      app.extensionManager?.setSidebarTab?.(SIDEBAR_ID);
    });
    if (node.addDOMWidget) {
      const preview = element("div", undefined, "arch-ref-node-preview");
      node._archReferenceLibraryPreview = preview;
      const widget = node.addDOMWidget("reference_library_preview", "div", preview, { serialize: false, getMinHeight: () => 82, getMaxHeight: () => 120, getValue: () => "", setValue: () => {} });
      if (widget) { widget.serialize = false; widget.serializeValue = () => undefined; }
    }
    for (const name of ["selection_mode", "collection_id", "profile_id"]) {
      const widget = findWidget(node, name);
      if (!widget || widget._archReferenceLibraryWrapped) continue;
      widget._archReferenceLibraryWrapped = true;
      const callback = widget.callback;
      widget.callback = function () {
        const callbackResult = callback?.apply(this, arguments);
        scheduleNodePreview(node, kind);
        return callbackResult;
      };
    }
    scheduleNodePreview(node, kind);
    return result;
  };
}

installCss();
app.registerExtension({
  name: "arch.reference-library",
  setup() { installCss(); },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const kind = SELECTOR_KINDS[nodeData.name];
    if (kind) enhanceSelector(nodeType, kind);
  },
});
app.extensionManager.registerSidebarTab({
  id: SIDEBAR_ID,
  icon: "pi pi-images",
  title: "Reference Library",
  type: "custom",
  render: renderPanel,
});

const seam = { normalizeFilters, batchTagPayload, pinSlot, responseJson, renderPanel };
globalThis.__archReferenceLibrary = seam;
export { normalizeFilters, batchTagPayload, pinSlot, responseJson, renderPanel };
