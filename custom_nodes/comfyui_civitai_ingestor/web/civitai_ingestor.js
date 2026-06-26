import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const APP_ID = "civitai-ingestor-app";
const DEFAULT_COLLECTION = "https://civitai.red/collections/8081491";

function notify(summary, severity = "info") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary, life: 3200 });
    } else {
        console.log(`[Civitai Ingestor] ${summary}`);
    }
}

function createButton() {
    if (document.getElementById(`${APP_ID}-button`)) {
        return;
    }
    const button = document.createElement("button");
    button.id = `${APP_ID}-button`;
    button.textContent = "Civitai Ingestor";
    button.style.cssText = [
        "position:fixed",
        "right:16px",
        "bottom:56px",
        "z-index:9999",
        "padding:8px 10px",
        "border:1px solid #555",
        "border-radius:6px",
        "background:#172033",
        "color:#f9fafb",
        "font:12px system-ui",
        "cursor:pointer",
    ].join(";");
    button.addEventListener("click", openPanel);
    document.body.appendChild(button);
}

function panelHtml() {
    return `
        <div class="ci-card">
            <div class="ci-head">
                <strong>Civitai Collection Ingestor</strong>
                <button type="button" data-ci-close>Close</button>
            </div>
            <div class="ci-controls">
                <input data-ci-url value="${DEFAULT_COLLECTION}" spellcheck="false" />
                <input data-ci-token type="password" placeholder="Civitai token (optional)" autocomplete="off" />
                <input data-ci-max type="number" min="1" max="500" value="50" title="Max images" />
                <button type="button" data-ci-ingest>Ingest</button>
                <button type="button" data-ci-refresh>Refresh local</button>
                <button type="button" data-ci-cache-images>Cache images</button>
                <button type="button" data-ci-download>Download missing</button>
            </div>
            <div class="ci-status" data-ci-status>Ready</div>
            <div class="ci-filter">
                <input data-ci-search type="search" placeholder="Search images, prompts, models, files, status" autocomplete="off" spellcheck="false" />
                <button type="button" data-ci-clear-search>Clear</button>
                <span data-ci-filter-status class="ci-muted"></span>
            </div>
            <div class="ci-summary" data-ci-summary></div>
            <div class="ci-grid">
                <div class="ci-pane">
                    <h3>Images</h3>
                    <div data-ci-images class="ci-list"></div>
                </div>
                <div class="ci-pane">
                    <h3>Resources</h3>
                    <div data-ci-resources class="ci-list"></div>
                </div>
            </div>
        </div>
    `;
}

