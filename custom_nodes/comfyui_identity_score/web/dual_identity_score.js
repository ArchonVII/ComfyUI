import { app } from "../../scripts/app.js";


const NODE_NAME = "DualIdentityScore";
const WIDGET_NAMES = {
  referenceScore: "Reference score",
  baseScore: "Base score",
  active: "Active score",
  baseDetection: "Base face",
  referenceDetection: "Reference face",
  generatedDetection: "Generated face",
  status: "Identity status",
  resultId: "Result ID",
};


function firstValue(payload, key, fallback = "") {
  const value = payload?.[key];
  return Array.isArray(value) ? (value[0] ?? fallback) : (value ?? fallback);
}


function formatDetection(detection, name) {
  return `${name}: ${detection?.[name] ? "detected" : "not detected"}`;
}


function readOnlyWidget(node, name, value) {
  const widget = node.addWidget("text", name, value, null, { serialize: false });
  widget.serialize = false;
  widget.readOnly = true;
  return widget;
}


function resultWidgets(node) {
  return node._dualIdentityScoreResultWidgets ?? {};
}


function splitScoreText(scoreText) {
  const segments = String(scoreText).split(";").map((segment) => segment.trim());
  return {
    reference: segments.find((segment) => segment.startsWith("reference ")) ?? "reference score unavailable",
    base: segments.find((segment) => segment.startsWith("base ")) ?? "base score unavailable",
    active: segments.find((segment) => segment.startsWith("active ")) ?? "active score unavailable",
  };
}


function updateResultWidgets(node, message) {
  const payload = message?.ui ?? message ?? {};
  const widgets = resultWidgets(node);
  if (!widgets.referenceScore) {
    return;
  }

  const detection = firstValue(payload, "face_detection", {});
  const status = firstValue(payload, "status", "pending");
  const resultId = firstValue(payload, "result_id", "") || "manual";
  const scoreText = firstValue(payload, "text", "No identity result returned.");
  const scores = splitScoreText(scoreText);
  widgets.referenceScore.value = scores.reference;
  widgets.baseScore.value = scores.base;
  widgets.active.value = scores.active;
  widgets.baseDetection.value = formatDetection(detection, "base");
  widgets.referenceDetection.value = formatDetection(detection, "reference");
  widgets.generatedDetection.value = formatDetection(detection, "generated");
  widgets.status.value = `status: ${status}`;
  widgets.resultId.value = `result: ${resultId}`;
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
      this._dualIdentityScoreResultWidgets = {
        referenceScore: readOnlyWidget(this, WIDGET_NAMES.referenceScore, "Awaiting identity score…"),
        baseScore: readOnlyWidget(this, WIDGET_NAMES.baseScore, "Awaiting identity score…"),
        active: readOnlyWidget(this, WIDGET_NAMES.active, "Awaiting identity score…"),
        baseDetection: readOnlyWidget(this, WIDGET_NAMES.baseDetection, "Awaiting identity score…"),
        referenceDetection: readOnlyWidget(this, WIDGET_NAMES.referenceDetection, "Awaiting identity score…"),
        generatedDetection: readOnlyWidget(this, WIDGET_NAMES.generatedDetection, "Awaiting identity score…"),
        status: readOnlyWidget(this, WIDGET_NAMES.status, "status: pending"),
        resultId: readOnlyWidget(this, WIDGET_NAMES.resultId, "result: manual"),
      };
      const size = this.computeSize?.();
      if (size) {
        this.setSize?.([
          Math.max(this.size?.[0] ?? 0, size[0]),
          Math.max(this.size?.[1] ?? 0, size[1]),
        ]);
      }
    };

    const previousExecuted = NodeType.prototype.onExecuted;
    NodeType.prototype.onExecuted = function (message) {
      previousExecuted?.call(this, message);
      updateResultWidgets(this, message);
    };
  },
});
