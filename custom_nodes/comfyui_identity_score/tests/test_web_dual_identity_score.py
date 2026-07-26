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

(async () => {{
  await extension.beforeRegisterNodeDef(NodeType, {{ name: "DualIdentityScore" }});
  node.onNodeCreated();
  const widget = node.widgets.find((item) => item.name === "dual_identity_score_result");
  if (!widget) throw new Error("result widget was not created");

  node.onExecuted({{
    ui: {{
      status: ["rankable"],
      result_id: ["run-2"],
      face_detection: [{{ base: true, reference: true, generated: true }}],
      text: ["reference 0.910000; base 0.420000; active (reference) 0.910000"],
    }},
  }});
  if (!widget.value.includes("reference 0.910000")) throw new Error("scores were not rendered");
  if (!widget.value.includes("base: detected")) throw new Error("base detection was not rendered");
  if (!widget.value.includes("result: run-2")) throw new Error("result id was not rendered");

  node.onExecuted({{
    ui: {{
      status: ["not_rankable"],
      result_id: [""],
      face_detection: [{{ base: true, reference: false, generated: true }}],
      text: ["active (reference) unavailable"],
    }},
  }});
  if (!widget.value.includes("status: not_rankable")) throw new Error("status was not updated");
  if (!widget.value.includes("reference: not detected")) throw new Error("updated detection was not rendered");
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
