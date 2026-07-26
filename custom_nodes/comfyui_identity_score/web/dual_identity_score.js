import { app } from "../../scripts/app.js";


const NODE_NAME = "DualIdentityScore";
const WIDGET_NAME = "dual_identity_score_result";


function firstValue(payload, key, fallback = "") {
  const value = payload?.[key];
  return Array.isArray(value) ? (value[0] ?? fallback) : (value ?? fallback);
}


function formatDetection(detection, name) {
  return `${name}: ${detection?.[name] ? "detected" : "not detected"}`;
}


function resultWidget(node) {
  return node._dualIdentityScoreResultWidget ?? node.widgets?.find((widget) => widget.name === WIDGET_NAME);
}


function updateResultWidget(node, message) {
  const payload = message?.ui ?? message ?? {};
  const widget = resultWidget(node);
  if (!widget) {
    return;
  }

  const detection = firstValue(payload, "face_detection", {});
  const status = firstValue(payload, "status", "pending");
  const resultId = firstValue(payload, "result_id", "") || "manual";
  const scoreText = firstValue(payload, "text", "No identity result returned.");
  widget.value = [
    scoreText,
    `status: ${status}`,
    formatDetection(detection, "base"),
    formatDetection(detection, "reference"),
    formatDetection(detection, "generated"),
    `result: ${resultId}`,
  ].join("\n");
  node.setDirtyCanvas?.(true);
}


app.registerExtension({
  name: "arch.identity-score.dual-result",
  async beforeRegisterNodeDef(NodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) {
      return;
    }

    const previousCreated = NodeType.prototype.onNodeCreated;
    NodeType.prototype.onNodeCreated = function (...args) {
      previousCreated?.apply(this, args);
      this._dualIdentityScoreResultWidget = this.addWidget(
        "text",
        WIDGET_NAME,
        "Awaiting identity score…",
        null,
        { serialize: false },
      );
    };

    const previousExecuted = NodeType.prototype.onExecuted;
    NodeType.prototype.onExecuted = function (message) {
      previousExecuted?.call(this, message);
      updateResultWidget(this, message);
    };
  },
});
