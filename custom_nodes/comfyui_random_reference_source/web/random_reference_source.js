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

      return result;
    };
  },
});
