import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const APP_ID = "reverse-prompter-app";

function notify(summary, severity = "info") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary, life: 2500 });
    } else {
        console.log(`[Reverse Prompter] ${summary}`);
    }
}

function createButton() {
    if (document.getElementById(`${APP_ID}-button`)) {
        return;
    }
    const button = document.createElement("button");
    button.id = `${APP_ID}-button`;
    button.textContent = "arch-Reverse Prompter";
    button.style.cssText = [
        "position:fixed",
        "right:16px",
        "bottom:16px",
        "z-index:9999",
        "padding:8px 10px",
        "border:1px solid #555",
        "border-radius:6px",
        "background:#1f2937",
        "color:#f9fafb",
        "font:12px system-ui",
        "cursor:pointer",
    ].join(";");
    button.addEventListener("click", openPanel);
    document.body.appendChild(button);
}

function panelHtml() {
    return `
        <div class="rp-card">
            <div class="rp-head">
                <strong>arch-Reverse Prompter</strong>
                <button type="button" data-rp-close>Close</button>
            </div>
            <div class="rp-grid">
                <button type="button" class="rp-drop" data-rp-drop>
                    <span data-rp-empty>Paste, drop, or select an image</span>
                    <img data-rp-preview alt="" />
                </button>
                <div class="rp-controls">
                    <input data-rp-file type="file" accept="image/*" hidden />
                    <button type="button" data-rp-select>Select image</button>
                    <input data-rp-key type="password" placeholder="OpenAI API key (optional)" autocomplete="off" />
                    <input data-rp-model value="gpt-5" />
                    <select data-rp-mode>
                        <option value="detailed">Detailed</option>
                        <option value="concise">Concise</option>
                        <option value="tags">Tags</option>
                    </select>
                    <select data-rp-detail>
                        <option value="high">High detail</option>
                        <option value="auto">Auto detail</option>
                        <option value="low">Low detail</option>
                    </select>
                    <label class="rp-check"><input data-rp-env-key type="checkbox" /> Use OPENAI_API_KEY from server</label>
                    <input data-rp-endpoint value="https://api.openai.com/v1/responses" />
                    <textarea data-rp-context placeholder="Optional intent or target style"></textarea>
                    <button type="button" data-rp-generate>Generate prompt</button>
                </div>
            </div>
            <textarea data-rp-output spellcheck="false" placeholder="Prompt output"></textarea>
            <div class="rp-foot">
                <span data-rp-status>Ready</span>
                <button type="button" data-rp-copy>Copy</button>
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
        #${APP_ID} .rp-card { width:min(980px, calc(100vw - 32px)); height:min(720px, calc(100vh - 32px)); display:flex; flex-direction:column; gap:10px; padding:12px; border:1px solid #3f3f46; border-radius:8px; background:#111827; color:#f9fafb; font:13px system-ui; box-shadow:0 18px 70px rgba(0,0,0,.45); }
        #${APP_ID} .rp-head, #${APP_ID} .rp-foot { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        #${APP_ID} button, #${APP_ID} input, #${APP_ID} select, #${APP_ID} textarea { border:1px solid #4b5563; border-radius:6px; background:#0b1220; color:#f9fafb; font:13px system-ui; }
        #${APP_ID} button { padding:7px 10px; cursor:pointer; }
        #${APP_ID} input, #${APP_ID} select { padding:7px 8px; }
        #${APP_ID} textarea { padding:8px; resize:none; }
        #${APP_ID} .rp-grid { flex:1; min-height:0; display:grid; grid-template-columns:minmax(260px, .9fr) minmax(260px, .8fr); gap:10px; }
        #${APP_ID} .rp-drop { position:relative; min-height:0; overflow:hidden; display:flex; align-items:center; justify-content:center; border-style:dashed; }
        #${APP_ID} .rp-drop img { display:none; position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }
        #${APP_ID} .rp-controls { min-height:0; display:grid; grid-template-columns:1fr 1fr; gap:8px; align-content:start; }
        #${APP_ID} .rp-controls input, #${APP_ID} .rp-controls textarea, #${APP_ID} .rp-controls button { grid-column:1 / -1; }
        #${APP_ID} [data-rp-context] { height:82px; }
        #${APP_ID} [data-rp-output] { height:180px; font-family:ui-monospace, SFMono-Regular, Consolas, monospace; line-height:1.45; }
        @media (max-width: 760px) { #${APP_ID} .rp-grid { grid-template-columns:1fr; } }
    `;
    document.head.appendChild(style);
    document.body.appendChild(panel);
    wirePanel(panel);
    return panel;
}

