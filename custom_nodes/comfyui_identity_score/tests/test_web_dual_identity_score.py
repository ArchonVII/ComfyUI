import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "web" / "dual_identity_score.js"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_dual_identity_score_frontend_renders_execution_status():
    node_script = f"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync({json.dumps(str(SCRIPT_PATH))}, "utf8")
  .replace(/^import[^\\n]*\\n/gm, "");

let extension = null;
const app = {{
  registerExtension(value) {{ extension = value; }},
}};
const context = {{ app, console }};
vm.runInNewContext(source, context);
if (!extension) throw new Error("extension did not register");

function NodeType() {{}}
const node = Object.create(NodeType.prototype);
node.widgets = [];
node.addWidget = function(type, name, value, callback, options = {{}}) {{
  const widget = {{ type, name, value, callback, options }};
  this.widgets.push(widget);
  return widget;
}};
node.setDirtyCanvas = function() {{ this.dirty = true; }};
node.size = [240, 120];
node.computeSize = function() {{ return [320, 460]; }};
node.setSize = function(size) {{ this.size = size; }};

(async () => {{
  await extension.beforeRegisterNodeDef(NodeType, {{ name: "DualIdentityScore" }});
  node.onNodeCreated();
  const referenceScore = node.widgets.find((item) => item.name === "Reference score");
  const baseScore = node.widgets.find((item) => item.name === "Base score");
  const active = node.widgets.find((item) => item.name === "Active score");
  const baseDetection = node.widgets.find((item) => item.name === "Base face");
  const referenceDetection = node.widgets.find((item) => item.name === "Reference face");
  const generatedDetection = node.widgets.find((item) => item.name === "Generated face");
  const status = node.widgets.find((item) => item.name === "Identity status");
  const resultId = node.widgets.find((item) => item.name === "Result ID");
  if (![referenceScore, baseScore, active, baseDetection, referenceDetection, generatedDetection, status, resultId].every(Boolean)) {{
    throw new Error("separate result widgets were not created");
  }}
  if (![referenceScore, baseScore, active, baseDetection, referenceDetection, generatedDetection, status, resultId].every((widget) => widget.options.serialize === false)) {{
    throw new Error("result widgets must not serialize into workflows");
  }}
  if (node.size[1] < 460) throw new Error("node was not resized for result widgets");

  node.onExecuted({{
    status: ["rankable"],
    result_id: ["run-2"],
    face_detection: [{{ base: true, reference: true, generated: true }}],
    text: ["reference 0.910000; base 0.420000; active (reference) 0.910000"],
  }});
  if (!referenceScore.value.includes("reference 0.910000")) throw new Error("reference score was not rendered");
  if (!baseScore.value.includes("base 0.420000")) throw new Error("base score was not rendered");
  if (!active.value.includes("active (reference) 0.910000")) throw new Error("active score was not rendered");
  if (!baseDetection.value.includes("base: detected")) throw new Error("base detection was not rendered");
  if (!referenceDetection.value.includes("reference: detected")) throw new Error("reference detection was not rendered");
  if (!generatedDetection.value.includes("generated: detected")) throw new Error("generated detection was not rendered");
  if (!status.value.includes("status: rankable")) throw new Error("rankability was not rendered");
  if (!resultId.value.includes("result: run-2")) throw new Error("result id was not rendered");

  node.onExecuted({{
    status: ["not_rankable"],
    result_id: [""],
    face_detection: [{{ base: true, reference: false, generated: true }}],
    text: ["reference unavailable; base 0.840000; active (reference) unavailable"],
  }});
  if (!status.value.includes("status: not_rankable")) throw new Error("status was not updated");
  if (!referenceDetection.value.includes("reference: not detected")) throw new Error("updated detection was not rendered");
  if (!node.dirty) throw new Error("node was not marked dirty");
}})().catch((error) => {{
  console.error(error.stack || error.message);
  process.exit(1);
}});
"""
    result = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_identity_score_package_exposes_web_directory():
    from comfyui_identity_score import WEB_DIRECTORY

    assert WEB_DIRECTORY == "./web"
