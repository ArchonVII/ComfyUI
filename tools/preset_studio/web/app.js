import {referenceRequest, choicesFromReferences} from './reference-selection.mjs';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {presets: [], workflows: [], references: {}, runs: []};
let selected = [], references = [], category = 'all', editingPreset = null, editingWorkflow = null;
let referenceChoices = {}, referenceBatch = null;
let preview = null, models = {loras: [], nodes: {}}, previewVersion = 0, timer, busy = false;

async function api(path, data) {
  const response = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
function message(text) { $('toast').textContent = text; $('toast').hidden = false; clearTimeout(timer); timer = setTimeout(() => $('toast').hidden = true, 6500); }
function showError(id, error) { $(id).textContent = error?.message || error || ''; $(id).hidden = !error; }
function on(id, event, callback) { $(id).addEventListener(event, async e => { try { await callback(e); } catch (error) { message(error.message); } }); }
function pickedPresets() { return selected.map(id => state.presets.find(p => p.id === id)).filter(Boolean); }
function referenceSelection() { return referenceRequest(pickedPresets(), referenceChoices, referenceBatch); }
function request() { return {preset_ids:selected, ...referenceSelection(), extra:$('extra').value, negative:$('negative').value, workflow_id:$('workflow').value, seed:Number($('seed').value), count:referenceBatch?1:Number($('count').value)}; }
function remember() { try { localStorage.setItem('preset-studio-draft', JSON.stringify(request())); } catch { /* Server presets remain usable when browser storage is disabled. */ } }
async function load() { state = await api('state'); renderLibrary(); renderSelection(); renderWorkflows(); renderRuns(); $('comfy-url').value = state.comfy_url; }

function renderLibrary() {
  $('filters').innerHTML = [['all','All'],['character','Characters'],['concept','Concepts'],['environment','Places']].map(([key,label]) => `<button class="${category===key?'active':''}" data-filter="${key}" aria-pressed="${category===key}">${label}</button>`).join('');
  const search = $('search').value.toLowerCase();
  const presets = state.presets.filter(p => (category === 'all' || p.kind === category) && `${p.name} ${p.positive}`.toLowerCase().includes(search));
  $('preset-list').innerHTML = presets.map(p => `<div class="preset-card ${selected.includes(p.id)?'selected':''}"><button class="preset-pick" data-pick="${esc(p.id)}" aria-pressed="${selected.includes(p.id)}">${p.references.length ? `<img class="preset-icon" src="/api/reference/${encodeURIComponent(p.references[0])}" alt="" loading="lazy">` : `<span class="preset-icon">${p.kind==='character'?'◎':p.kind==='environment'?'⌂':'✦'}</span>`}<span><strong>${esc(p.name)}</strong><small>${esc(p.kind)}${p.references.length?' · '+p.references.length+' refs':''}${p.loras.length?' · '+p.loras.length+' LoRA':''}</small></span></button><button class="preset-edit" data-edit="${esc(p.id)}" aria-label="Edit ${esc(p.name)}">Edit</button></div>`).join('') || '<div class="empty">No presets. Use New or Import.</div>';
}
function renderSelection() {
  selected = selected.filter(id => state.presets.some(p => p.id === id));
  const picked = selected.map(id => state.presets.find(p => p.id === id));
  $('selection').innerHTML = picked.map((p,i) => `<button class="chip" data-remove="${esc(p.id)}" title="Remove from combination"><span>${i+1}</span>${esc(p.name)} ×</button>`).join('') || '<p class="hint">Click presets to combine them.</p>';
  for (const p of picked) if (!(p.id in referenceChoices)) referenceChoices[p.id] = p.references.slice(0,1);
  const selection = referenceSelection();
  references = selection.reference_ids;
  referenceBatch = selection.reference_batch || null;
  $('count').disabled = Boolean(referenceBatch);
  if (referenceBatch) $('count').value = '1';
  $('references').innerHTML = picked.filter(p=>p.kind==='character'||p.references.length).map(p=>{
    const batch = referenceBatch?.preset_id===p.id;
    const chosen = batch ? referenceBatch.image_ids : (referenceChoices[p.id] || []).filter(id=>p.references.includes(id)).slice(0,p.kind==='character'?1:undefined);
    return `<div class="reference-group"><div class="reference-tools"><strong>${esc(p.name)}</strong>${p.kind==='character'?`<select data-reference-mode="${esc(p.id)}" aria-label="Image mode for ${esc(p.name)}"><option value="single" ${!batch?'selected':''}>Single image</option><option value="each" ${batch?'selected':''}>Run each selected</option></select>`:''}${batch?`<button class="quiet small" data-ref-all="${esc(p.id)}">All</button><button class="quiet small" data-ref-none="${esc(p.id)}">None</button><span class="hint">${chosen.length} images → ${chosen.length} runs · same seed</span>`:''}<button class="quiet small" data-ref-edit="${esc(p.id)}">${p.references.length?'Edit images':'+ Add images'}</button></div><div class="reference-strip">${p.references.map(id=>`<button class="ref ${chosen.includes(id)?'selected':''}" data-ref="${esc(id)}" data-ref-preset="${esc(p.id)}" aria-pressed="${chosen.includes(id)}" title="${esc(state.references[id]?.name || 'Reference')}"><img src="/api/reference/${encodeURIComponent(id)}" alt="${esc(state.references[id]?.name || 'Reference')}" loading="lazy">${chosen.includes(id)?`<span>${batch?'✓':references.indexOf(id)+1}</span>`:''}<small>${esc(state.references[id]?.name||'Image')}</small></button>`).join('')||'<span class="hint">No images attached.</span>'}</div></div>`;
  }).join('') || '<p class="hint">Select a character to choose its reference image.</p>';
  $('ref-count').textContent = `${references.length} slots`;
}
function renderWorkflows() {
  $('queue').textContent=referenceBatch?`Queue ${referenceBatch.image_ids.length} images`:Number($('count').value)===1?'Queue test':`Queue ${$('count').value} variations`;
  $('download').textContent=referenceBatch?'Export first run JSON':'Export assembled JSON';
  const value = $('workflow').value;
  $('workflow').innerHTML = '<option value="">Choose a workflow…</option>' + state.workflows.map(w => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join('');
  if (state.workflows.some(w => w.id === value)) $('workflow').value = value;
  const workflow = state.workflows.find(w => w.id === $('workflow').value);
  $('map-workflow').disabled = !workflow;
  $('workflow-summary').textContent = workflow ? `${workflow.adapter.positive?.length||0} prompt fields · ${workflow.adapter.references?.length||0} references · ${workflow.adapter.seed?.length||0} seed fields${workflow.adapter.model?' · LoRA insertion mapped':''}` : 'Import an image or video API workflow, then map the fields this workspace controls.';
}
async function updatePreview() {
  const version = ++previewVersion;
  preview = null;
  $('queue').disabled = true;
  remember();
  const payload = request();
  try {
    const composed = await api('preview', {...payload, workflow_id:''});
    if (version !== previewVersion) return;
    const c = composed.composition;
    $('prompt-preview').textContent = c.positive || 'Select presets or type a prompt.';
    $('negative-preview').textContent = c.negative ? 'Negative: ' + c.negative : '';
    $('lora-count').textContent = `${c.loras.length} active`;
    $('lora-preview').innerHTML = c.loras.map(l => `<div class="lora-row">${esc(l.name)}<span>Model ${l.model} / CLIP ${l.clip}</span></div>`).join('') || '<p class="hint">None selected</p>';
    const result = payload.workflow_id ? await api('preview', payload) : composed;
    if (version !== previewVersion) return;
    preview = result;
    showError('preview-error', null);
    $('queue').disabled = busy || !preview.graph;
    $('download').disabled = !preview.graph;
  } catch(error) {
    if (version !== previewVersion) return;
    showError('preview-error', error);
    $('download').disabled = true;
  }
}
async function changed() { renderLibrary(); renderSelection(); renderWorkflows(); await updatePreview(); }
function renderRuns() {
  $('runs').innerHTML = state.runs.map(run => `<article class="run-card"><div class="run-meta"><span>Seed ${run.seed}</span><span class="status ${esc(run.status)}">${esc(run.status)}</span></div>${(run.outputs || []).map((asset,i) => {
    const url = `/api/output?run=${encodeURIComponent(run.id)}&index=${i}`;
    return /\.(mp4|webm|mov)$/i.test(asset.filename) ? `<video src="${url}" controls preload="metadata"></video>` : `<a href="${url}" target="_blank" rel="noopener"><img src="${url}" alt="Generated output, seed ${run.seed}" loading="lazy"></a>`;
  }).join('')}<h2>${esc(run.name)}</h2>${run.reference_id?`<div class="run-reference"><img src="/api/reference/${encodeURIComponent(run.reference_id)}" alt="Character reference" loading="lazy"><span>${esc(run.reference_label||"Character reference")}</span></div>`:""}<p class="run-prompt">${esc(run.composition.positive)}</p>${run.error?`<details><summary>Run error</summary><p class="error">${esc(run.error)}</p></details>`:''}<div class="button-row"><button data-restore="${esc(run.id)}">Restore as copy</button><button data-run-download="${esc(run.id)}">Save run JSON</button></div></article>`).join('') || '<div class="empty">No runs yet.</div>';
}
async function checkConnection() {
  const status = await api('status');
  $('connection').textContent = status.online ? 'ComfyUI connected' : 'ComfyUI offline';
  $('connection').classList.toggle('online', status.online);
  $('connection').title = status.online ? status.url : status.error;
  if(status.online) {
    models = await api('models');
    $('lora-names').innerHTML = models.loras.map(name => `<option value="${esc(name)}"></option>`).join('');
  }
}

function openPreset(id) {
  const existing = state.presets.find(p => p.id === id);
  editingPreset = existing ? structuredClone(existing) : {name:'',kind:'character',positive:'',negative:'',references:[],loras:[]};
  $('preset-title').textContent = existing ? 'Edit preset' : 'New preset';
  $('preset-name').value = editingPreset.name;
  $('preset-kind').value = editingPreset.kind;
  $('preset-positive').value = editingPreset.positive;
  $('preset-negative').value = editingPreset.negative;
  $('duplicate-preset').hidden = !existing;
  $('preset-files').value = '';
  showError('preset-error', null);
  renderEditorReferences(); renderEditorLoras();
  $('preset-dialog').showModal();
}
function renderEditorReferences() {
  $('editor-references').innerHTML = editingPreset.references.map(id => `<button type="button" class="ref" data-unlink="${esc(id)}" title="Remove from this preset"><img src="/api/reference/${encodeURIComponent(id)}" alt="${esc(state.references[id]?.name || 'Reference')}" loading="lazy"><span>×</span></button>`).join('') || '<p class="hint">Optional. Add several choices and pick the references you want when composing.</p>';
}
function renderEditorLoras() {
  $('editor-loras').innerHTML = editingPreset.loras.map((l,i) => `<div class="lora-editor"><div><label for="ln-${i}">Filename</label><input id="ln-${i}" data-lora="${i}" data-key="name" list="lora-names" value="${esc(l.name)}" placeholder="Choose or enter a LoRA" required></div><div><label for="lm-${i}">Model</label><input id="lm-${i}" data-lora="${i}" data-key="model" type="number" step="0.05" min="-10" max="10" value="${l.model??1}" required></div><div><label for="lc-${i}">CLIP</label><input id="lc-${i}" data-lora="${i}" data-key="clip" type="number" step="0.05" min="-10" max="10" value="${l.clip??1}" required></div><button type="button" data-remove-lora="${i}" aria-label="Remove LoRA">×</button></div>`).join('');
}
async function savePreset(asCopy=false) {
  if (!$('preset-form').reportValidity()) return;
  const data = {...editingPreset, name:$('preset-name').value, kind:$('preset-kind').value, positive:$('preset-positive').value, negative:$('preset-negative').value};
  if (asCopy) { delete data.id; data.name += ' copy'; }
  try {
    const saved = await api('preset', data);
    await load();
    if (!editingPreset.id) selected.push(saved.id);
    if (!(referenceChoices[saved.id]||[]).some(id=>saved.references.includes(id))) referenceChoices[saved.id]=saved.references.slice(0,1);
    $('preset-dialog').close(); await changed(); message('Preset saved');
  } catch(error) { showError('preset-error', error); }
}

function inferFields(graph) {
  return Object.entries(graph).flatMap(([node,n]) => Object.entries(n.inputs||{}).filter(([,v]) => !Array.isArray(v) && typeof v !== 'object').map(([input,value]) => ({binding:`${node}.${input}`,node,input,value,title:n._meta?.title||n.class_type,class_type:n.class_type})));
}
function openWorkflow(id) {
  const existing = state.workflows.find(w => w.id === id);
  editingWorkflow = existing ? structuredClone(existing) : {name:'',graph:{},adapter:{positive:[],negative:[],references:[],seed:[],model:null,clip:null},fields:[]};
  $('workflow-title').textContent = existing ? 'Map workflow controls' : 'Import API workflow';
  $('workflow-name').value = editingWorkflow.name;
  $('workflow-file').value = '';
  showError('workflow-error', null); renderMapping(); $('workflow-dialog').showModal();
}
function renderMapping() {
  if(!Object.keys(editingWorkflow.graph).length) { $('workflow-mapping').innerHTML = ''; return; }
  const adapter = editingWorkflow.adapter;
  const rows = editingWorkflow.fields || inferFields(editingWorkflow.graph);
  const role = binding => {
    for(const key of ['positive','negative','seed']) if(adapter[key]?.includes(binding)) return key;
    const slot = adapter.references?.indexOf(binding) ?? -1;
    return slot >= 0 ? `ref${slot}` : '';
  };
  const choices = [['','Keep workflow value'],['positive','Positive prompt'],['negative','Negative prompt'],['seed','Variation seed'],['ref0','Reference 1'],['ref1','Reference 2'],['ref2','Reference 3'],['ref3','Reference 4']];
  $('workflow-mapping').innerHTML = '<h2>Fields controlled by Studio</h2>' + rows.map(f => `<div class="mapping-row"><div>${esc(f.title)}<small>${esc(f.binding)} · ${esc(String(f.value).slice(0,100))}</small></div><select data-binding="${esc(f.binding)}" aria-label="Map ${esc(f.binding)}">${choices.map(([value,label]) => `<option value="${value}" ${role(f.binding)===value?'selected':''}>${label}</option>`).join('')}</select></div>`).join('') + '<div class="preview-head"><h2>Preset LoRA insertion</h2></div><p class="hint">Choose the MODEL output feeding sampling, and its CLIP output when applicable. Studio inserts the ordered LoRA stack after these outputs. Leave CLIP empty for model-only LoRAs.</p>' + ['model','clip'].map(type => {
    const options = Object.entries(editingWorkflow.graph).flatMap(([id,node]) => {
      let outputs = models.nodes[node.class_type]?.output;
      if (!outputs) outputs = {CheckpointLoaderSimple:['MODEL','CLIP','VAE'],UNETLoader:['MODEL'],CLIPLoader:['CLIP'],DualCLIPLoader:['CLIP'],LoraLoader:['MODEL','CLIP'],LoraLoaderModelOnly:['MODEL']}[node.class_type] || [];
      return outputs.map((out,slot) => ({out,slot,id,title:node._meta?.title||node.class_type})).filter(o => o.out.toLowerCase()===type);
    });
    return `<label for="insert-${type}">${type.toUpperCase()} source</label><select id="insert-${type}"><option value="">No insertion</option>${options.map(o => `<option value="${esc(o.id)}:${o.slot}" ${JSON.stringify(adapter[type])===JSON.stringify([o.id,o.slot])?'selected':''}>${esc(o.id)} · ${esc(o.title)} · output ${o.slot}</option>`).join('')}</select>`;
  }).join('');
}

on('filters','click', async e => { const button=e.target.closest('[data-filter]'); if(button) { category=button.dataset.filter; renderLibrary(); } });
on('search','input', renderLibrary);
on('preset-list','click', async e => {
  const edit=e.target.closest('[data-edit]'); if(edit) return openPreset(edit.dataset.edit);
  const pick=e.target.closest('[data-pick]'); if(!pick) return;
  const id=pick.dataset.pick;
  if(selected.includes(id)) selected=selected.filter(x=>x!==id);
  else selected.push(id);
  await changed();
});
on('selection','click', async e => { const b=e.target.closest('[data-remove]'); if(b) { selected=selected.filter(id=>id!==b.dataset.remove); await changed(); } });
on('references','click', async e => {
  const edit=e.target.closest('[data-ref-edit]');if(edit)return openPreset(edit.dataset.refEdit);
  const all=e.target.closest('[data-ref-all]'), none=e.target.closest('[data-ref-none]');
  if(all||none){const id=(all||none).dataset[all?'refAll':'refNone'];const p=state.presets.find(p=>p.id===id);referenceBatch={preset_id:id,image_ids:all?[...p.references]:[]};await changed();return;}
  const b=e.target.closest('[data-ref]');if(!b)return;
  const id=b.dataset.ref,pid=b.dataset.refPreset,preset=state.presets.find(p=>p.id===pid);
  if(referenceBatch?.preset_id===pid){const images=referenceBatch.image_ids;referenceBatch.image_ids=images.includes(id)?images.filter(x=>x!==id):[...images,id];}
  else if(preset.kind==='character')referenceChoices[pid]=[id];
  else {const choices=referenceChoices[pid]||[];referenceChoices[pid]=choices.includes(id)?choices.filter(x=>x!==id):[...choices,id];}
  await changed();
});
on('references','change',async e=>{
  const pid=e.target.dataset.referenceMode;if(!pid)return;
  if(e.target.value==='each'){
    if(referenceBatch){referenceChoices[referenceBatch.preset_id]=referenceBatch.image_ids.slice(0,1);message('One character group per batch; other references stay fixed.');}
    referenceBatch={preset_id:pid,image_ids:(referenceChoices[pid]||[]).slice(0,1)};
  }else{referenceChoices[pid]=referenceBatch?.image_ids.slice(0,1)||referenceChoices[pid]||[];referenceBatch=null;}
  await changed();
});
on('clear','click', async()=>{ selected=[]; references=[]; referenceChoices={};referenceBatch=null; $('extra').value=''; $('negative').value=''; await changed(); });
let debounce;
for(const id of ['extra','negative','seed']) on(id,'input',()=>{ $('queue').disabled=true; clearTimeout(debounce); debounce=setTimeout(updatePreview,220); });
on('workflow','change',async()=>{renderWorkflows(); await updatePreview();});
on('count','change',async()=>{renderWorkflows();await updatePreview();});
on('random-seed','click',async()=>{ $('seed').value=crypto.getRandomValues(new Uint32Array(1))[0]; await updatePreview(); });
on('copy-prompt','click',async()=>{ await navigator.clipboard.writeText($('prompt-preview').textContent); message('Prompt copied'); });
on('new-preset','click',()=>openPreset());
on('preset-form','submit',async e=>{e.preventDefault();await savePreset();});
on('duplicate-preset','click',()=>savePreset(true));
on('add-lora','click',()=>{editingPreset.loras.push({name:'',model:1,clip:1});renderEditorLoras();});
on('editor-loras','input',e=>{ if(e.target.dataset.lora!==undefined) editingPreset.loras[Number(e.target.dataset.lora)][e.target.dataset.key]=e.target.dataset.key==='name'?e.target.value:Number(e.target.value); });
on('editor-loras','click',e=>{const b=e.target.closest('[data-remove-lora]');if(b){editingPreset.loras.splice(Number(b.dataset.removeLora),1);renderEditorLoras();}});
on('editor-references','click',e=>{const b=e.target.closest('[data-unlink]');if(b){editingPreset.references=editingPreset.references.filter(id=>id!==b.dataset.unlink);renderEditorReferences();}});
on('preset-files','change',async e=>{
  const files=[...e.target.files];
  const save=$('preset-form').querySelector('[type=submit]'); save.disabled=true;
  try {
    for(const file of files) {
      if(file.size>20*1024*1024) throw new Error(`${file.name} exceeds 20 MB`);
      const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
      const ref=await api('upload',{name:file.name,content}); editingPreset.references.push(ref.id);state.references[ref.id]={name:ref.name};
    }
    renderEditorReferences();
  } finally {save.disabled=false;e.target.value='';}
});
on('add-workflow','click',()=>openWorkflow());
on('map-workflow','click',()=>openWorkflow($('workflow').value));
on('workflow-file','change',async e=>{
  const file=e.target.files[0]; if(!file)return;
  try {
    const graph=JSON.parse(await file.text());
    if(!graph || Array.isArray(graph) || graph.nodes || !Object.keys(graph).length || Object.values(graph).some(n=>!n.class_type || !n.inputs)) throw new Error('Choose an API-format workflow export, not the editor JSON.');
    editingWorkflow.graph=graph; editingWorkflow.fields=inferFields(graph);
    const adapter={positive:[],negative:[],references:[],seed:[],model:null,clip:null};
    for(const f of editingWorkflow.fields) {
      if(['seed','noise_seed'].includes(f.input) && typeof f.value==='number')adapter.seed.push(f.binding);
      if(f.class_type==='LoadImage' && f.input==='image')adapter.references.push(f.binding);
      if(f.class_type==='CLIPTextEncode' && f.input==='text')adapter[/negative/i.test(f.title)?'negative':'positive'].push(f.binding);
    }
    editingWorkflow.adapter=adapter;
    if(!$('workflow-name').value)$('workflow-name').value=file.name.replace(/\.json$/i,'');
    showError('workflow-error',null);renderMapping();
  }catch(error){showError('workflow-error',error);}
});
on('workflow-form','submit',async e=>{
  e.preventDefault();
  try {
    if(!Object.keys(editingWorkflow.graph).length)throw new Error('Choose an API workflow JSON first.');
    const adapter={positive:[],negative:[],references:[],seed:[],model:null,clip:null};
    for(const input of $('workflow-mapping').querySelectorAll('[data-binding]')) {
      if(!input.value)continue;
      if(input.value.startsWith('ref')) {const index=Number(input.value.slice(3));if(adapter.references[index])throw new Error(`Reference ${index+1} is assigned twice.`);adapter.references[index]=input.dataset.binding;}
      else adapter[input.value].push(input.dataset.binding);
    }
    for(let i=0;i<adapter.references.length;i++)if(!adapter.references[i])throw new Error('Reference slots must start at 1 with no gaps.');
    for(const type of ['model','clip']) {const value=$('insert-'+type)?.value;if(value){const [node,slot]=value.split(':');adapter[type]=[node,Number(slot)];}}
    const saved=await api('workflow',{...editingWorkflow,name:$('workflow-name').value,adapter});
    await load();$('workflow').value=saved.id;$('workflow-dialog').close();await changed();message('Workflow mapping saved');
  }catch(error){showError('workflow-error',error);}
});
on('import-library','click',async()=>{
  $('library-dialog').showModal();$('library-items').textContent='Reading local library…';
  try {
    const library=await api('library');
    $('library-items').innerHTML='<h2>Character / environment collections</h2>'+(library.collections.map(c=>`<div class="library-row"><span>${esc(c.name)} · ${esc(c.kind)}</span><button data-import-collection="${esc(c.id)}">Import preset</button></div>`).join('')||'<p class="hint">No Reference Library collections found. Create a character preset and add images instead.</p>')+'<h2 class="preview-head">Saved API workflows</h2>'+library.workflows.map(w=>`<div class="library-row"><span>${esc(w)}</span><button data-import-workflow="${esc(w)}">Import copy</button></div>`).join('');
  }catch(error){$('library-items').textContent=error.message;}
});
on('library-items','click',async e=>{
  const b=e.target.closest('[data-import-collection],[data-import-workflow]');if(!b)return;b.disabled=true;
  try {
    const isWorkflow=Boolean(b.dataset.importWorkflow);
    const saved=await api('import',isWorkflow?{workflow:b.dataset.importWorkflow}:{collection:b.dataset.importCollection});
    await load();$('library-dialog').close();
    if(isWorkflow){$('workflow').value=saved.id;openWorkflow(saved.id);}else openPreset(saved.id);
    await changed();
  }finally{b.disabled=false;}
});
on('queue','click',async()=>{
  if(busy)return;busy=true;$('queue').disabled=true;$('queue-status').textContent='Validating and submitting to local ComfyUI…';
  try {
    const payload=request(),expected=payload.reference_batch?.image_ids.length||payload.count;
    const result=await api('submit',payload);
    const queued=result.runs.filter(r=>r.status==='queued').length;
    $('queue-status').textContent=`${queued} of ${expected} runs queued.${queued<expected?' Submission stopped; see the run error below.':''}`;
    await load();renderRuns();
  }finally{busy=false;await updatePreview();}
});
on('refresh','click',async()=>{state.runs=await api('refresh',{});renderRuns();});
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
on('download','click',()=>{if(preview?.graph)download(preview.graph,'preset-studio-api.json');});
on('runs','click',async e=>{
  const restore=e.target.closest('[data-restore]');
  if(restore){const saved=await api('restore',{id:restore.dataset.restore});await load();selected=saved.preset_ids;references=saved.reference_ids;referenceChoices=choicesFromReferences(pickedPresets(),references);referenceBatch=null;$('extra').value=saved.extra;$('negative').value=saved.negative;$('workflow').value=saved.workflow_id;$('seed').value=saved.seed;$('count').value='1';await changed();message('Restored the saved configuration as independent copies');return;}
  const button=e.target.closest('[data-run-download]');if(button)download(await api('run',{id:button.dataset.runDownload}),'preset-studio-run.json');
});
on('connection','click',()=>{document.querySelector('.workflow-setup').open=true;document.querySelector('.connection-details').open=true;$('comfy-url').focus();});
on('save-connection','click',async()=>{await api('settings',{comfy_url:$('comfy-url').value});await checkConnection();message('Local connection saved');});
document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>$(b.dataset.close).close()));

