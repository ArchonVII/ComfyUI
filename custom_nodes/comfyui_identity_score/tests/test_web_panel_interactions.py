import json
import subprocess
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "web" / "identity_lab.js"


def test_identity_lab_panel_drives_local_review_and_delete_controls():
    script = f"""
const fs = require("fs"), vm = require("vm");
let source = fs.readFileSync({json.dumps(str(SCRIPT_PATH))}, "utf8").replace(/^import[^\\n]*\\n/gm, "").replaceAll("import.meta.url", JSON.stringify("https://local/identity_lab.js")).replace(/export \\{{[^}}]+\\}};?\\s*$/m, "");
;(async () => {{
function node(tag) {{ return {{ tagName:tag, children:[], listeners:{{}}, dataset:{{}}, style:{{}}, textContent:"", value:"", checked:false,
  append(...x){{for(const c of x)c.parent=this;this.children.push(...x);if(this.tagName==="select"&&!this.value&&x[0])this.value=x[0].value}}, prepend(...x){{for(const c of x)c.parent=this;this.children.unshift(...x)}}, replaceChildren(...x){{for(const c of x)c.parent=this;this.children=x}}, addEventListener(n,h){{this.listeners[n]=h}}, setAttribute(){{}},
  querySelector(s){{return this.querySelectorAll(s)[0]}}, querySelectorAll(s){{const out=[]; const m=s.match(/^([a-z]+)?\\[name=\"([^\"]+)\"\\](?::checked)?$/); const walk=(v)=>{{for(const c of v.children||[]){{if(m&&(!m[1]||c.tagName===m[1])&&c.name===m[2]&&(!s.endsWith(":checked")||c.checked))out.push(c);walk(c)}}}};walk(this);return out;}}
}}; }}
const workflow = {{
 "1":{{class_type:"LoadImage",inputs:{{image:"base.png"}},_meta:{{title:"IDENTITY_LAB_BASE_IMAGE"}}}}, "2":{{class_type:"LoadImage",inputs:{{image:"ref.png"}},_meta:{{title:"IDENTITY_LAB_REFERENCE_IMAGE"}}}}, "3":{{class_type:"UNETLoader",inputs:{{}},_meta:{{title:"IDENTITY_LAB_MODEL"}}}}, "4":{{class_type:"LoraLoader",inputs:{{lora_name:"safe-1.safetensors"}},_meta:{{title:"IDENTITY_LAB_LORA_1"}}}}, "5":{{class_type:"LoraLoader",inputs:{{lora_name:"safe-2.safetensors"}},_meta:{{title:"IDENTITY_LAB_LORA_2"}}}}, "6":{{class_type:"LoraLoader",inputs:{{lora_name:"safe-3.safetensors"}},_meta:{{title:"IDENTITY_LAB_LORA_3"}}}}, "7":{{class_type:"KSampler",inputs:{{}},_meta:{{title:"IDENTITY_LAB_SAMPLER"}}}}, "8":{{class_type:"DualIdentityScore",inputs:{{}},_meta:{{title:"IDENTITY_LAB_SCORE"}}}}, "9":{{class_type:"ImageScaleToTotalPixels",inputs:{{}},_meta:{{title:"IDENTITY_LAB_PIXEL_BUDGET"}}}}
}};
let calls=[], archived=false, deletePreview=false, deleted=false;
const run={{id:"run-1",state:"completed",favorite:false,rating:null,notes:"",plan:{{checkpoint:"flux.safetensors",seed:7,loras:[],stage:"baseline",refine:{{}}}},identity_report:{{active_score:{{cosine_similarity:.9}},reference_to_output:{{cosine_similarity:.9}},base_to_output:{{cosine_similarity:.2}},rankable:true,face_detection:{{base:true,reference:true,generated:true}},runtime_seconds:3}}}};
const detail=()=>({{experiment:{{id:"exp-1",settings:{{workflow_template:workflow,setup:{{mode:"face_swap",checkpoints:["flux.safetensors"],loras:[{{name:"face.safetensors",strength:.7}}],seeds:[7],steps:28,cfg:3.5,denoise:.8,pixelBudget:1.048576,sampler:"euler",scheduler:"simple"}}}}}},runs:[run]}});
const backend={{fetchApi:async(path,options={{}})=>{{calls.push([path,options]); const body=options.body?JSON.parse(options.body):null;
 if(path.endsWith("/catalog"))return {{ok:true,json:async()=>({{diffusion_models:["flux.safetensors"],loras:["face.safetensors"]}})}};
 if(path.endsWith("/estimates"))return {{ok:true,json:async()=>({{run_count:body.run_count,estimated_seconds:2,estimated_bytes:3,free_bytes:4,time_source:"fallback",disk_source:"fallback",can_launch:true}})}};
 if(path==="/identity-lab/experiments"){{if(options.method==="POST")return {{ok:true,json:async()=>({{experiment:detail().experiment,runs:[run]}})}};return {{ok:true,json:async()=>({{experiments:[detail().experiment]}})}}}}
 if(path==="/identity-lab/experiments/exp-1"&&options.method!=="DELETE")return {{ok:true,json:async()=>detail()}};
 if(path.includes("/review")){{Object.assign(run,body);return {{ok:true,json:async()=>run}}}}
 if(path.endsWith("/promote"))return {{ok:true,json:async()=>({{runs:[]}})}};
 if(path.endsWith("/archive")){{archived=true;return {{ok:true,json:async()=>({{state:"archived"}})}}}}
 if(path.endsWith("/delete-preview")){{deletePreview=true;return {{ok:true,json:async()=>({{runs:["run-1"],files:["identity_lab/results/run-1.png"],token:"a".repeat(64),confirmation:"DELETE exp-1"}})}}}}
 if(path==="/identity-lab/experiments/exp-1"&&options.method==="DELETE"){{deleted=true;return {{ok:true,json:async()=>({{runs:["run-1"],recoverable_trash:[]}})}}}}
 if(path.includes("/resume")||path.includes("/queued")||path.includes("/failed"))return {{ok:true,json:async()=>({{state:"queued"}})}};
 if(path==="/prompt")return {{ok:true,json:async()=>({{prompt_id:"p"}})}};
 if(path.startsWith("/history/"))return {{ok:true,json:async()=>({{p:{{status:{{status_str:"success"}}}}}})}};
 return {{ok:true,json:async()=>({{}})}};
}}}};
let sidebar; const app={{registerExtension(){{}},extensionManager:{{registerSidebarTab(v){{sidebar=v}}}},graphToPrompt:async()=>({{output:workflow}})}};
const document={{head:{{append(){{}}}},createElement:node}}; const context={{app,api:backend,document,Option:function(t,v){{let x=node("option");x.textContent=t;x.value=v;return x}},URL,structuredClone,console,setTimeout,clearTimeout}};
vm.runInNewContext(source,context); const root=node("section"); sidebar.render(root); await new Promise(resolve=>setTimeout(resolve,0));
const walk=(root)=>{{const a=[];const w=(v)=>{{for(const c of v.children||[]){{a.push(c);w(c)}}}};w(root);return a}}; const byText=(text)=>walk(root).find(x=>x.textContent===text); const byClickText=(text)=>walk(root).find(x=>x.textContent===text&&x.listeners.click); const byName=(name)=>walk(root).find(x=>x.name===name);
const form=walk(root).find(x=>x.tagName==="form"); await form.listeners.submit({{preventDefault(){{}}}}); await new Promise(resolve=>setTimeout(resolve,0));
const rate=byClickText("5"); await rate.listeners.click(); const favorite=byClickText("☆"); await favorite.listeners.click(); const reject=byClickText("Reject (1)"); await reject.listeners.click(); const notes=walk(root).find(x=>x.tagName==="textarea"); notes.value="keep details"; await notes.listeners.change();
const choose=walk(root).find(x=>x.tagName==="input"&&x.parent?.tagName==="article"); choose.checked=true; choose.listeners.change({{target:choose}}); const stage=walk(root).find(x=>x.tagName==="select"&&x.children.some(c=>c.value==="focused_refine")); stage.value="focused_refine"; byName("steps").value="31"; await byClickText("Preview promotion").listeners.click(); await byClickText("Confirm promotion").listeners.click();
await byClickText("Pause after current").listeners.click(); await byClickText("Resume planned or confirmed-stale work").listeners.click(); await byClickText("Archive").listeners.click(); await byClickText("Preview deletion").listeners.click(); const confirmation=walk(root).find(x=>x.placeholder==="DELETE exp-1"); confirmation.value="wrong"; await byClickText("Delete archived experiment").listeners.click(); if(deleted)throw new Error("wrong confirmation was sent"); confirmation.value="DELETE exp-1"; await byClickText("Delete archived experiment").listeners.click();
const bodies=calls.map(([p,o])=>[p,o.method, o.body&&JSON.parse(o.body)]); if(!bodies.some(([p,m,b])=>p.endsWith("/estimates")&&m==="POST"&&b.run_count===3))throw new Error("launch did not request a matching backend estimate"); if(!bodies.some(([p,m,b])=>p.includes("/review")&&b.rating===5)||!bodies.some(([p,m,b])=>p.includes("/review")&&b.favorite===true)||!bodies.some(([p,m,b])=>p.includes("/review")&&b.notes==="keep details"))throw new Error("review controls did not patch local API"); if(!bodies.some(([p,m,b])=>p.endsWith("/promote")&&b.stages[0]==="focused_refine"&&b.refine_settings.steps===31))throw new Error("focused refinement used stale controls"); if(!archived||!deletePreview||!deleted||!bodies.some(([p,m,b])=>m==="DELETE"&&b.token==="a".repeat(64)))throw new Error("archive/delete contract was not driven");
}})().catch((error) => {{ console.error(error.stack || error.message); process.exit(1); }});
"""
    result = subprocess.run(["node", "-e", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