function ensurePanel() {
    let panel = document.getElementById(APP_ID);
    if (panel) {
        return panel;
    }
    panel = document.createElement("div");
    panel.id = APP_ID;
    panel.innerHTML = panelHtml();
    panel.style.cssText = [
        "position:fixed",
        "inset:0",
        "z-index:10000",
        "display:none",
        "background:rgba(0,0,0,.55)",
        "align-items:center",
        "justify-content:center",
    ].join(";");
    const style = document.createElement("style");
    style.textContent = `
        #${APP_ID} .ci-card { width:min(1180px, calc(100vw - 28px)); height:min(820px, calc(100vh - 28px)); display:flex; flex-direction:column; gap:10px; padding:12px; border:1px solid #3f3f46; border-radius:8px; background:#0f172a; color:#f8fafc; font:13px system-ui; box-shadow:0 18px 70px rgba(0,0,0,.45); }
        #${APP_ID} .ci-head { display:flex; justify-content:space-between; align-items:center; gap:8px; }
        #${APP_ID} .ci-controls { display:grid; grid-template-columns:minmax(260px, 1fr) minmax(180px, .45fr) 90px repeat(4, auto); gap:8px; }
        #${APP_ID} button, #${APP_ID} input { border:1px solid #475569; border-radius:6px; background:#111827; color:#f8fafc; font:13px system-ui; }
        #${APP_ID} button { padding:7px 10px; cursor:pointer; white-space:nowrap; }
        #${APP_ID} button:disabled { opacity:.45; cursor:not-allowed; }
        #${APP_ID} input { padding:7px 8px; min-width:0; }
        #${APP_ID} .ci-status { min-height:20px; color:#cbd5e1; }
        #${APP_ID} .ci-filter { display:grid; grid-template-columns:minmax(220px, 1fr) auto auto; align-items:center; gap:8px; }
        #${APP_ID} .ci-summary { display:flex; flex-wrap:wrap; gap:8px; color:#d1d5db; }
        #${APP_ID} .ci-chip { border:1px solid #334155; border-radius:6px; padding:4px 7px; background:#111827; }
        #${APP_ID} .ci-grid { flex:1; min-height:0; display:grid; grid-template-columns:1fr 1fr; gap:10px; }
        #${APP_ID} .ci-pane { min-height:0; display:flex; flex-direction:column; gap:8px; border:1px solid #334155; border-radius:8px; padding:8px; }
        #${APP_ID} h3 { margin:0; font-size:13px; font-weight:700; }
        #${APP_ID} .ci-list { min-height:0; overflow:auto; display:flex; flex-direction:column; gap:8px; }
        #${APP_ID} .ci-row { display:grid; grid-template-columns:76px 1fr; gap:8px; border:1px solid #334155; border-radius:8px; padding:7px; background:#111827; }
        #${APP_ID} .ci-row img { width:76px; height:96px; object-fit:cover; border-radius:6px; background:#020617; }
        #${APP_ID} .ci-title { font-weight:700; overflow-wrap:anywhere; }
        #${APP_ID} .ci-muted { color:#94a3b8; font-size:12px; overflow-wrap:anywhere; }
        #${APP_ID} .ci-resource { display:grid; grid-template-columns:1fr auto; gap:8px; border:1px solid #334155; border-radius:8px; padding:7px; background:#111827; }
        #${APP_ID} .ci-actions { display:flex; flex-wrap:wrap; gap:6px; margin-top:7px; }
        #${APP_ID} .ci-actions button { padding:5px 8px; font-size:12px; }
        #${APP_ID} .ci-empty { border:1px dashed #334155; border-radius:8px; padding:14px; color:#94a3b8; background:#0b1220; }
        #${APP_ID} .ci-ok { color:#86efac; }
        #${APP_ID} .ci-warn { color:#facc15; }
        #${APP_ID} .ci-bad { color:#fca5a5; }
        @media (max-width: 840px) {
            #${APP_ID} .ci-controls, #${APP_ID} .ci-filter, #${APP_ID} .ci-grid { grid-template-columns:1fr; }
        }
    `;
    document.head.appendChild(style);
    document.body.appendChild(panel);
    wirePanel(panel);
    return panel;
}

function setStatus(panel, text) {
    panel.querySelector("[data-ci-status]").textContent = text;
}

function collectionIdFromUrl(url) {
    const match = String(url || "").match(/collections\/(\d+)/);
    return match ? Number(match[1]) : Number(url);
}

async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || response.statusText);
    }
    return data;
}

async function ingest(panel) {
    const url = panel.querySelector("[data-ci-url]").value;
    const token = panel.querySelector("[data-ci-token]").value;
    const maxItems = Number(panel.querySelector("[data-ci-max]").value || 50);
    setStatus(panel, "Ingesting collection...");
    const response = await api.fetchApi("/civitai-ingestor/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, token, max_items: maxItems }),
    });
    const data = await readJson(response);
    panel._civitaiIngestorCollectionId = data.ingest?.collection_id || collectionIdFromUrl(url);
    render(panel, data);
    setStatus(panel, `Ingested ${data.summary?.images || 0} images.`);
}

async function loadCollection(panel) {
    const collectionId = panel._civitaiIngestorCollectionId || collectionIdFromUrl(panel.querySelector("[data-ci-url]").value);
    if (!collectionId) {
        return;
    }
    panel._civitaiIngestorCollectionId = collectionId;
    setStatus(panel, "Loading saved collection...");
    const response = await api.fetchApi(`/civitai-ingestor/collections/${collectionId}`, { cache: "no-store" });
    const data = await readJson(response);
    if (!data.collection) {
        setStatus(panel, "No saved collection found. Ingest a collection first.");
        return;
    }
    render(panel, data);
    setStatus(panel, `Loaded ${data.summary?.images || 0} images.`);
}