async function start(){
  await load();
  try {const draft=JSON.parse(localStorage.getItem('preset-studio-draft')||'null');if(draft){selected=draft.preset_ids||[];references=draft.reference_ids||[];referenceChoices=choicesFromReferences(pickedPresets(),references);referenceBatch=draft.reference_batch||null;$('extra').value=draft.extra||'';$('negative').value=draft.negative||'';$('workflow').value=draft.workflow_id||'';$('seed').value=draft.seed??1;$('count').value=draft.count||1;}else if(state.workflows.length===1){$('workflow').value=state.workflows[0].id;}}catch{/* A broken browser draft never replaces server data. */}
  await changed();await checkConnection();
  if(document.modelContext?.registerTool){
    const lifecycle=new AbortController();
    addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
    try{await document.modelContext.registerTool({
      name:'stage_studio_combination',title:'Stage a preset combination',
      description:'Select existing Studio presets by exact name and update the visible prompt preview. Does not queue generation.',
      inputSchema:{type:'object',properties:{names:{type:'array',items:{type:'string'}},extra:{type:'string'}},required:['names'],additionalProperties:false},
      annotations:{readOnlyHint:false,untrustedContentHint:true},
      async execute(input){
        if(!input || !Array.isArray(input.names) || input.names.some(n=>typeof n!=='string') || (input.extra!==undefined && typeof input.extra!=='string'))throw new Error('Provide preset names and optional extra text.');
        const matches=input.names.map(name=>{const found=state.presets.filter(p=>p.name===name);if(found.length!==1)throw new Error(`Preset name is missing or ambiguous: ${name}`);return found[0];});
        selected=[...new Set(matches.map(p=>p.id))];referenceChoices=Object.fromEntries(matches.map(p=>[p.id,p.references.slice(0,1)]));referenceBatch=null;$('extra').value=input.extra||'';
        await changed();return {staged:true,presets:matches.map(p=>p.name),positive:$('prompt-preview').textContent,validationError:$('preview-error').hidden?null:$('preview-error').textContent};
      }
    },{signal:lifecycle.signal});}catch{/* Optional agent integration must not block the workspace. */}
  }
  setInterval(async()=>{if(!busy && !document.hidden && state.runs.some(r=>['queued','running'].includes(r.status))){try{state.runs=await api('refresh',{});renderRuns();}catch{/* Preserve visible runs while the backend is unavailable. */}}},6000);
}
start().catch(error=>{showError('preview-error',error);message('Could not load the workspace: '+error.message);});
