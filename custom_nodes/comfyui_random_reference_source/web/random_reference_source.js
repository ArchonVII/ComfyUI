import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_NAME = "RandomReferenceImageSource";

function notify(summary, severity = "info") {
  if (app.extensionManager?.toast?.add) {
    app.extensionManager.toast.add({ severity, summary, life: 3600 });
  } else {
    console.log(`[arch-Random Reference] ${summary}`);
  }
}

function findWidget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

// Push a value into a widget the same way a user edit would, so callbacks and
// the canvas stay in sync.
function setWidgetValue(node, widget, value) {
  if (!widget) return;
  widget.value = value;
  widget.callback?.(value, app.canvas, node);
  node.setDirtyCanvas(true, true);
}

async function callDialog(endpoint, initialDir) {
  const response = await api.fetchApi(`/arch-random-reference/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initial_dir: initialDir || "" }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      data?.error || `Dialog request failed (${response.status})`,
    );
  }
  return data;
}

function referencePayload(node) {
  return {
    lane: findWidget(node, "lane")?.value || "",
    source_mode: findWidget(node, "source_mode")?.value || "auto",
    favorite: findWidget(node, "favorite")?.value || "None",
    folder: findWidget(node, "folder")?.value || ".",
    selected_images: findWidget(node, "selected_images")?.value || "",
    selection_policy:
      findWidget(node, "selection_policy")?.value || "random_each_queue",
    seed: findWidget(node, "seed")?.value || 0,
    include_subfolders: Boolean(findWidget(node, "include_subfolders")?.value),
  };
}

async function fetchPreview(node) {
  const response = await api.fetchApi("/arch-random-reference/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(referencePayload(node)),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data?.error || `Preview failed (${response.status})`);
  }
  return data;
}

function renderPreview(container, data) {
  const images = data?.images || [];
  if (!images.length) {
    container.innerHTML =
      '<div style="opacity:.7;padding:8px;font-size:12px;">No preview images</div>';
    return;
  }

  const note = data.preview_is_exact_next
    ? ""
    : '<div style="grid-column:1/-1;font-size:11px;opacity:.7;">Folder/random mode shows a pool preview; the exact next image is chosen when queued.</div>';
  const escapeHtml = (value) =>
    String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  container.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;align-items:start;">
      ${images
        .map(
          (image) => `
            <div title="${escapeHtml(image.path || image.name)}" style="min-width:0;">
              <img src="${image.thumbnail_data_url}" alt="${escapeHtml(image.name)}" style="width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:4px;border:1px solid rgba(255,255,255,.18);" />
              <div style="font-size:10px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.8;">${escapeHtml(image.name)}</div>
            </div>
          `,
        )
        .join("")}
      ${note}
    </div>
  `;
}

function schedulePreview(node) {
  clearTimeout(node._archReferencePreviewTimer);
  node._archReferencePreviewTimer = setTimeout(async () => {
    if (!node._archReferencePreviewContainer) return;
    try {
      const data = await fetchPreview(node);
      renderPreview(node._archReferencePreviewContainer, data);
    } catch (err) {
      node._archReferencePreviewContainer.innerHTML = `<div style="opacity:.75;padding:8px;font-size:12px;">${String(
        err.message || err,
      )}</div>`;
    }
    node.setDirtyCanvas(true, true);
  }, 200);
}

function installPreviewWidget(node) {
  if (!node.addDOMWidget || node._archReferencePreviewContainer) return;

  const container = document.createElement("div");
  container.style.width = "100%";
  container.style.minHeight = "120px";
  container.style.boxSizing = "border-box";
  container.style.padding = "6px 2px";
  container.style.overflow = "hidden";
  node._archReferencePreviewContainer = container;

  node.addDOMWidget("reference_preview", "div", container, {
    serialize: false,
    getMinHeight: () => 128,
    getMaxHeight: () => 180,
    getValue: () => "",
    setValue: () => {},
  });

  const watchedWidgets = [
    "source_mode",
    "favorite",
    "folder",
    "selected_images",
    "selection_policy",
    "seed",
    "include_subfolders",
  ];
  for (const name of watchedWidgets) {
    const widget = findWidget(node, name);
    if (!widget || widget._archReferencePreviewWrapped) continue;
    widget._archReferencePreviewWrapped = true;
    const callback = widget.callback;
    widget.callback = function () {
      const result = callback?.apply(this, arguments);
      schedulePreview(node);
      return result;
    };
  }

  setTimeout(() => schedulePreview(node), 100);
}

app.registerExtension({
  name: "arch.RandomReferenceSource",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated?.apply(this, arguments);
      const node = this;

      // Insert a button widget directly beneath a named widget so it sits
      // next to the field it controls rather than at the node's bottom.
      const addButtonAfter = (targetName, label, callback) => {
        const button = node.addWidget("button", label, null, callback);
        button.serialize = false;
        button.serializeValue = () => undefined;
        const targetIdx = node.widgets.findIndex((w) => w.name === targetName);
        if (targetIdx !== -1) {
          node.widgets.splice(node.widgets.indexOf(button), 1);
          node.widgets.splice(targetIdx + 1, 0, button);
        }
        return button;
      };

      addButtonAfter("folder", "📁 Browse folder…", async () => {
        const folderWidget = findWidget(node, "folder");
        try {
          const data = await callDialog("browse-folder", folderWidget?.value);
          if (data.path) {
            setWidgetValue(node, folderWidget, data.path);
            schedulePreview(node);
          }
        } catch (err) {
          notify(String(err.message || err), "error");
        }
      });

      addButtonAfter("selected_images", "🖼 Pick images…", async () => {
        const folderWidget = findWidget(node, "folder");
        const selWidget = findWidget(node, "selected_images");
        const modeWidget = findWidget(node, "source_mode");
        try {
          const data = await callDialog("pick-images", folderWidget?.value);
          if (data.paths?.length) {
            setWidgetValue(node, selWidget, data.paths.join("\n"));
            // Picking explicit files only matters in selection mode,
            // so flip the toggle for the user.
            setWidgetValue(node, modeWidget, "selection");
            schedulePreview(node);
            notify(`Added ${data.paths.length} image(s) to the selection.`);
          }
        } catch (err) {
          notify(String(err.message || err), "error");
        }
      });

      // The two new widgets make the node taller; grow it to fit.
      const size = node.computeSize();
      node.setSize([
        Math.max(node.size[0], size[0]),
        Math.max(node.size[1], size[1]),
      ]);
      installPreviewWidget(node);

      return result;
    };
  },
});
