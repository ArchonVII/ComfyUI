import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_CLASS = "CivitaiPromptMetadataImport";
const EXTENSION_NAME = "comfyui.civitai_prompt_import";

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function notify(summary, severity = "info") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary, life: 3000 });
    } else {
        console.log(`[Civitai Prompt Import] ${summary}`);
    }
}

async function analyzeUrl(url, modelRoots = "", scanComfyModels = true) {
    const response = await api.fetchApi("/civitai-prompt-import/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            url,
            model_roots: modelRoots,
            scan_comfy_models: scanComfyModels,
        }),
        cache: "no-store",
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data?.error || response.statusText);
    }
    return data;
}

function copyButton(text) {
    const button = document.createElement("button");
    button.textContent = "Copy";
    button.type = "button";
    button.style.cssText = "border:1px solid #4b5563;background:#111827;color:#e5e7eb;padding:4px 8px;border-radius:4px;cursor:pointer;";
    button.addEventListener("click", async () => {
        await navigator.clipboard.writeText(text || "");
        notify("Copied");
    });
    return button;
}

function section(title, text) {
    const wrapper = document.createElement("section");
    wrapper.style.cssText = "display:grid;gap:8px;";

    const header = document.createElement("div");
    header.style.cssText = "display:flex;align-items:center;gap:8px;";

    const label = document.createElement("h3");
    label.textContent = title;
    label.style.cssText = "margin:0;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#9ca3af;flex:1;";
    header.append(label, copyButton(text || ""));

    const area = document.createElement("textarea");
    area.value = text || "";
    area.readOnly = true;
    area.spellcheck = false;
    area.style.cssText = "width:100%;min-height:120px;box-sizing:border-box;background:#020617;color:#e5e7eb;border:1px solid #374151;border-radius:4px;padding:8px;font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;resize:vertical;";

    wrapper.append(header, area);
    return wrapper;
}

function modelsTable(resources) {
    const wrapper = document.createElement("section");
    wrapper.style.cssText = "display:grid;gap:8px;";

    const title = document.createElement("h3");
    title.textContent = "Models";
    title.style.cssText = "margin:0;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#9ca3af;";
    wrapper.append(title);

    const list = document.createElement("div");
    list.style.cssText = "display:grid;gap:6px;";

    if (!resources?.length) {
        const empty = document.createElement("div");
        empty.textContent = "No model records found.";
        empty.style.cssText = "color:#9ca3af;font-size:12px;";
        list.append(empty);
    } else {
        for (const resource of resources) {
            const item = document.createElement("div");
            item.style.cssText = "border:1px solid #374151;background:#111827;padding:8px;border-radius:4px;display:grid;gap:4px;";
            const name = document.createElement("div");
            name.textContent = resource.model_name || resource.version_name || "Model";
            name.style.cssText = "font-weight:600;color:#f9fafb;";
            const meta = document.createElement("div");
            meta.textContent = [
                resource.model_type,
                resource.version_name,
                resource.base_model ? `Base: ${resource.base_model}` : "",
                resource.strength !== null && resource.strength !== undefined ? `Strength: ${resource.strength}` : "",
                `Status: ${resource.availability}`,
            ].filter(Boolean).join(" | ");
            meta.style.cssText = "font-size:12px;color:#9ca3af;";
            item.append(name, meta);
            if (resource.matched_path) {
                const path = document.createElement("div");
                path.textContent = resource.matched_path;
                path.style.cssText = "font-size:12px;color:#86efac;word-break:break-all;";
                item.append(path);
            }
            list.append(item);
        }
    }

    wrapper.append(list);
    return wrapper;
}

function showReportDialog(report) {
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:10000;display:flex;align-items:center;justify-content:center;padding:24px;";

    const panel = document.createElement("div");
    panel.style.cssText = "width:min(980px,96vw);max-height:90vh;overflow:auto;background:#030712;color:#e5e7eb;border:1px solid #374151;border-radius:6px;box-shadow:0 20px 60px rgba(0,0,0,.45);padding:16px;display:grid;gap:14px;";

    const header = document.createElement("div");
    header.style.cssText = "display:flex;align-items:center;gap:12px;";
    const title = document.createElement("h2");
    title.textContent = "arch-Civitai Prompt Metadata";
    title.style.cssText = "margin:0;font-size:16px;flex:1;";
    const close = document.createElement("button");
    close.textContent = "Close";
    close.type = "button";
    close.style.cssText = "border:1px solid #4b5563;background:#111827;color:#e5e7eb;padding:6px 10px;border-radius:4px;cursor:pointer;";
    close.addEventListener("click", () => overlay.remove());
    header.append(title, close);

    const settingsText = JSON.stringify(report.settings || [], null, 2);
    const modelsText = JSON.stringify(report.resources || [], null, 2);
    const warnings = report.warnings?.length ? report.warnings.join("\n") : "";

    panel.append(
        header,
        section("Prompt", report.prompt || ""),
        section("Negative Prompt", report.negative_prompt || ""),
        section("Settings JSON", settingsText),
        modelsTable(report.resources || []),
        section("Models JSON", modelsText)
    );
    if (warnings) {
        panel.append(section("Notices", warnings));
    }

    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) {
            overlay.remove();
        }
    });
    overlay.append(panel);
    document.body.append(overlay);
}

function installControls(node) {
    if (node._civitaiPromptImportInstalled) {
        return;
    }
    node._civitaiPromptImportInstalled = true;

    node.addWidget("button", "Analyze URL", "analyze", async () => {
        const url = getWidget(node, "url")?.value || "";
        const modelRoots = getWidget(node, "model_roots")?.value || "";
        const scanComfyModels = getWidget(node, "scan_comfy_models")?.value !== false;
        if (!String(url).trim()) {
            notify("Enter a Civitai image URL", "warn");
            return;
        }
        try {
            const report = await analyzeUrl(url, modelRoots, scanComfyModels);
            showReportDialog(report);
        } catch (error) {
            notify(`Analyze failed: ${error.message}`, "error");
        }
    });
}

window.comfyCivitaiPromptImport = {
    analyzeUrl,
    showReportDialog,
};

app.registerExtension({
    name: EXTENSION_NAME,

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            installControls(this);
            return result;
        };
    },
});
