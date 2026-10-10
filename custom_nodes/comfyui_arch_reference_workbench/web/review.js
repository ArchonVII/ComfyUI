import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const ROOT = "/arch-reference-workbench/reviews";
async function request(path, options = {}) {
    const response = await api.fetchApi(path, {
        ...options,
        headers: { "Content-Type": "application/json", ...options.headers },
        ...(options.body ? { body: JSON.stringify(options.body) } : {}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
}
function element(tag, text) {
    const item = document.createElement(tag);
    if (text != null) item.textContent = text;
    return item;
}
function button(text, action) {
    const item = element("button", text);
    item.type = "button";
    item.onclick = action;
    return item;
}
function imageUrl(record, item) {
    return `${ROOT}/${encodeURIComponent(record.id)}/images/${encodeURIComponent(item.filename)}`;
}
function selectedPaths(record, selection) {
    if (selection === "all") return record.results.map(item => item.path);
    const index = Number(selection);
    if (!Number.isInteger(index) || index < 0 || index >= record.results.length) throw new Error("Select a valid result image");
    return [record.results[index].path];
}
async function saveToLibrary(record) {
    const dialog = element("dialog");
    dialog.style.cssText = "max-width:650px;width:85vw;padding:20px;color:var(--input-text);background:var(--comfy-menu-bg);";
    const title = element("h3", "Save result copies to Reference Library");
    const status = element("p", "Loading subject and environment collections…");
    const collection = element("select");
    collection.setAttribute("aria-label", "Destination collection");
    const selection = element("select");
    selection.setAttribute("aria-label", "Result images to save");
    const all = element("option", `All ${record.results.length} result images`);
    all.value = "all";
    selection.append(all);
    record.results.forEach((item, index) => {
        const option = element("option", `Result ${index + 1}: ${item.filename}`);
        option.value = String(index);
        selection.append(option);
    });
    const save = button("Save copies", async () => {
        save.disabled = true;
        try {
            if (!collection.value) throw new Error("Choose a destination collection");
            const paths = selectedPaths(record, selection.value);
            const result = await request(`/arch-reference-library/collections/${encodeURIComponent(collection.value)}/import-paths`, { method: "POST", body: { paths } });
            status.textContent = `Saved ${result.imports?.length || 0} of ${paths.length} images. ` + (result.failures || []).map(item => item.error).join("; ");
        } catch (error) { status.textContent = error.message; }
        finally { save.disabled = false; }
    });
    save.disabled = true;
    dialog.append(title, collection, selection, save, button("Close", () => dialog.close()), status);
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
    try {
        const data = await request("/arch-reference-library/bootstrap");
        (data.collections || []).filter(item => ["subject", "environment"].includes(item.kind)).forEach(item => {
            const option = element("option", `${item.kind}: ${item.name}`);
            option.value = item.id;
            collection.append(option);
        });
        save.disabled = collection.options.length === 0;
        status.textContent = save.disabled ? "Create a subject or environment collection in Reference Library first." : "Choose all results or one specific image. Originals remain unchanged.";
    } catch (error) { status.textContent = error.message; }
}
function showReview(record) {
    const dialog = element("dialog");
    dialog.style.cssText = "width:90vw;max-width:1200px;max-height:90vh;overflow:auto;padding:20px;color:var(--input-text);background:var(--comfy-menu-bg);";
    const status = element("p", `Classification: ${record.classification}`);
    const columns = element("div");
    columns.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:16px;";
    for (const [heading, items] of [["References", record.references], ["Results", record.results]]) {
        const column = element("section");
        column.append(element("h3", `${heading} (${items.length})`));
        items.forEach((item, index) => {
            const img = element("img");
            img.src = imageUrl(record, item);
            img.alt = `${heading} ${index + 1}`;
            img.loading = "lazy";
            img.style.cssText = "display:block;max-width:100%;max-height:400px;object-fit:contain;";
            column.append(element("p", `${index + 1}: ${item.filename}`), img);
        });
        columns.append(column);
    }
    const metadata = element("pre", JSON.stringify({ score_report: record.score_report, run_settings: record.run_settings }, null, 2));
    metadata.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere;";
    const controls = element("div");
    for (const classification of ["keep", "reject"]) {
        controls.append(button(classification === "keep" ? "Keep" : "Reject", async () => {
            try {
                const updated = await request(`${ROOT}/${encodeURIComponent(record.id)}/classification`, { method: "POST", body: { classification } });
                record.classification = updated.classification;
                status.textContent = `Classification: ${record.classification}. Image copies retained.`;
            } catch (error) { status.textContent = error.message; }
        }));
    }
    controls.append(button("Save to Library…", () => saveToLibrary(record)), button("Close", () => dialog.close()));
    dialog.append(element("h2", "Result Review"), status, controls, columns, metadata);
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
}
app.registerExtension({
    name: "Arch.ReferenceWorkbench.Review",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ArchResultReview") return;
        const previous = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function (...args) {
            const result = previous?.apply(this, args);
            this.addWidget("button", "Review results…", null, async () => {
                const id = this.properties?.arch_review_id;
                if (!id) return;
                try { showReview(await request(`${ROOT}/${encodeURIComponent(id)}`)); }
                catch (error) { app.extensionManager?.toast?.add({ severity: "error", summary: "Review unavailable", detail: error.message }); }
            }, { serialize: false });
            return result;
        };
        const executed = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = async function (message) {
            executed?.apply(this, arguments);
            const record = message.arch_review?.[0];
            if (!record) return;
            this.properties ||= {};
            this.properties.arch_review_id = record.id;
            try { showReview(await request(`${ROOT}/${encodeURIComponent(record.id)}`)); }
            catch (error) { app.extensionManager?.toast?.add({ severity: "error", summary: "Review unavailable", detail: error.message }); }
        };
    },
});
