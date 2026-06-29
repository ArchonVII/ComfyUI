import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_CLASSES = new Set(["SmartModelLoraLoader", "ArchModelStackLoader"]);
const NONE = "None";

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function setWidgetOptions(node, name, values, keepValue = true) {
    const widget = getWidget(node, name);
    if (!widget) {
        return;
    }

    const nextValues = values?.length ? values : [NONE];
    widget.options = widget.options || {};
    widget.options.values = nextValues;

    if (!keepValue || !nextValues.includes(widget.value)) {
        widget.value = nextValues[0];
    }
}

function names(items) {
    return (items || []).map((item) => item.name || item).filter(Boolean);
}

function labels(items) {
    return (items || []).map((item) => item.label || item.name || item).filter(Boolean);
}

function loraNameFromLabel(value) {
    if (!value || value === NONE) {
        return NONE;
    }
    return String(value).replace(/^\[(compatible|uncertain)\]\s+/, "");
}

async function fetchCatalog(selectedModel, refresh = false) {
    const params = new URLSearchParams();
    if (selectedModel) {
        params.set("selected_model", selectedModel);
    }
    if (refresh) {
        params.set("refresh", "1");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const response = await api.fetchApi(`/smart-model-loader/catalog${suffix}`, {
        cache: "no-store",
    });
    if (!response.ok) {
        throw new Error(await response.text());
    }
    return await response.json();
}

function notify(summary, severity = "info") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary, life: 2500 });
    } else {
        console.log(`[Smart Model Loader] ${summary}`);
    }
}

function familyForSelectedModel(data) {
    return data?.selected_model?.family || "auto";
}

function clipTypeForFamily(family) {
    if (family === "flux") {
        return "flux2";
    }
    if (family === "qwen") {
        return "qwen_image";
    }
    if (family === "wan") {
        return "wan";
    }
    return "stable_diffusion";
}

function syncFamilyWidgets(node, data) {
    const family = familyForSelectedModel(data);
    const familyWidget = getWidget(node, "workflow_family");
    if (familyWidget && family !== "auto") {
        familyWidget.value = family;
    }

    const clipTypeWidget = getWidget(node, "clip_type");
    if (clipTypeWidget) {
        clipTypeWidget.value = clipTypeForFamily(family);
    }
}

function refreshNodeFromCatalog(node, data) {
    syncFamilyWidgets(node, data);

    setWidgetOptions(node, "clip_name", names(data.filtered?.text_encoders));
    setWidgetOptions(node, "vae_name", names(data.filtered?.vae));

    const loraValues = [NONE, ...labels(data.filtered?.loras)];
    for (let index = 1; index <= 8; index += 1) {
        const widget = getWidget(node, `lora_${index}`);
        if (!widget) {
            continue;
        }
        const selectedName = loraNameFromLabel(widget.value);
        setWidgetOptions(node, `lora_${index}`, loraValues);
        const replacement = loraValues.find((value) => loraNameFromLabel(value) === selectedName);
        widget.value = replacement || NONE;
    }

    node.setDirtyCanvas(true, true);
}

async function refreshNode(node, refresh = false) {
    const primary = getWidget(node, "primary_model")?.value;
    const data = await fetchCatalog(primary, refresh);
    refreshNodeFromCatalog(node, data);
    return data;
}

function wrapPrimaryModelCallback(node) {
    const widget = getWidget(node, "primary_model");
    if (!widget || widget._smartModelLoaderWrapped) {
        return;
    }

    const originalCallback = widget.callback;
    widget.callback = async function () {
        const result = originalCallback?.apply(this, arguments);
        try {
            await refreshNode(node, false);
        } catch (error) {
            notify(`Catalog refresh failed: ${error.message}`, "error");
        }
        return result;
    };
    widget._smartModelLoaderWrapped = true;
}

function installControls(node) {
    if (node._smartModelLoaderInstalled) {
        return;
    }
    node._smartModelLoaderInstalled = true;

    const button = node.addWidget("button", "Refresh catalog", "refresh", async () => {
        try {
            const data = await refreshNode(node, true);
            notify(`Catalog scanned ${data.profiles?.length || 0} local assets.`);
        } catch (error) {
            notify(`Catalog refresh failed: ${error.message}`, "error");
        }
    });
    button.serialize = false;
    button.serializeValue = () => undefined;

    wrapPrimaryModelCallback(node);
    setTimeout(() => refreshNode(node, false).catch(console.error), 50);
}

app.registerExtension({
    name: "comfyui.smart_model_loader",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_CLASSES.has(nodeData.name)) {
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