async function refreshLocal(panel) {
    const collectionId = panel._civitaiIngestorCollectionId || collectionIdFromUrl(panel.querySelector("[data-ci-url]").value);
    if (!collectionId) {
        notify("No collection loaded.", "error");
        return;
    }
    setStatus(panel, "Refreshing local model status...");
    const response = await api.fetchApi("/civitai-ingestor/local/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ collection_id: collectionId }),
    });
    const data = await readJson(response);
    render(panel, data);
    setStatus(panel, "Local status refreshed.");
}

async function cacheImages(panel) {
    const collectionId = panel._civitaiIngestorCollectionId || collectionIdFromUrl(panel.querySelector("[data-ci-url]").value);
    if (!collectionId) {
        notify("No collection loaded.", "error");
        return;
    }
    const token = panel.querySelector("[data-ci-token]").value;
    setStatus(panel, "Caching images locally...");
    const response = await api.fetchApi("/civitai-ingestor/images/cache", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ collection_id: collectionId, token }),
    });
    const data = await readJson(response);
    render(panel, data);
    const counts = data.image_cache || {};
    setStatus(panel, `Image cache complete: ${counts.cached || 0} cached, ${counts.skipped || 0} skipped, ${counts.failed || 0} failed.`);
}

async function downloadMissing(panel) {
    const data = panel._civitaiIngestorData;
    const fileIds = (data?.resources || [])
        .filter((item) => item.local_status === "missing")
        .map((item) => item.file_id);
    if (!fileIds.length) {
        notify("No missing files to download.");
        return;
    }
    const token = panel.querySelector("[data-ci-token]").value;
    const response = await api.fetchApi("/civitai-ingestor/downloads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_ids: fileIds, token }),
    });
    const job = await readJson(response);
    panel._civitaiIngestorJobId = job.id;
    renderJobStatus(panel, job);
    pollJob(panel, job.id);
}

async function saveDraft(panel, imageId, queue = false) {
    setStatus(panel, queue ? `Preparing workflow draft for image ${imageId}...` : `Saving workflow draft for image ${imageId}...`);
    const response = await api.fetchApi("/civitai-ingestor/workflows/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_id: imageId, save: true, readonly: true }),
    });
    const draft = await readJson(response);
    const warnings = (draft.warnings || []).join(" ");
    if (!queue) {
        setStatus(panel, `Draft saved: ${draft.saved_path || "not saved"}${warnings ? ` (${warnings})` : ""}`);
        return draft;
    }
    if (!draft.runnable || !draft.api_prompt) {
        setStatus(panel, `Draft saved but not runnable: ${warnings || "missing required metadata or models."}`);
        notify("Draft is not runnable yet.", "warn");
        return draft;
    }
    const queued = await queueApiPrompt(draft.api_prompt);
    setStatus(panel, `Queued workflow draft ${queued.prompt_id || ""} for image ${imageId}.`);
    return draft;
}

async function queueApiPrompt(prompt) {
    const response = await api.fetchApi("/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
    });
    return readJson(response);
}

async function pollJob(panel, jobId) {
    const response = await api.fetchApi(`/civitai-ingestor/downloads/${jobId}`, { cache: "no-store" });
    const job = await readJson(response);
    renderJobStatus(panel, job);
    if (["queued", "running"].includes(job.status)) {
        setTimeout(() => pollJob(panel, jobId).catch((error) => setStatus(panel, error.message)), 1200);
    } else if (panel._civitaiIngestorCollectionId) {
        await refreshLocal(panel);
    }
}

function renderJobStatus(panel, job) {
    const current = (job.items || []).find((item) => item.status === "running") || (job.items || [])[0];
    const suffix = current ? `: ${current.file_name} ${formatBytes(current.downloaded_bytes)} / ${formatBytes(current.total_bytes)}` : "";
    setStatus(panel, `Download ${job.status}${suffix}`);
}