function setImage(panel, dataUrl) {
    panel._reversePrompterImage = dataUrl;
    const preview = panel.querySelector("[data-rp-preview]");
    const empty = panel.querySelector("[data-rp-empty]");
    preview.src = dataUrl;
    preview.style.display = "block";
    empty.style.display = "none";
    panel.querySelector("[data-rp-status]").textContent = "Image loaded";
}

function readFile(file, panel) {
    if (!file?.type?.startsWith("image/")) {
        notify("No image found.", "error");
        return;
    }
    const reader = new FileReader();
    reader.onload = () => setImage(panel, String(reader.result || ""));
    reader.readAsDataURL(file);
}

function wirePanel(panel) {
    const close = panel.querySelector("[data-rp-close]");
    const drop = panel.querySelector("[data-rp-drop]");
    const file = panel.querySelector("[data-rp-file]");
    const select = panel.querySelector("[data-rp-select]");
    const generate = panel.querySelector("[data-rp-generate]");
    const copy = panel.querySelector("[data-rp-copy]");

    close.addEventListener("click", () => {
        panel.style.display = "none";
    });
    select.addEventListener("click", () => file.click());
    file.addEventListener("change", () => readFile(file.files?.[0], panel));
    drop.addEventListener("dragover", (event) => event.preventDefault());
    drop.addEventListener("drop", (event) => {
        event.preventDefault();
        readFile(event.dataTransfer?.files?.[0], panel);
    });
    panel.addEventListener("paste", (event) => {
        const item = Array.from(event.clipboardData?.items || []).find((entry) => entry.type.startsWith("image/"));
        if (item) {
            event.preventDefault();
            readFile(item.getAsFile(), panel);
        }
    });
    generate.addEventListener("click", () => generatePrompt(panel));
    copy.addEventListener("click", async () => {
        const text = panel.querySelector("[data-rp-output]").value || "";
        if (!text) {
            return;
        }
        await navigator.clipboard.writeText(text);
        notify("Prompt copied.");
    });
}

async function generatePrompt(panel) {
    if (!panel._reversePrompterImage) {
        notify("Paste, drop, or select an image first.", "error");
        return;
    }
    const status = panel.querySelector("[data-rp-status]");
    status.textContent = "Generating...";
    const payload = {
        image_data_url: panel._reversePrompterImage,
        api_key: panel.querySelector("[data-rp-key]").value,
        model: panel.querySelector("[data-rp-model]").value,
        mode: panel.querySelector("[data-rp-mode]").value,
        detail: panel.querySelector("[data-rp-detail]").value,
        endpoint: panel.querySelector("[data-rp-endpoint]").value,
        extra_context: panel.querySelector("[data-rp-context]").value,
        fallback_on_error: true,
        use_env_api_key: panel.querySelector("[data-rp-env-key]").checked,
    };
    const response = await api.fetchApi("/reverse-prompter/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
        status.textContent = data.error || "Request failed";
        notify(status.textContent, "error");
        return;
    }
    panel.querySelector("[data-rp-output]").value = data.prompt || "";
    status.textContent = data.metadata?.source === "openai" ? "AI prompt ready" : "Local prompt ready";
}

function openPanel() {
    const panel = ensurePanel();
    panel.style.display = "flex";
    setTimeout(() => panel.focus(), 0);
}

app.registerExtension({
    name: "comfyui.reverse_prompter",
    setup() {
        createButton();
        ensurePanel();
    },
});
