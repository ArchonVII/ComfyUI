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
const detail=()=>({{experiment:{{id:"exp-1",settings:{{workflow_template:workflow,setup:{{mode:"face_swap",checkpoints:["flux.safetensors"],loras:[{{name:"persisted-face.safetensors",strength:.42}}],seeds:[7],steps:28,cfg:3.5,denoise:.8,pixelBudget:1,sampler:"euler",scheduler:"simple"}}}}}},runs:[run]}});
const backend={{fetchApi:async(path,options={{}})=>{{calls.push([path,options]); const body=options.body?JSON.parse(options.body):null;
 if(path.endsWith("/catalog"))return {{ok:true,json:async()=>({{diffusion_models:["flux.safetensors"],loras:["current-face.safetensors","persisted-face.safetensors"]}})}};
 if(path.endsWith("/estimates"))return {{ok:true,json:async()=>({{run_count:body.run_count,estimated_seconds:2,estimated_bytes:3,free_bytes:4,time_source:"completed_median",disk_source:"completed_median",can_launch:true}})}};
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
const restored=node("section"); sidebar.render(restored); await new Promise(resolve=>setTimeout(resolve,0)); const restoredNodes=walk(restored); const restoredExisting=restoredNodes.find(x=>x.name==="active-experiment"); restoredExisting.value="exp-1"; await restoredExisting.listeners.change(); const restoredChoose=walk(restored).find(x=>x.tagName==="input"&&x.parent?.tagName==="article"); restoredChoose.checked=true; restoredChoose.listeners.change({{target:restoredChoose}}); const restoredStage=walk(restored).find(x=>x.tagName==="select"&&x.children.some(c=>c.value==="lora_single")); restoredStage.value="lora_single"; const restoredButton=(text)=>walk(restored).find(x=>x.textContent===text&&x.listeners.click); await restoredButton("Preview promotion").listeners.click(); const restoredStatus=walk(restored).find(x=>x.tagName==="p"&&x.textContent.includes("Promotion preview")); if(!restoredStatus||!restoredStatus.textContent.includes("completed_median"))throw new Error("promotion preview did not display backend estimate sources"); await restoredButton("Confirm promotion").listeners.click();
const bodies=calls.map(([p,o])=>[p,o.method, o.body&&JSON.parse(o.body)]); if(!bodies.some(([p,m,b])=>p==="/identity-lab/estimates"&&m==="POST"&&b.run_count===3))throw new Error("launch did not request a matching backend estimate"); if(!bodies.some(([p,m,b])=>p==="/identity-lab/experiments/exp-1/estimates"&&m==="POST"))throw new Error("promotion did not use the experiment estimate endpoint"); if(!bodies.some(([p,m,b])=>p.endsWith("/promote")&&b.stages[0]==="lora_single"&&b.loras[0][0]==="persisted-face.safetensors"&&b.loras[0][1]===.42))throw new Error("fresh browser promotion did not hydrate persisted LoRAs"); if(!bodies.some(([p,m,b])=>p.includes("/review")&&b.rating===5)||!bodies.some(([p,m,b])=>p.includes("/review")&&b.favorite===true)||!bodies.some(([p,m,b])=>p.includes("/review")&&b.notes==="keep details"))throw new Error("review controls did not patch local API"); if(!bodies.some(([p,m,b])=>p.endsWith("/promote")&&b.stages[0]==="focused_refine"&&b.refine_settings.steps===31))throw new Error("focused refinement used stale controls"); if(!archived||!deletePreview||!deleted||!bodies.some(([p,m,b])=>m==="DELETE"&&b.token==="a".repeat(64)))throw new Error("archive/delete contract was not driven");
}})().catch((error) => {{ console.error(error.stack || error.message); process.exit(1); }});
"""
    result = subprocess.run(["node", "-e", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_identity_lab_panel_surfaces_action_failures_in_live_status_without_unhandled_rejections():
    script = r"""
const fs = require("fs"), vm = require("vm");
let source = fs.readFileSync(__SCRIPT_PATH__, "utf8").replace(/^import[^\n]*\n/gm, "").replaceAll("import.meta.url", JSON.stringify("https://local/identity_lab.js")).replace(/export \{[^}]+\};?\s*$/m, "");
;(async () => {
const node = (tag) => ({ tagName:tag, children:[], listeners:{}, dataset:{}, style:{}, attributes:{}, textContent:"", value:"", checked:false,
  append(...nodes) { for (const child of nodes) child.parent = this; this.children.push(...nodes); if (this.tagName === "select" && !this.value && nodes[0]) this.value = nodes[0].value; },
  prepend(...nodes) { for (const child of nodes) child.parent = this; this.children.unshift(...nodes); },
  replaceChildren(...nodes) { for (const child of nodes) child.parent = this; this.children = nodes; },
  addEventListener(name, handler) { this.listeners[name] = handler; },
  setAttribute(name, value) { this.attributes[name] = value; },
  querySelector(selector) { return this.querySelectorAll(selector)[0]; },
  querySelectorAll(selector) { const result = []; const match = selector.match(/^([a-z]+)?\[name="([^"]+)"\](?::checked)?$/); const visit = (parent) => { for (const child of parent.children || []) { if (match && (!match[1] || child.tagName === match[1]) && child.name === match[2] && (!selector.endsWith(":checked") || child.checked)) result.push(child); visit(child); } }; visit(this); return result; },
});
const workflow = {
  "1":{class_type:"LoadImage",inputs:{},_meta:{title:"IDENTITY_LAB_BASE_IMAGE"}}, "2":{class_type:"LoadImage",inputs:{},_meta:{title:"IDENTITY_LAB_REFERENCE_IMAGE"}},
  "3":{class_type:"UNETLoader",inputs:{},_meta:{title:"IDENTITY_LAB_MODEL"}}, "4":{class_type:"LoraLoader",inputs:{},_meta:{title:"IDENTITY_LAB_LORA_1"}},
  "5":{class_type:"LoraLoader",inputs:{},_meta:{title:"IDENTITY_LAB_LORA_2"}}, "6":{class_type:"LoraLoader",inputs:{},_meta:{title:"IDENTITY_LAB_LORA_3"}},
  "7":{class_type:"KSampler",inputs:{},_meta:{title:"IDENTITY_LAB_SAMPLER"}}, "8":{class_type:"DualIdentityScore",inputs:{},_meta:{title:"IDENTITY_LAB_SCORE"}},
  "9":{class_type:"ImageScaleToTotalPixels",inputs:{},_meta:{title:"IDENTITY_LAB_PIXEL_BUDGET"}},
};
const run = {id:"run-1",state:"completed",favorite:false,rating:null,notes:"",plan:{checkpoint:"flux.safetensors",seed:7,loras:[["face.safetensors", .7]],stage:"baseline",refine:{}},identity_report:{active_score:{cosine_similarity:.9},reference_to_output:{cosine_similarity:.9},base_to_output:{cosine_similarity:.2},rankable:true,face_detection:{base:true,reference:true,generated:true}}};
const detail = () => ({experiment:{id:"exp-1",state:"active",settings:{workflow_template:workflow,setup:{mode:"face_swap",checkpoints:["flux.safetensors"],loras:[{name:"face.safetensors",strength:.7}],seeds:[7],steps:28,cfg:3.5,denoise:.8,pixelBudget:1,sampler:"euler",scheduler:"simple"}}},runs:[run]});
const ok = (value) => ({ok:true,json:async()=>value});
const jsonFailure = (message) => ({ok:false,status:422,json:async()=>({error:message})});
const textFailure = (message) => ({ok:false,status:400,json:async()=>{throw new Error("not JSON")},text:async()=>message});
const backend = {fetchApi: async (path, options = {}) => {
  if (path.endsWith("/catalog")) return ok({diffusion_models:["flux.safetensors"],loras:["face.safetensors"]});
  if (path === "/identity-lab/experiments") return ok({experiments:[detail().experiment]});
  if (path === "/identity-lab/experiments/exp-1" && options.method === "DELETE") return textFailure("delete plain-text detail");
  if (path === "/identity-lab/experiments/exp-1") return ok(detail());
  if (path.endsWith("/review")) return jsonFailure("review JSON detail");
  if (path === "/identity-lab/experiments/exp-1/estimates") return textFailure("promotion plain-text detail");
  if (path.endsWith("/estimates")) return ok({run_count:1,estimated_seconds:1,estimated_bytes:1,free_bytes:1,time_source:"test",disk_source:"test",can_launch:true});
  if (path.endsWith("/archive")) return jsonFailure("archive JSON detail");
  if (path.endsWith("/delete-preview")) return ok({runs:["run-1"],files:["identity_lab/results/run-1.png"],token:"a".repeat(64),confirmation:"DELETE exp-1"});
  return ok({});
}};
let sidebar, unhandled = [];
process.on("unhandledRejection", (error) => unhandled.push(String(error && (error.stack || error.message) || error)));
const app = {registerExtension() {}, extensionManager:{registerSidebarTab(value) { sidebar = value; }}, graphToPrompt:async()=>({output:workflow})};
const document = {head:{append() {}},createElement:node};
const context = {app,api:backend,document,Option:function(text,value) { const option = node("option"); option.textContent = text; option.value = value; return option; },URL,structuredClone,console,setTimeout,clearTimeout};
vm.runInNewContext(source, context);
const root = node("section"); sidebar.render(root); await new Promise((resolve) => setTimeout(resolve, 0));
const walk = (parent) => { const result = []; const visit = (value) => { for (const child of value.children || []) { result.push(child); visit(child); } }; visit(parent); return result; };
const liveStatus = () => walk(root).find((item) => item.attributes["aria-live"] === "polite");
const button = (text) => walk(root).find((item) => item.textContent === text && item.listeners.click);
const assertStatus = (message) => { const status = liveStatus(); if (!status || status.textContent !== `Error: ${message}`) throw new Error(`expected live status ${message}, got ${status && status.textContent}`); };
const existing = walk(root).find((item) => item.name === "active-experiment"); existing.value = "exp-1"; await existing.listeners.change();
if (!liveStatus()) throw new Error("missing aria-live status region");
await button("5").listeners.click(); assertStatus("review JSON detail");
const candidate = walk(root).find((item) => item.tagName === "input" && item.parent && item.parent.tagName === "article"); candidate.checked = true; candidate.listeners.change({target:candidate});
await button("Preview promotion").listeners.click(); assertStatus("promotion plain-text detail");
await button("Archive").listeners.click(); assertStatus("archive JSON detail");
await button("Preview deletion").listeners.click();
const confirmation = walk(root).find((item) => item.placeholder === "DELETE exp-1"); confirmation.value = "DELETE exp-1";
await button("Delete archived experiment").listeners.click(); assertStatus("delete plain-text detail");
await new Promise((resolve) => setTimeout(resolve, 0));
if (unhandled.length) throw new Error(`unhandled rejection: ${unhandled.join("\n")}`);
})().catch((error) => { console.error(error.stack || error.message); process.exit(1); });
""".replace("__SCRIPT_PATH__", json.dumps(str(SCRIPT_PATH)))
    result = subprocess.run(["node", "-e", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_new_experiment_queue_updates_and_setup_controls_are_accessible():
    script = r"""
const fs = require("fs"), vm = require("vm");
let source = fs.readFileSync(__SCRIPT_PATH__, "utf8").replace(/^import[^\n]*\n/gm, "").replaceAll("import.meta.url", JSON.stringify("https://local/identity_lab.js")).replace(/export \{[^}]+\};?\s*$/m, "");
;(async () => {
const node = (tag) => ({tagName:tag,children:[],listeners:{},dataset:{},style:{},attributes:{},textContent:"",value:"",checked:false,
 append(...nodes){for(const child of nodes)child.parent=this;this.children.push(...nodes);if(this.tagName==="select"&&!this.value&&nodes[0])this.value=nodes[0].value},prepend(...nodes){for(const child of nodes)child.parent=this;this.children.unshift(...nodes)},replaceChildren(...nodes){for(const child of nodes)child.parent=this;this.children=nodes},addEventListener(name,handler){this.listeners[name]=handler},setAttribute(name,value){this.attributes[name]=value},querySelector(selector){return this.querySelectorAll(selector)[0]},querySelectorAll(selector){const found=[],match=selector.match(/^([a-z]+)?\[name="([^"]+)"\](?::checked)?$/);const visit=(parent)=>{for(const child of parent.children||[]){if(match&&(!match[1]||child.tagName===match[1])&&child.name===match[2]&&(!selector.endsWith(":checked")||child.checked))found.push(child);visit(child)}};visit(this);return found}});
const workflow={"1":{class_type:"LoadImage",inputs:{},_meta:{title:"IDENTITY_LAB_BASE_IMAGE"}},"2":{class_type:"LoadImage",inputs:{},_meta:{title:"IDENTITY_LAB_REFERENCE_IMAGE"}},"3":{class_type:"UNETLoader",inputs:{},_meta:{title:"IDENTITY_LAB_MODEL"}},"4":{class_type:"LoraLoader",inputs:{},_meta:{title:"IDENTITY_LAB_LORA_1"}},"5":{class_type:"LoraLoader",inputs:{},_meta:{title:"IDENTITY_LAB_LORA_2"}},"6":{class_type:"LoraLoader",inputs:{},_meta:{title:"IDENTITY_LAB_LORA_3"}},"7":{class_type:"KSampler",inputs:{},_meta:{title:"IDENTITY_LAB_SAMPLER"}},"8":{class_type:"DualIdentityScore",inputs:{},_meta:{title:"IDENTITY_LAB_SCORE"}},"9":{class_type:"ImageScaleToTotalPixels",inputs:{},_meta:{title:"IDENTITY_LAB_PIXEL_BUDGET"}}};
const run={id:"new-run",state:"queued",plan:{checkpoint:"flux.safetensors",loras:[],seed:1}}; const completed={id:"result-7",state:"completed",favorite:false,rating:null,plan:{checkpoint:"flux.safetensors",loras:[],seed:2},identity_report:{rankable:true,face_detection:{}}}; const detail={experiment:{id:"new-exp",settings:{workflow_template:workflow,setup:{mode:"face_swap",checkpoints:["flux.safetensors"],loras:[],seeds:[1],steps:28,cfg:3.5,denoise:.8,pixelBudget:1,sampler:"euler",scheduler:"simple"}}},runs:[run,completed]}; const failedRun={id:"failed-run",state:"planned",plan:{checkpoint:"flux.safetensors",loras:[],seed:3}}; const failedDetail={experiment:{...detail.experiment,id:"error-exp"},runs:[failedRun]};
const ok=(value)=>({ok:true,json:async()=>value}); let unhandled=[]; process.on("unhandledRejection",error=>unhandled.push(String(error)));
let creates=0;const backend={fetchApi:async(path,options={})=>{if(path.endsWith("/catalog"))return ok({diffusion_models:["flux.safetensors"],loras:[]});if(path.endsWith("/estimates")){const body=JSON.parse(options.body);return ok({run_count:body.run_count,estimated_seconds:1,estimated_bytes:1,free_bytes:1,time_source:"test",disk_source:"test",can_launch:true})}if(path==="/identity-lab/experiments"&&options.method==="POST")return ok(++creates===1?{experiment:detail.experiment,runs:detail.runs}:{experiment:failedDetail.experiment,runs:failedDetail.runs});if(path==="/identity-lab/experiments")return ok({experiments:[]});if(path==="/identity-lab/experiments/new-exp")return ok(detail);if(path==="/identity-lab/experiments/error-exp")return ok(failedDetail);if(path.endsWith("/queued")||path.endsWith("/failed"))return ok({state:"queued"});if(path==="/prompt")return {ok:false,status:422,json:async()=>({error:"prompt rejected"})};throw new Error(`unexpected ${path}`)}};
let sidebar;const app={registerExtension(){},extensionManager:{registerSidebarTab(value){sidebar=value}},graphToPrompt:async()=>({output:workflow})};const document={head:{append(){}},createElement:node};vm.runInNewContext(source,{app,api:backend,document,Option:function(text,value){const option=node("option");option.textContent=text;option.value=value;return option},URL,structuredClone,console,setTimeout,clearTimeout});
const root=node("section");sidebar.render(root);await new Promise(resolve=>setTimeout(resolve,10));const walk=(parent)=>{const all=[];const visit=value=>{for(const child of value.children||[]){all.push(child);visit(child)}};visit(parent);return all};const form=walk(root).find(value=>value.tagName==="form");await form.listeners.input();await new Promise(resolve=>setTimeout(resolve,10));await form.listeners.submit({preventDefault(){}});await new Promise(resolve=>setTimeout(resolve,0));
const status=walk(root).find(value=>value.attributes["aria-live"]==="polite");if(!status||!status.textContent.includes("queued or running"))throw new Error(`new experiment did not surface queue status: ${status&&status.textContent}`);if(!walk(root).some(value=>value.tagName==="article"))throw new Error("new experiment did not refresh gallery runs");
for(const name of ["mode","sampler","scheduler","name","seeds","steps","cfg","denoise","pixelBudget"]){const input=walk(root).find(value=>value.name===name);if(!input||!input.parent||input.parent.tagName!=="label")throw new Error(`missing visible associated label for ${name}`)}
const controls=walk(root); const selected=controls.find(value=>value.tagName==="input"&&value.parent&&value.parent.tagName==="article"); if(!selected||!selected.attributes["aria-label"].includes("result-7"))throw new Error("result selection has no contextual accessible name"); for(const [text,action] of [["5","Rate"],["☆","Favorite"],["Reject (1)","Reject"]]){const control=controls.find(value=>value.textContent===text&&value.listeners.click);if(!control||!control.attributes["aria-label"].includes("result-7")||!control.attributes["aria-label"].includes(action))throw new Error(`missing contextual accessible name for ${text}`)}
await form.listeners.submit({preventDefault(){}}); if(status.textContent!=="Error: prompt rejected")throw new Error(`new experiment did not surface queue error: ${status.textContent}`);
if(unhandled.length)throw new Error(`unhandled rejection: ${unhandled.join("\\n")}`);
})().catch(error=>{console.error(error.stack||error.message);process.exit(1)});
""".replace("__SCRIPT_PATH__", json.dumps(str(SCRIPT_PATH)))
    result = subprocess.run(["node", "-e", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