function render(panel, data) {
    panel._civitaiIngestorData = data;
    const summary = data.summary || {};
    panel.querySelector("[data-ci-summary]").innerHTML = [
        ["Images", summary.images || 0],
        ["With metadata", summary.images_with_meta || 0],
        ["Files", summary.resource_files || 0],
        ["Present", summary.present_files || 0],
        ["Missing", summary.missing_files || 0],
    ].map(([label, value]) => `<span class="ci-chip">${label}: ${value}</span>`).join("");
    applyFilters(panel);
}

function renderImages(panel, images) {
    const container = panel.querySelector("[data-ci-images]");
    if (!images.length) {
        container.innerHTML = `<div class="ci-empty">No matching images.</div>`;
        return;
    }
    container.innerHTML = images.map((image) => {
        const prompt = escapeHtml(image.prompt || "No prompt metadata");
        const metaClass = image.has_meta ? "ci-ok" : "ci-warn";
        const imageSrc = image.local_image_status === "cached"
            ? `/civitai-ingestor/images/${image.image_id}/cached?ts=${encodeURIComponent(image.local_image_cached_at || "")}`
            : image.url || "";
        const cacheClass = image.local_image_status === "cached" ? "ci-ok" : image.local_image_status === "failed" ? "ci-bad" : "ci-muted";
        const cacheLabel = image.local_image_status === "cached" ? "cached image" : image.local_image_status === "failed" ? "cache failed" : "remote image";
        return `
            <div class="ci-row">
                <img src="${escapeAttr(imageSrc)}" alt="" loading="lazy" />
                <div>
                    <div class="ci-title">#${image.image_id} ${escapeHtml(image.username || "")}</div>
                    <div class="ci-muted">${escapeHtml(image.base_model || "")} ${image.width || ""}x${image.height || ""}</div>
                    <div class="${metaClass}">${image.has_meta ? "metadata" : "no metadata"}</div>
                    <div class="${cacheClass}">${cacheLabel}</div>
                    <div class="ci-muted">${prompt.slice(0, 320)}</div>
                    <div class="ci-actions">
                        <button type="button" data-ci-draft="${image.image_id}">Save draft</button>
                        <button type="button" data-ci-queue="${image.image_id}" ${image.has_meta ? "" : "disabled"}>Queue draft</button>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}

function renderResources(panel, resources) {
    const container = panel.querySelector("[data-ci-resources]");
    if (!resources.length) {
        container.innerHTML = `<div class="ci-empty">No matching resources.</div>`;
        return;
    }
    container.innerHTML = resources.map((item) => {
        const statusClass = item.local_status === "missing" ? "ci-bad" : item.local_status === "present_elsewhere" ? "ci-warn" : "ci-ok";
        const trained = (item.trained_words || []).join(", ");
        return `
            <div class="ci-resource">
                <div>
                    <div class="ci-title">${escapeHtml(item.model_name || "")} - ${escapeHtml(item.version_name || "")}</div>
                    <div class="ci-muted">${escapeHtml(item.file_name || "")}</div>
                    <div class="ci-muted">${escapeHtml(item.model_type || "")} -> ${escapeHtml(item.target_folder || "")} · ${formatBytes((item.size_kb || 0) * 1024)}</div>
                    ${trained ? `<div class="ci-muted">Triggers: ${escapeHtml(trained)}</div>` : ""}
                    ${item.local_path ? `<div class="ci-muted">${escapeHtml(item.local_path)}</div>` : ""}
                </div>
                <div class="${statusClass}">${escapeHtml(item.local_status || "unknown")}</div>
            </div>
        `;
    }).join("");
}

function applyFilters(panel) {
    const data = panel._civitaiIngestorData || {};
    const query = normalizeSearch(panel.querySelector("[data-ci-search]")?.value);
    const allImages = data.images || [];
    const allResources = data.resources || [];
    const images = query
        ? allImages.filter((image) => imageSearchText(image).includes(query))
        : allImages;
    const resources = query
        ? allResources.filter((resource) => resourceSearchText(resource).includes(query))
        : allResources;

    renderImages(panel, images);
    renderResources(panel, resources);
    renderFilterStatus(panel, images.length, allImages.length, resources.length, allResources.length, query);
}

function renderFilterStatus(panel, imageCount, totalImages, resourceCount, totalResources, query) {
    const node = panel.querySelector("[data-ci-filter-status]");
    if (!node) {
        return;
    }
    node.textContent = query
        ? `Showing ${imageCount}/${totalImages} images and ${resourceCount}/${totalResources} resources`
        : `${totalImages} images and ${totalResources} resources`;
}

function imageSearchText(image) {
    return searchText([
        image.image_id,
        image.post_id,
        image.username,
        image.base_model,
        image.media_type,
        image.prompt,
        image.negative_prompt,
        image.seed,
        image.steps,
        image.sampler,
        image.cfg_scale,
        image.width,
        image.height,
        image.local_image_status,
    ]);
}

function resourceSearchText(resource) {
    return searchText([
        resource.file_id,
        resource.model_version_id,
        resource.model_name,
        resource.version_name,
        resource.file_name,
        resource.file_type,
        resource.model_type,
        resource.base_model,
        resource.target_folder,
        resource.local_status,
        resource.local_path,
        resource.local_folder,
        resource.sha256,
        resource.auto_v2,
        resource.trained_words || [],
    ]);
}

function searchText(values) {
    return normalizeSearch(values.flatMap((value) => Array.isArray(value) ? value : [value]).join(" "));
}

function normalizeSearch(value) {
    return String(value ?? "").trim().toLowerCase();
}

function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes > 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
    if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    if (bytes > 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    }[char]));
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
}

function wirePanel(panel) {
    panel.querySelector("[data-ci-close]").addEventListener("click", () => {
        panel.style.display = "none";
    });
    panel.querySelector("[data-ci-ingest]").addEventListener("click", () => ingest(panel).catch((error) => {
        setStatus(panel, error.message);
        notify(error.message, "error");
    }));
    panel.querySelector("[data-ci-refresh]").addEventListener("click", () => refreshLocal(panel).catch((error) => {
        setStatus(panel, error.message);
        notify(error.message, "error");
    }));
    panel.querySelector("[data-ci-cache-images]").addEventListener("click", () => cacheImages(panel).catch((error) => {
        setStatus(panel, error.message);
        notify(error.message, "error");
    }));
    panel.querySelector("[data-ci-download]").addEventListener("click", () => downloadMissing(panel).catch((error) => {
        setStatus(panel, error.message);
        notify(error.message, "error");
    }));
    panel.querySelector("[data-ci-search]").addEventListener("input", () => applyFilters(panel));
    panel.querySelector("[data-ci-clear-search]").addEventListener("click", () => {
        const search = panel.querySelector("[data-ci-search]");
        search.value = "";
        applyFilters(panel);
        search.focus();
    });
    panel.querySelector("[data-ci-images]").addEventListener("click", (event) => {
        const draftButton = event.target.closest("[data-ci-draft]");
        const queueButton = event.target.closest("[data-ci-queue]");
        if (draftButton) {
            saveDraft(panel, Number(draftButton.dataset.ciDraft), false).catch((error) => {
                setStatus(panel, error.message);
                notify(error.message, "error");
            });
        } else if (queueButton) {
            saveDraft(panel, Number(queueButton.dataset.ciQueue), true).catch((error) => {
                setStatus(panel, error.message);
                notify(error.message, "error");
            });
        }
    });
}

function openPanel() {
    const panel = ensurePanel();
    panel.style.display = "flex";
    if (!panel._civitaiIngestorData && !panel._civitaiIngestorLoadedOnce) {
        panel._civitaiIngestorLoadedOnce = true;
        loadCollection(panel).catch((error) => {
            setStatus(panel, error.message);
            notify(error.message, "error");
        });
    }
}

app.registerExtension({
    name: "comfyui.civitai_ingestor",
    setup() {
        createButton();
        ensurePanel();
    },
});
