import json
import subprocess
from pathlib import Path


def test_load_collection_clears_previous_data_when_collection_is_missing():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "custom_nodes" / "comfyui_civitai_ingestor" / "web" / "civitai_ingestor.js"
    node_script = f"""
const fs = require("fs");
const vm = require("vm");
const scriptPath = {json.dumps(str(script_path))};
const source = fs.readFileSync(scriptPath, "utf8")
  .replace(/^import[^\\n]*\\n/gm, "")
  + "\\nglobalThis.__ci = {{ loadCollection }};";

const nodes = new Map([
  ["[data-ci-url]", {{ value: "https://civitai.red/collections/999" }}],
  ["[data-ci-status]", {{ textContent: "" }}],
  ["[data-ci-summary]", {{ innerHTML: "old summary" }}],
  ["[data-ci-search]", {{ value: "" }}],
  ["[data-ci-images]", {{ innerHTML: "old image" }}],
  ["[data-ci-resources]", {{ innerHTML: "old resource" }}],
  ["[data-ci-filter-status]", {{ textContent: "old counts" }}],
]);
const panel = {{
  _civitaiIngestorData: {{
    collection: {{ collection_id: 8081491 }},
    summary: {{ images: 1, resource_files: 1 }},
    images: [{{ image_id: 1, prompt: "old" }}],
    resources: [{{ file_id: 2, file_name: "old.safetensors" }}],
  }},
  querySelector(selector) {{
    if (!nodes.has(selector)) throw new Error(`Missing selector ${{selector}}`);
    return nodes.get(selector);
  }},
}};

const context = {{
  app: {{ registerExtension() {{}} }},
  api: {{
    fetchApi: async (url) => {{
      if (url !== "/civitai-ingestor/collections/999") throw new Error(`Unexpected URL ${{url}}`);
      return {{
        ok: true,
        json: async () => ({{
          collection: null,
          summary: {{ images: 0, images_with_meta: 0, resource_files: 0, missing_files: 0, present_files: 0 }},
          images: [],
          resources: [],
          image_resources: [],
        }}),
      }};
    }},
  }},
  console,
  globalThis: null,
}};
context.globalThis = context;

vm.runInNewContext(source, context);

(async () => {{
  await context.__ci.loadCollection(panel);
  if (panel._civitaiIngestorData.images.length !== 0) {{
    throw new Error("Expected missing collection to clear stale image data");
  }}
  if (!nodes.get("[data-ci-images]").innerHTML.includes("No matching images")) {{
    throw new Error("Expected missing collection to render an empty image state");
  }}
  if (!nodes.get("[data-ci-status]").textContent.includes("No saved collection")) {{
    throw new Error("Expected missing collection status");
  }}
}})().catch((error) => {{
  console.error(error.stack || error.message);
  process.exit(1);
}});
"""

    result = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_ingest_clears_previous_data_when_backend_rejects_collection():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "custom_nodes" / "comfyui_civitai_ingestor" / "web" / "civitai_ingestor.js"
    node_script = f"""
const fs = require("fs");
const vm = require("vm");
const scriptPath = {json.dumps(str(script_path))};
const source = fs.readFileSync(scriptPath, "utf8")
  .replace(/^import[^\\n]*\\n/gm, "")
  + "\\nglobalThis.__ci = {{ ingest }};";

const nodes = new Map([
  ["[data-ci-url]", {{ value: "https://civitai.red/collections/999" }}],
  ["[data-ci-token]", {{ value: "" }}],
  ["[data-ci-max]", {{ value: "3" }}],
  ["[data-ci-status]", {{ textContent: "" }}],
  ["[data-ci-summary]", {{ innerHTML: "old summary" }}],
  ["[data-ci-search]", {{ value: "" }}],
  ["[data-ci-images]", {{ innerHTML: "old image" }}],
  ["[data-ci-resources]", {{ innerHTML: "old resource" }}],
  ["[data-ci-filter-status]", {{ textContent: "old counts" }}],
]);
const panel = {{
  _civitaiIngestorData: {{
    collection: {{ collection_id: 8081491 }},
    summary: {{ images: 1, resource_files: 1 }},
    images: [{{ image_id: 1, prompt: "old" }}],
    resources: [{{ file_id: 2, file_name: "old.safetensors" }}],
  }},
  querySelector(selector) {{
    if (!nodes.has(selector)) throw new Error(`Missing selector ${{selector}}`);
    return nodes.get(selector);
  }},
}};

const context = {{
  app: {{ registerExtension() {{}} }},
  api: {{
    fetchApi: async (url) => {{
      if (url !== "/civitai-ingestor/ingest") throw new Error(`Unexpected URL ${{url}}`);
      return {{
        ok: false,
        statusText: "Bad Gateway",
        json: async () => ({{ error: "Civitai images endpoint ignored collectionId" }}),
      }};
    }},
  }},
  console,
  globalThis: null,
}};
context.globalThis = context;

vm.runInNewContext(source, context);

(async () => {{
  let errorMessage = "";
  try {{
    await context.__ci.ingest(panel);
  }} catch (error) {{
    errorMessage = error.message;
  }}
  if (!errorMessage.includes("ignored collectionId")) {{
    throw new Error(`Expected collectionId rejection, got ${{errorMessage}}`);
  }}
  if (panel._civitaiIngestorData.images.length !== 0) {{
    throw new Error("Expected failed ingest to clear stale image data");
  }}
  if (!nodes.get("[data-ci-images]").innerHTML.includes("No matching images")) {{
    throw new Error("Expected failed ingest to render an empty image state");
  }}
}})().catch((error) => {{
  console.error(error.stack || error.message);
  process.exit(1);
}});
"""

    result = subprocess.run(
        ["node", "-e", node_script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
