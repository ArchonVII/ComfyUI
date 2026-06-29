import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const LOADER_CLASS = "PromptLibraryLoader";
const SAVER_CLASS = "PromptLibrarySaver";
const EMPTY_PROMPT_NAME = "<empty: save a prompt first>";

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function getWidgetValue(node, name, fallback = "") {
    const widget = getWidget(node, name);
    return widget?.value ?? fallback;
}

function notify(summary, severity = "info") {
    if (app.extensionManager?.toast) {
        app.extensionManager.toast.add({
            severity,
            summary,
            life: 2500,
        });
    } else {
        console.log(`[Prompt Library] ${summary}`);
    }
}

async function fetchLibrary() {
    const response = await api.fetchApi("/prompt-library/prompts", { cache: "no-store" });
    if (!response.ok) {
        throw new Error(await response.text());
    }
    return await response.json();
}

async function savePrompt(payload) {
    const response = await api.fetchApi("/prompt-library/prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });

    if (!response.ok) {
        let message = await response.text();
        try {
            message = JSON.parse(message).error || message;
        } catch (_) {
            // Keep the raw response text.
        }
        throw new Error(message);
    }

    return await response.json();
}

function dropdownValues(data) {
    return data.dropdown_names?.length ? data.dropdown_names : [EMPTY_PROMPT_NAME];
}

function refreshLoaderNode(node, data) {
    const promptWidget = getWidget(node, "prompt_name");
    if (!promptWidget) {
        return;
    }

    const values = dropdownValues(data);
    promptWidget.options = promptWidget.options || {};
    promptWidget.options.values = values;

    if (!values.includes(promptWidget.value)) {
        promptWidget.value = values[0];
    }

    node.setDirtyCanvas(true, true);
}

function refreshAllLoaderNodes(data) {
    for (const node of app.graph?._nodes || []) {
        if (node.comfyClass === LOADER_CLASS || node.type === LOADER_CLASS) {
            refreshLoaderNode(node, data);
        }
    }
}

async function refreshLibrary(node, showToast = true) {
    const data = await fetchLibrary();
    refreshAllLoaderNodes(data);
    if (node) {
        refreshLoaderNode(node, data);
    }
    if (showToast) {
        notify(`Loaded ${data.names.length} saved prompt${data.names.length === 1 ? "" : "s"}.`);
    }
    return data;
}

function installLoaderControls(node) {
    if (node._promptLibraryControlsInstalled) {
        return;
    }
    node._promptLibraryControlsInstalled = true;

    const button = node.addWidget("button", "Refresh prompts", "refresh", async () => {
        try {
            await refreshLibrary(node);
        } catch (error) {
            notify(`Prompt refresh failed: ${error.message}`, "error");
        }
    });
    button.serialize = false;
    button.serializeValue = () => undefined;

    setTimeout(() => refreshLibrary(node, false).catch(console.error), 50);
}

function installSaverControls(node) {
    if (node._promptLibraryControlsInstalled) {
        return;
    }
    node._promptLibraryControlsInstalled = true;

    const button = node.addWidget("button", "Save now", "save", async () => {
        try {
            const data = await savePrompt({
                name: getWidgetValue(node, "prompt_name"),
                positive: getWidgetValue(node, "positive"),
                negative: getWidgetValue(node, "negative"),
                notes: getWidgetValue(node, "notes"),
                overwrite: Boolean(getWidgetValue(node, "overwrite", true)),
            });
            refreshAllLoaderNodes(data);
            notify(`Saved "${data.prompt.name}".`);
        } catch (error) {
            notify(`Prompt save failed: ${error.message}`, "error");
        }
    });
    button.serialize = false;
    button.serializeValue = () => undefined;
}

app.registerExtension({
    name: "comfyui.prompt_library",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (![LOADER_CLASS, SAVER_CLASS].includes(nodeData.name)) {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            if (nodeData.name === LOADER_CLASS) {
                installLoaderControls(this);
            } else {
                installSaverControls(this);
            }
            return result;
        };
    },
});
