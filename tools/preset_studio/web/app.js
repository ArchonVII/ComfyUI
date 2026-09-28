import {referenceRequest, choicesFromReferences} from './reference-selection.mjs';
import {CHARACTER_VIEWS, DESTINATIONS, createReviewQueueViewModel, createScopedSelectionViewModel, createStudioViewModel} from './studio-view-model.mjs';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {presets: [], workflows: [], references: {}, runs: []};
let selected = [], references = [], category = 'all', editingPreset = null, editingWorkflow = null;
let referenceChoices = {}, referenceBatch = null;
let preview = null, models = {loras: [], nodes: {}}, previewVersion = 0, timer, busy = false;
let folderBrowse = {characterId: null, mode: 'assign', path: '', parent: '', folders: []};
let activeDiscoveryJobId = null;
const discoveryCache = new Map();
const duplicateCache = new Map();
const quarantineHistoryCache = new Map();
const familyCache = new Map();
const characterImageCache = new Map();
const characterImageTotal = new Map();
const galleryFilters = new Map();
const assignmentJobCache = new Map();
const assignmentPolls = new Set();
let lastQuarantineOperation = null;
let builderState = {experiments: [], revisions: []}, builderCatalog = [], activeBuilderOptionId = null, selectedBuilderNodeId = null;
const studioViewModel = createStudioViewModel();
const reviewQueueViewModel = createReviewQueueViewModel();
const imageSelectionViewModel = createScopedSelectionViewModel();
let gallerySearchTimer = null;

function galleryFilter(characterId) { return galleryFilters.get(characterId)||{query:'',sort:'newest'}; }

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
async function load() { state = await api('state'); for(const character of state.characters||[]){const job=character.assignment_jobs?.[0];if(job){assignmentJobCache.set(character.id,job);if(['pending','running'].includes(job.state))watchAssignmentJob(job.id,character.id);}} studioViewModel.hydrate(state); renderLibrary(); renderSelection(); renderWorkflows(); renderRuns(); $('comfy-url').value = state.comfy_url; }

function renderShell(snapshot) {
  $('app-nav').innerHTML = DESTINATIONS.map(destination => `<button class="${destination.id===snapshot.activeDestination?'active':''}" data-destination="${destination.id}" aria-current="${destination.id===snapshot.activeDestination?'page':'false'}">${destination.label}</button>`).join('');
  for (const view of document.querySelectorAll('[data-view]')) view.hidden = view.dataset.view !== snapshot.activeDestination;
}

function renderCharacters() {
  const snapshot = studioViewModel.snapshot;
  const search = $('character-search').value.toLowerCase();
  const characters = snapshot.catalog.characters.filter(character => `${character.name} ${character.positive}`.toLowerCase().includes(search));
  $('character-list').innerHTML = characters.map(character => {
    const preset = state.presets.find(item => item.id === character.preset_id);
    const reference = preset?.references?.[0];
    return `<button class="character-row ${character.id===snapshot.selectedCharacterId?'selected':''}" data-character-select="${esc(character.id)}">${reference?`<img src="/api/reference/${encodeURIComponent(reference)}" alt="" loading="lazy">`:'<span class="character-avatar">◎</span>'}<span><strong>${esc(character.name)}</strong><small>${character.asset_count} images</small></span><span class="row-arrow">›</span></button>`;
  }).join('') || '<div class="empty">No matching characters.</div>';
}

function renderCharacterWorkspace(snapshot = studioViewModel.snapshot) {
  const character = snapshot.catalog.characters.find(item => item.id === snapshot.selectedCharacterId);
  if (!character) {
    $('character-workspace').innerHTML = '<div class="empty-state"><strong>Select a character</strong><p>Choose a character from the rail or create one to manage its images.</p></div>';
    return;
  }
  const availableViews = new Set(['overview', 'images', 'families', 'sources', 'find', 'review']);
  const tabs = CHARACTER_VIEWS.map(view => `<button data-character-view="${view.id}" class="${view.id===snapshot.activeCharacterView?'active':''}" ${availableViews.has(view.id)?'': 'disabled'}>${view.label}</button>`).join('');
  const latestJob = (character.discovery_jobs || [])[0];
  const jobId = activeDiscoveryJobId || latestJob?.id;
  const discovery = jobId ? discoveryCache.get(jobId) : null;
  let body;
  if (snapshot.activeCharacterView === 'images') {
    const groups = duplicateCache.get(character.id);
    const quarantineHistory = quarantineHistoryCache.get(character.id) || [];
    const images = characterImageCache.get(character.id);
    const selectedImages = imageSelectionViewModel.selectedIds();
    const assignmentJob = assignmentJobCache.get(character.id);
    const filter = galleryFilter(character.id);
    const imageTotal = characterImageTotal.get(character.id) ?? character.asset_count;
    const duplicateSection = groups===undefined?'<div class="empty">Loading exact-copy review…</div>':groups.length?`<details class="duplicate-review" open><summary>${groups.length} exact-copy group${groups.length===1?'':'s'} need review</summary><div class="duplicate-groups">${groups.map(group=>`<article class="duplicate-group"><img src="/api/character/thumbnail/${encodeURIComponent(group.asset_id)}?size=256" alt="Exact duplicate preview" loading="lazy"><div><h2>${group.copy_count} byte-exact copies</h2><p class="hint">SHA-256 ${esc(group.sha256.slice(0,12))}… · ${group.size_bytes} bytes</p><div class="duplicate-locations">${group.locations.map(location=>`<div><span title="${esc(location.path)}">${esc(location.path)}</span>${location.id===group.recommended_keeper.id?'<strong>Keep</strong>':`<button class="danger" data-quarantine-location="${esc(location.id)}">Quarantine copy</button>`}</div>`).join('')}</div></div></article>`).join('')}</div></details>`:'<p class="duplicate-clear">✓ No byte-exact copies need review</p>';
    const galleryControls=`<div class="gallery-controls"><input data-image-search value="${esc(filter.query)}" placeholder="Search filenames or folders" aria-label="Search character images"><select data-image-sort aria-label="Sort character images"><option value="newest" ${filter.sort==='newest'?'selected':''}>Newest first</option><option value="oldest" ${filter.sort==='oldest'?'selected':''}>Oldest first</option><option value="name" ${filter.sort==='name'?'selected':''}>Filename</option><option value="largest" ${filter.sort==='largest'?'selected':''}>Largest file</option></select>${filter.query?'<button class="quiet" data-image-search-clear>Clear search</button>':''}</div>`;
    const gallery = images===undefined?galleryControls+'<div class="empty-state"><strong>Loading character gallery…</strong></div>':images.length?`${galleryControls}<div class="image-batch-actions"><span>${selectedImages.length} selected · ${imageTotal} matching</span><button class="quiet" data-image-toggle="all">Select loaded</button><button class="quiet" data-image-toggle="none" ${selectedImages.length?'':'disabled'}>Clear</button><button class="accent" data-family-from-selection="${esc(character.id)}" ${selectedImages.length?'':'disabled'}>Create family</button></div><div class="character-gallery">${images.map(item=>`<figure class="${imageSelectionViewModel.isSelected(item.id)?'selected':''}"><input class="image-card-select" type="checkbox" data-image-select="${esc(item.id)}" ${imageSelectionViewModel.isSelected(item.id)?'checked':''} aria-label="Select ${esc(item.original_name)}"><button class="image-preview" data-view-asset="${esc(item.id)}" data-view-name="${esc(item.original_name)}"><img src="/api/character/thumbnail/${encodeURIComponent(item.id)}?size=320" alt="${esc(item.original_name)}" loading="lazy"></button><figcaption><strong>${esc(item.original_name)}</strong><span>${esc(item.assignment_type)}</span><div class="card-actions"><button data-use-builder="${esc(item.id)}" data-builder-character="${esc(character.id)}">Use in Builder</button><button data-use-compose="${esc(item.id)}" data-compose-character="${esc(character.id)}">Use in Compose</button></div></figcaption></figure>`).join('')}</div>${images.length<imageTotal?`<button class="load-more" data-images-more>Load more · ${images.length} of ${imageTotal}</button>`:''}`:`${galleryControls}<div class="empty-state"><strong>${filter.query?'No matching images':'No assigned images yet'}</strong><p>${filter.query?'Try a different filename or folder search.':'Add a local folder or accept discovery recommendations.'}</p></div>`;
    const quarantineSection = quarantineHistory.length?`<details class="quarantine-history"><summary>Recoverable deletion history · ${quarantineHistory.filter(item=>item.state!=='restored').length} in quarantine</summary>${quarantineHistory.slice(0,20).map(item=>`<div><span title="${esc(item.original_path)}">${esc(item.original_path)}</span><strong>${esc(item.state==='database_done'?'quarantined':item.state)}</strong>${item.state==='database_done'?`<button data-restore-quarantine="${esc(item.id)}">Restore</button>`:''}</div>`).join('')}</details>`:'';
    const assignmentStatus = assignmentJob?`<div class="assignment-status ${esc(assignmentJob.state)}"><div><strong>${assignmentJob.state==='completed'?'Folder assignment complete':'Assigning folder images'}</strong><span>${assignmentJob.processed_count}/${assignmentJob.found_count||'?'} checked · ${assignmentJob.assigned_count} new · ${assignmentJob.already_assigned_count} already known</span></div>${assignmentJob.state==='running'?'<span class="busy-dot">●</span>':''}${assignmentJob.error?`<button class="quiet" data-assignment-error title="${esc(assignmentJob.error)}">${assignmentJob.error_count} errors</button>`:''}</div>`:'';
    body = `<div class="image-summary"><div><strong>${character.asset_count}</strong><span>assigned images</span></div><button data-open-folder="${esc(character.id)}" class="accent">Add images from folder</button></div>${assignmentStatus}${lastQuarantineOperation?`<div class="quarantine-banner"><span>A duplicate copy was moved to recoverable quarantine.</span><button data-restore-quarantine="${esc(lastQuarantineOperation.id)}">Restore</button></div>`:''}${duplicateSection}${quarantineSection}${gallery}`;
  } else if (snapshot.activeCharacterView === 'families') {
    const families = familyCache.get(character.id);
    body = `<div class="family-toolbar"><div><strong>Image families</strong><span>Membership and source choice stay independent.</span></div><button class="accent" data-new-family="${esc(character.id)}">New family</button></div>${families===undefined?'<div class="empty-state"><strong>Loading image families…</strong></div>':families.length?`<div class="family-grid">${families.map(family=>`<article class="family-card"><header><div><h2>${esc(family.name)}</h2><span>${family.members.length} images</span></div><div class="button-row">${family.designated_source_id?'<strong class="source-badge">Source set</strong>':'<span class="hint">No source selected</span>'}<button class="quiet" data-edit-family="${esc(family.id)}">Edit members</button></div></header><div class="family-strip">${family.members.map(member=>`<div class="family-member ${member.asset_id===family.designated_source_id?'designated':''} ${member.asset_id===family.recommended_source_id?'recommended-source':''}"><img src="/api/character/thumbnail/${encodeURIComponent(member.asset_id)}?size=256" alt="Family member" loading="lazy"><span>${member.width?`${member.width}×${member.height}`:'Dimensions unavailable'}</span>${member.asset_id===family.designated_source_id?'<strong>Source</strong>':`<button data-family-source="${esc(family.id)}" data-source-asset="${esc(member.asset_id)}" class="${member.asset_id===family.recommended_source_id?'recommended':''}">${member.asset_id===family.recommended_source_id?'Use recommended':'Use as source'}</button>`}${member.generated_count?`<button class="lineage-button" data-view-lineage="${esc(member.asset_id)}">View ${member.generated_count} generated</button>`:''}</div>`).join('')}</div></article>`).join('')}</div>`:'<div class="empty-state"><strong>No image families yet</strong><p>Group variations together, then designate or replace the best source independently.</p><button class="accent" data-new-family="'+esc(character.id)+'">Create first family</button></div>'}`;
  } else if (snapshot.activeCharacterView === 'sources') {
    const families = familyCache.get(character.id);
    if(families===undefined)body='<div class="empty-state"><strong>Loading character sources…</strong></div>';
    else {
      const sources=families.map(family=>{const member=family.members.find(item=>item.asset_id===family.designated_source_id);return member?{family,member}:null;}).filter(Boolean);
      const suggestions=families.filter(family=>!family.designated_source_id&&family.recommended_source_id).map(family=>({family,member:family.members.find(item=>item.asset_id===family.recommended_source_id)}));
      body=`<div class="source-toolbar"><div><strong>Designated source images</strong><span>These are the intentional generation anchors for ${esc(character.name)}.</span></div><button data-new-family="${esc(character.id)}">New family</button></div>${sources.length?`<div class="source-grid">${sources.map(({family,member})=>`<article><img src="/api/character/thumbnail/${encodeURIComponent(member.asset_id)}?size=320" alt="${esc(family.name)} source" loading="lazy"><div><p class="eyebrow">${esc(family.name)}</p><strong>${esc(member.original_name)}</strong><span>${member.width?`${member.width}×${member.height}`:'Dimensions unavailable'} · ${member.generated_count} generated</span><div class="button-row"><button data-use-builder="${esc(member.asset_id)}" data-builder-character="${esc(character.id)}">Use in Builder</button><button data-use-compose="${esc(member.asset_id)}" data-compose-character="${esc(character.id)}">Use in Compose</button><button class="lineage-button" data-view-lineage="${esc(member.asset_id)}">Generated gallery</button></div></div></article>`).join('')}</div>`:'<div class="empty-state"><strong>No sources designated yet</strong><p>Set a source in a family, or accept a recommended source below.</p></div>'}${suggestions.length?`<section class="source-suggestions"><h2>Recommended sources</h2>${suggestions.map(({family,member})=>`<article><img src="/api/character/thumbnail/${encodeURIComponent(member.asset_id)}?size=192" alt="Recommended source" loading="lazy"><span><strong>${esc(family.name)}</strong><small>${member.width}×${member.height} · highest-resolution member</small></span><button class="recommended" data-family-source="${esc(family.id)}" data-source-asset="${esc(member.asset_id)}">Assign recommended</button></article>`).join('')}</section>`:''}`;
    }
  } else if (snapshot.activeCharacterView === 'find') {
    body = `<section class="discovery-panel"><div><p class="eyebrow">Manual discovery</p><h2>Search only when you ask</h2><p class="hint">Choose a local folder, review the recursion setting, then start. Background watching remains off.</p></div><button class="accent" data-find-folder="${esc(character.id)}">Choose folder and scan</button></section><div class="job-list">${(character.discovery_jobs||[]).map(job=>`<button data-review-job="${esc(job.id)}"><span><strong>${esc(job.state)}</strong><small>${esc(job.root_path)}</small></span><span>${job.processed_count}/${job.found_count} · ${job.matched_count} matches</span></button>`).join('')||'<div class="empty">No scans have been started.</div>'}</div>`;
  } else if (snapshot.activeCharacterView === 'review') {
    if (!jobId) body = '<div class="empty-state"><strong>No review queue yet</strong><p>Run Find New Pics to create an explicit review queue.</p></div>';
    else if (!discovery) body = '<div class="empty-state"><strong>Loading review queue…</strong></div>';
    else {
      const job = discovery.job;
      const pending = discovery.review.filter(item=>item.decision==='pending');
      const selectedCount = reviewQueueViewModel.selectedIds().length;
      body = `<div class="review-toolbar"><div><strong>${esc(job.state)}</strong><span>${job.processed_count}/${job.found_count} scanned · ${discovery.pending_total} pending · ${selectedCount} selected</span></div><div class="button-row">${pending.length?'<button class="quiet" data-review-toggle="all">Select visible</button><button class="quiet" data-review-toggle="none">Clear visible</button><button data-review-decision="deferred">Defer selected</button><button class="danger" data-review-decision="rejected">Reject selected</button>':''}${['pending','running'].includes(job.state)?'<button class="danger" data-cancel-discovery>Cancel scan</button>':''}<button data-assign-recommended ${selectedCount?'':'disabled'}>Assign selected (${selectedCount})</button><button class="recommended" data-assign-all ${discovery.pending_total?'':'disabled'}>Assign all pending (${discovery.pending_total})</button></div></div>${job.error?`<p class="error">${esc(job.error)}</p>`:''}<div class="review-grid">${discovery.review.map(item=>`<label class="review-card ${esc(item.decision)}"><input type="checkbox" data-review-select="${esc(item.id)}" ${item.decision==='pending'?(reviewQueueViewModel.isSelected(item.id)?'checked':''):'disabled'}><div class="review-evidence"><img src="/api/character/thumbnail/${encodeURIComponent(item.asset_id)}?size=256" alt="Full image context" loading="lazy"><img src="/api/character/review-face/${encodeURIComponent(item.id)}?size=192" alt="Matched face crop" loading="lazy"><span>Face</span></div><span><strong>${Number(item.score).toFixed(3)} similarity</strong><small>${esc(item.original_name)} · face ${item.face_index+1} · ${Math.round(Number(item.face_confidence)*100)}% detection</small></span></label>`).join('')||`<div class="empty-state"><strong>${job.state==='completed'?'No likely matches':'Scanning local images…'}</strong><p>${job.error?esc(job.error):'This queue updates as the explicit scan progresses.'}</p></div>`}</div>${discovery.review.length<discovery.review_total?`<button class="load-more" data-review-more>Load more · ${discovery.review.length} of ${discovery.review_total}</button>`:''}`;
      if(discovery.errors?.length)body+=`<details class="scan-errors"><summary>${discovery.errors.length} files could not be analyzed</summary>${discovery.errors.map(item=>`<div><strong>${esc(item.path)}</strong><span>${esc(item.error)}</span></div>`).join('')}</details>`;
    }
  } else {
    body = `<div class="character-overview"><article><span>Assigned images</span><strong>${character.asset_count}</strong></article><article><span>Families</span><strong>—</strong></article><article><span>Needs review</span><strong>${latestJob?.matched_count||0}</strong></article></div>`;
  }
  $('character-workspace').innerHTML = `<div class="workspace-header"><div><p class="eyebrow">Character catalog</p><h1>${esc(character.name)}</h1></div><div class="button-row"><button data-edit-character="${esc(character.preset_id)}">Edit preset</button><button data-open-folder="${esc(character.id)}">Add folder</button><button class="accent" data-find-folder="${esc(character.id)}">Find New Pics</button></div></div><div class="workspace-tabs" aria-label="Character workspace sections">${tabs}</div>${body}`;
}

async function refreshDiscovery(jobId, append = false) {
  const existing = discoveryCache.get(jobId);
  const offset = append ? (existing?.review.length || 0) : 0;
  const limit = append ? 250 : Math.max(250, Math.min(existing?.review.length || 0, 1000));
  const result = await api('character/discovery', {job_id: jobId, limit, offset});
  if (append && existing) {
    const byId = new Map([...existing.review, ...result.review].map(item=>[item.id,item]));
    result.review = [...byId.values()];
  }
  reviewQueueViewModel.hydrate(jobId, result.review);
  discoveryCache.set(jobId, result);
  activeDiscoveryJobId = jobId;
  renderCharacterWorkspace();
  if (['pending','running'].includes(result.job.state)) setTimeout(()=>refreshDiscovery(jobId).catch(error=>message(error.message)), 900);
  else await load();
}

async function refreshDuplicates(characterId, append = false) {
  const offset = append ? (characterImageCache.get(characterId)?.length || 0) : 0;
  const filter=galleryFilter(characterId);
  const [duplicates, images, quarantineHistory] = await Promise.all([
    api('character/duplicates', {character_id: characterId}),
    api('character/images', {character_id: characterId, limit: 200, offset, ...filter}),
    api('character/quarantine/history', {character_id: characterId}),
  ]);
  duplicateCache.set(characterId, duplicates);
  quarantineHistoryCache.set(characterId, quarantineHistory);
  const current = append ? (characterImageCache.get(characterId) || []) : [];
  const loaded = [...current, ...images.items];
  characterImageCache.set(characterId, loaded);
  imageSelectionViewModel.hydrate(characterId, loaded.map(item=>item.id));
  characterImageTotal.set(characterId, images.total);
  renderCharacterWorkspace();
}

function watchAssignmentJob(jobId, characterId) {
  if(assignmentPolls.has(jobId))return;
  assignmentPolls.add(jobId);
  const tick=async()=>{
    try {
      const job=await api('character/assignment',{job_id:jobId});
      assignmentJobCache.set(characterId,job);
      renderCharacterWorkspace();
      if(['pending','running'].includes(job.state))setTimeout(tick,650);
      else {assignmentPolls.delete(jobId);if(job.state==='completed'){await load();await refreshDuplicates(characterId);message(`Folder assignment complete · ${job.assigned_count} new · ${job.already_assigned_count} already known${job.error_count?' · '+job.error_count+' failed':''}`);}else message(job.error||'Folder assignment failed');}
    } catch(error) { assignmentPolls.delete(jobId);message(error.message); }
  };
  tick();
}

async function refreshFamilies(characterId) {
  const [families, images] = await Promise.all([
    api('character/families', {character_id: characterId}),
    api('character/images', {character_id: characterId, limit: 200, offset: 0}),
  ]);
  familyCache.set(characterId, families);
  characterImageCache.set(characterId, images.items);
  characterImageTotal.set(characterId, images.total);
  renderCharacterWorkspace();
}

async function loadAllCharacterImages(characterId) {
  const images=[];
  let total=1;
  while(images.length<total){const page=await api('character/images',{character_id:characterId,limit:500,offset:images.length});images.push(...page.items);total=page.total;}
  characterImageCache.set(characterId,images);
  characterImageTotal.set(characterId,total);
  imageSelectionViewModel.hydrate(characterId,images.map(item=>item.id));
  return images;
}

async function openFamilyDialog(characterId, preselectedIds = [], family = null) {
  const images = await loadAllCharacterImages(characterId);
  $('family-name').value = family?.name || '';
  $('family-dialog-title').textContent = family ? 'Edit image family' : 'Create a flexible image group';
  $('create-family').textContent = family ? 'Save family' : 'Create family';
  $('family-image-picker').innerHTML = images.map(item=>`<label><input type="checkbox" value="${esc(item.id)}"><img src="/api/character/thumbnail/${encodeURIComponent(item.id)}?size=192" alt="${esc(item.original_name)}" loading="lazy"><span>${esc(item.original_name)}</span></label>`).join('') || '<div class="empty">Assign images to this character first.</div>';
  const preselected = new Set(preselectedIds);
  for(const input of $('family-image-picker').querySelectorAll('input')) input.checked=preselected.has(input.value);
  $('family-dialog').dataset.characterId = characterId;
  $('family-dialog').dataset.familyId = family?.id || '';
  showError('family-error', null);
  $('family-dialog').showModal();
}

async function openLineageGallery(sourceAssetId) {
  $('lineage-dialog').showModal();
  $('lineage-gallery').innerHTML = '<div class="empty">Loading generated images…</div>';
  const images = await api('character/generated', {source_asset_id: sourceAssetId});
  $('lineage-gallery').innerHTML = images.map(item=>`<figure><img src="/api/character/thumbnail/${encodeURIComponent(item.output_asset_id)}?size=320" alt="Generated from selected source" loading="lazy"><figcaption>${esc(item.original_name)}<small>Run ${esc(item.run_id)}</small></figcaption></figure>`).join('') || '<div class="empty-state"><strong>No recorded outputs</strong><p>New Preset Studio runs using this source will appear here.</p></div>';
}

async function browseFolders(path = '') {
  folderBrowse = {...folderBrowse, ...await api('folders', {path})};
  $('folder-current').value = folderBrowse.path;
  $('folder-up').disabled = !folderBrowse.parent || folderBrowse.parent === folderBrowse.path;
  $('folder-list').innerHTML = folderBrowse.folders.map(folder => `<button data-folder-path="${esc(folder.path)}"><span class="folder-icon">▸</span><span>${esc(folder.name)}</span></button>`).join('') || '<div class="empty">No subfolders.</div>';
  showError('folder-error', null);
}

function recentFolders() {
  try {
    const value=JSON.parse(localStorage.getItem('preset-studio-character-folders')||'[]');
    return Array.isArray(value)?value.filter(path=>typeof path==='string'&&path).slice(0,6):[];
  } catch { return []; }
}
function rememberFolder(path) {
  const folders=[path,...recentFolders().filter(item=>item!==path)].slice(0,6);
  try { localStorage.setItem('preset-studio-character-folders',JSON.stringify(folders)); } catch { /* Folder browsing remains usable without browser storage. */ }
}
function renderRecentFolders() {
  const folders=recentFolders();
  $('folder-recent').innerHTML=folders.length?`<span>Recent</span>${folders.map(path=>`<button class="quiet" data-recent-folder="${esc(path)}" title="${esc(path)}">${esc(path.split(/[\\/]/).filter(Boolean).pop()||path)}</button>`).join('')}`:'';
}

function activeBuilderOption() {
  for(const experiment of builderState.experiments||[])for(const option of experiment.options||[])if(option.id===activeBuilderOptionId)return {experiment,option};
  return null;
}
function builderResourcesMarkup(active) {
  const checkpoints=models.nodes.CheckpointLoaderSimple?.input?.required?.ckpt_name?.[0]||[];
  const loras=active.option.resources.loras||[];
  const selectedReferences=new Set(active.option.resources.references||[]);
  const referenceRows=Object.entries(state.references||{}).map(([id,reference])=>`<label class="builder-reference ${selectedReferences.has(id)?'selected':''}"><input type="checkbox" data-builder-reference="${esc(id)}" ${selectedReferences.has(id)?'checked':''}><img src="/api/reference/${encodeURIComponent(id)}" alt="" loading="lazy"><span>${esc(reference.name)}</span></label>`).join('');
  return `<section class="builder-resources"><h3>Generation resources</h3><label>Option name<input data-builder-option-name maxlength="160" value="${esc(active.option.name)}"></label><label>Model<select data-builder-model><option value="">Use graph value</option>${checkpoints.map(name=>`<option value="${esc(name)}" ${name===active.option.resources.model?'selected':''}>${esc(name)}</option>`).join('')}</select></label><div class="builder-loras"><div class="builder-resource-head"><strong>LoRAs</strong><span>Model / CLIP</span></div>${loras.map((lora,index)=>`<div><select data-builder-lora="name" data-lora-index="${index}">${models.loras.map(name=>`<option value="${esc(name)}" ${name===lora.name?'selected':''}>${esc(name)}</option>`).join('')}</select><input data-builder-lora="model" data-lora-index="${index}" type="number" step=".05" value="${lora.model}" aria-label="Model strength"><input data-builder-lora="clip" data-lora-index="${index}" type="number" step=".05" value="${lora.clip}" aria-label="CLIP strength"><button data-builder-remove-lora="${index}" aria-label="Remove LoRA">×</button></div>`).join('')}<button data-builder-add-lora ${models.loras.length?'':'disabled'}>+ LoRA</button></div><details class="builder-reference-picker"><summary>References · ${selectedReferences.size} selected</summary>${referenceRows||'<p class="hint">Use an image from a Character gallery to add it here.</p>'}</details></section>`;
}
async function refreshBuilder(query='') {
  [builderState,builderCatalog]=await Promise.all([api('builder/state',{}),api('builder/catalog',{query})]);
  if(!activeBuilderOption())activeBuilderOptionId=builderState.experiments?.[0]?.options?.[0]?.id||null;
  renderBuilder();
}
function renderBuilder() {
  const active=activeBuilderOption();
  const workflowValue=$('builder-workflow').value;
  $('builder-workflow').innerHTML='<option value="">Choose saved workflow…</option>'+state.workflows.map(item=>`<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
  $('builder-workflow').value=active?.option.workflow_graph.source_workflow_id||workflowValue;
  $('builder-graph-summary').textContent=active?.option.workflow_graph.source_graph?`${active.option.workflow_graph.source_workflow_name||'Imported workflow'} · ${active.option.workflow_graph.blocks.length} nodes · ${Object.keys(active.option.workflow_graph.advanced_nodes||{}).length} advanced preserved`:'Choose a saved workflow as a starting graph. Unknown nodes remain preserved.';
  const graphBlocks=active?.option.workflow_graph.blocks||[];if(selectedBuilderNodeId&&!graphBlocks.some(block=>block.node_id===selectedBuilderNodeId))selectedBuilderNodeId=null;
  $('builder-graph-blocks').innerHTML=graphBlocks.map(block=>`<button class="builder-graph-block ${block.kind==='advanced'?'advanced':''} ${block.node_id===selectedBuilderNodeId?'selected':''}" data-builder-node="${esc(block.node_id)}"><span>${esc(block.kind)}</span><strong>${esc(block.label)}</strong><small>${esc(block.class_type)}</small></button>`).join('');
  const favorites=new Set(builderState.favorites||[]),bundles=(builderState.bundles||[]).map(bundle=>`<article class="builder-catalog-item bundle"><div><strong>${esc(bundle.name)}</strong><small>Reusable bundle · ${bundle.prompt_board.blocks.length} blocks</small></div><button data-builder-apply-bundle="${esc(bundle.id)}">Add all</button></article>`).join('');
  $('builder-catalog').innerHTML=bundles+builderCatalog.slice(0,250).map(item=>`<article class="builder-catalog-item" draggable="true" data-builder-catalog-id="${esc(item.id)}"><button class="favorite ${favorites.has(item.id)?'active':''}" data-builder-favorite="${esc(item.id)}" title="Favorite">★</button><div><strong>${esc(item.label)}</strong><small>${esc(item.source)} · ${esc(item.group||item.category)}</small></div><div><button data-builder-add="positive" data-catalog-id="${esc(item.id)}" title="Add to positive">+</button><button data-builder-add="negative" data-catalog-id="${esc(item.id)}" title="Add to negative">−</button></div></article>`).join('')||'<div class="empty">No matching prompt blocks.</div>';
  $('builder-title').textContent=active?`${active.experiment.name} · ${active.option.name}`:'Start an experiment';
  $('builder-options').innerHTML=(builderState.experiments||[]).flatMap(experiment=>experiment.options.map(option=>`<button class="${option.id===activeBuilderOptionId?'active':''}" data-builder-option="${esc(option.id)}"><strong>${esc(option.name)}</strong><small>${esc(experiment.name)} · ${option.revision_ids.length} revisions</small></button>`)).join('')||'<span class="hint">Create an experiment to begin.</span>';
  for(const lane of ['positive','negative']){
    const blocks=(active?.option.prompt_board.blocks||[]).filter(block=>block.lane===lane);
    $(lane==='positive'?'builder-positive':'builder-negative').innerHTML=blocks.map(block=>`<article class="builder-prompt-block ${block.enabled?'':'disabled'}" draggable="true" data-builder-block="${esc(block.id)}"><button data-builder-toggle="${esc(block.id)}" aria-label="Toggle block">${block.enabled?'●':'○'}</button><span>${esc(block.text)}</span><input data-builder-weight="${esc(block.id)}" type="number" min="0.1" max="4" step="0.05" value="${block.weight}" aria-label="Block weight"><button class="danger" data-builder-remove="${esc(block.id)}" aria-label="Remove block">×</button></article>`).join('')||'<div class="builder-drop-hint">Drop or add blocks here</div>';
  }
  if(active){const positive=active.option.prompt_board.blocks.filter(item=>item.enabled&&item.lane==='positive').map(item=>item.weight===1?item.text:`(${item.text}:${item.weight})`).join(', ');const negative=active.option.prompt_board.blocks.filter(item=>item.enabled&&item.lane==='negative').map(item=>item.weight===1?item.text:`(${item.text}:${item.weight})`).join(', ');const node=selectedBuilderNodeId?active.option.workflow_graph.source_graph?.[selectedBuilderNodeId]:null;const nodeFields=node?Object.entries(node.inputs).filter(([,value])=>!Array.isArray(value)&&['string','number','boolean'].includes(typeof value)).map(([name,value])=>`<label>${esc(name)}<input data-builder-node-input="${esc(name)}" data-value-type="${typeof value}" value="${esc(value)}"></label>`).join(''):'';$('builder-preview').innerHTML=`<label>Positive</label><p>${esc(positive)||'<span class="hint">Empty</span>'}</p><label>Negative</label><p>${esc(negative)||'<span class="hint">Empty</span>'}</p><dl><dt>Model</dt><dd>${esc(active.option.resources.model||'Set on graph')}</dd><dt>Graph blocks</dt><dd>${active.option.workflow_graph.blocks.length}</dd></dl>${node?`<div class="builder-node-editor"><h3>${esc(node._meta?.title||node.class_type)}</h3>${nodeFields||'<p class="hint">This node has no scalar inputs.</p>'}</div>`:''}`;}else $('builder-preview').innerHTML='<p class="hint">Create an experiment, then add prompt blocks.</p>';
  if(active){$('builder-preview').insertAdjacentHTML('beforeend',builderResourcesMarkup(active));const parent=active.option.parent_option_id?(builderState.experiments||[]).flatMap(item=>item.options).find(item=>item.id===active.option.parent_option_id):null;if(parent){const before=new Set(parent.prompt_board.blocks.map(item=>item.text)),after=new Set(active.option.prompt_board.blocks.map(item=>item.text)),added=[...after].filter(item=>!before.has(item)),removed=[...before].filter(item=>!after.has(item));$('builder-preview').insertAdjacentHTML('beforeend',`<details class="builder-diff"><summary>Changes from ${esc(parent.name)}</summary>${added.map(item=>`<p class="added">+ ${esc(item)}</p>`).join('')}${removed.map(item=>`<p class="removed">− ${esc(item)}</p>`).join('')||(!added.length?'<p class="hint">Prompt blocks unchanged</p>':'')}</details>`);}const revisions=(builderState.revisions||[]).filter(item=>item.option_id===active.option.id);if(revisions.length)$('builder-preview').insertAdjacentHTML('beforeend',`<section class="builder-revisions"><h3>Generated revisions</h3>${revisions.slice().reverse().map((revision,index)=>`<article><strong>Revision ${revisions.length-index}</strong><small>${new Date(revision.created_at).toLocaleString()}</small><div>${revision.outputs.map(output=>`<img src="/api/output?run=${encodeURIComponent(output.run_id)}&index=${output.output_index}" alt="Builder output" loading="lazy">`).join('')||'<span class="hint">Queued or awaiting output</span>'}</div></article>`).join('')}</section>`);}
  $('builder-branch').disabled=!active;$('builder-save-bundle').disabled=!active||!active.option.prompt_board.blocks.length;$('builder-save-workflow').disabled=!active?.option.workflow_graph.source_graph;$('builder-delete-option').disabled=!active;$('builder-attach-workflow').disabled=!active||!$('builder-workflow').value;$('builder-generate').disabled=!active?.option.workflow_graph.source_graph;
}
async function updateBuilderBoard(blocks) {
  const active=activeBuilderOption();if(!active)return;
  await api('builder/option/update',{option_id:active.option.id,changes:{prompt_board:{blocks}}});await refreshBuilder($('builder-search').value);
}

async function openFolderBrowser(characterId, mode = 'assign') {
  folderBrowse = {characterId, mode, path: '', parent: '', folders: []};
  $('folder-recursive').checked = false;
  $('folder-title').textContent = mode === 'discover' ? 'Find new character pictures' : 'Assign images to character';
  $('folder-hint').textContent = mode === 'discover' ? 'Nothing runs until you press Start scan. Images stay in place and matches go to review.' : 'Browse locally, choose this folder, and decide whether to include its subfolders. Nothing is moved or copied.';
  $('assign-folder').textContent = mode === 'discover' ? 'Start scan' : 'Assign images from this folder';
  renderRecentFolders();
  $('folder-dialog').showModal();
  const start=recentFolders()[0]||'';
  try { await browseFolders(start); } catch (error) { try { await browseFolders(''); } catch { showError('folder-error', error); } }
}

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
  $('workflow-list').innerHTML = state.workflows.map(item => `<article class="workflow-card"><div><strong>${esc(item.name)}</strong><small>${item.adapter.positive?.length||0} prompt fields · ${item.adapter.references?.length||0} references · ${item.adapter.seed?.length||0} seed fields</small></div><button data-workflow-edit="${esc(item.id)}">Map fields</button></article>`).join('') || '<div class="empty-state"><strong>No mapped workflows</strong><p>Import a ComfyUI API workflow to make it available in Compose.</p></div>';
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
    if(studioViewModel.snapshot.activeDestination==='builder')renderBuilder();
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
  const openNewCharacter = !editingPreset.id && data.kind === 'character' && studioViewModel.snapshot.activeDestination === 'characters';
  if (asCopy) { delete data.id; data.name += ' copy'; }
  try {
    const saved = await api('preset', data);
    await load();
    if (!editingPreset.id) selected.push(saved.id);
    if (!(referenceChoices[saved.id]||[]).some(id=>saved.references.includes(id))) referenceChoices[saved.id]=saved.references.slice(0,1);
    if (openNewCharacter) {
      const character = state.characters.find(item=>item.preset_id===saved.id);
      if (character) { imageSelectionViewModel.hydrate(character.id,[]); studioViewModel.selectCharacter(character.id); studioViewModel.showCharacterView('images'); }
    }
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

studioViewModel.subscribe(snapshot => {
  renderShell(snapshot);
  renderCharacters();
  renderCharacterWorkspace(snapshot);
});
renderShell(studioViewModel.snapshot);
renderCharacters();
renderCharacterWorkspace();
on('app-nav','click', async e => { const button=e.target.closest('[data-destination]'); if(button){studioViewModel.navigate(button.dataset.destination);if(button.dataset.destination==='builder')await refreshBuilder();} });
on('builder-new','click',async()=>{const experiment=await api('builder/experiment/create',{name:`Experiment ${(builderState.experiments?.length||0)+1}`});activeBuilderOptionId=experiment.options[0].id;await refreshBuilder();});
on('builder-branch','click',async()=>{const active=activeBuilderOption();if(!active)return;const branch=await api('builder/option/branch',{option_id:active.option.id,name:`${active.option.name} variation`});activeBuilderOptionId=branch.id;await refreshBuilder($('builder-search').value);});
on('builder-options','click',e=>{const button=e.target.closest('[data-builder-option]');if(button){activeBuilderOptionId=button.dataset.builderOption;renderBuilder();}});
on('builder-catalog','click',async e=>{const favorite=e.target.closest('[data-builder-favorite]'),bundleButton=e.target.closest('[data-builder-apply-bundle]'),button=e.target.closest('[data-builder-add]');if(favorite){await api('builder/favorite/toggle',{item_id:favorite.dataset.builderFavorite});await refreshBuilder($('builder-search').value);return;}const active=activeBuilderOption();if(!active){message('Create an experiment first');return;}if(bundleButton){const bundle=(builderState.bundles||[]).find(item=>item.id===bundleButton.dataset.builderApplyBundle);if(bundle)await updateBuilderBoard([...active.option.prompt_board.blocks,...bundle.prompt_board.blocks.map(item=>({...item,id:crypto.randomUUID()}))]);return;}if(!button)return;const item=builderCatalog.find(value=>value.id===button.dataset.catalogId);if(!item)return;await updateBuilderBoard([...active.option.prompt_board.blocks,{id:crypto.randomUUID(),lane:button.dataset.builderAdd,text:item.text,weight:1,enabled:true,catalog_id:item.id}]);});
on('builder-search','input',()=>{clearTimeout(gallerySearchTimer);gallerySearchTimer=setTimeout(()=>refreshBuilder($('builder-search').value).catch(error=>message(error.message)),220);});
on('builder-catalog','dragstart',e=>{const item=e.target.closest('[data-builder-catalog-id]');if(item)e.dataTransfer.setData('text/preset-studio-catalog',item.dataset.builderCatalogId);});
for(const id of ['builder-positive','builder-negative']){
  on(id,'dragover',e=>e.preventDefault());
  on(id,'dragstart',e=>{const block=e.target.closest('[data-builder-block]');if(block)e.dataTransfer.setData('text/preset-studio-block',block.dataset.builderBlock);});
  on(id,'drop',async e=>{e.preventDefault();const catalogId=e.dataTransfer.getData('text/preset-studio-catalog'),blockId=e.dataTransfer.getData('text/preset-studio-block');const item=builderCatalog.find(value=>value.id===catalogId);const active=activeBuilderOption(),lane=e.currentTarget.dataset.builderLane;if(item&&active)await updateBuilderBoard([...active.option.prompt_board.blocks,{id:crypto.randomUUID(),lane,text:item.text,weight:1,enabled:true,catalog_id:item.id}]);else if(blockId&&active){const moved=active.option.prompt_board.blocks.find(item=>item.id===blockId);if(moved)await updateBuilderBoard([...active.option.prompt_board.blocks.filter(item=>item.id!==blockId),{...moved,lane}]);}});
  on(id,'click',async e=>{const active=activeBuilderOption();if(!active)return;const remove=e.target.closest('[data-builder-remove]'),toggle=e.target.closest('[data-builder-toggle]');if(remove)await updateBuilderBoard(active.option.prompt_board.blocks.filter(item=>item.id!==remove.dataset.builderRemove));if(toggle)await updateBuilderBoard(active.option.prompt_board.blocks.map(item=>item.id===toggle.dataset.builderToggle?{...item,enabled:!item.enabled}:item));});
  on(id,'change',async e=>{const input=e.target.closest('[data-builder-weight]');const active=activeBuilderOption();if(input&&active)await updateBuilderBoard(active.option.prompt_board.blocks.map(item=>item.id===input.dataset.builderWeight?{...item,weight:Number(input.value)}:item));});
}
on('builder-import-workflow','click',()=>openWorkflow());
on('builder-graph-blocks','click',e=>{const button=e.target.closest('[data-builder-node]');if(button){selectedBuilderNodeId=button.dataset.builderNode;renderBuilder();}});
on('builder-properties','change',async e=>{
  const active=activeBuilderOption();if(!active)return;
  const changes={};
  const name=e.target.closest('[data-builder-option-name]');
  const model=e.target.closest('[data-builder-model]');
  const lora=e.target.closest('[data-builder-lora]');
  const reference=e.target.closest('[data-builder-reference]');
  const nodeInput=e.target.closest('[data-builder-node-input]');
  if(name)changes.name=name.value;
  else if(model)changes.resources={...active.option.resources,model:model.value||null};
  else if(lora){const loras=structuredClone(active.option.resources.loras||[]),index=Number(lora.dataset.loraIndex),key=lora.dataset.builderLora;loras[index][key]=key==='name'?lora.value:Number(lora.value);changes.resources={...active.option.resources,loras};}
  else if(reference){const references=[...new Set([...(active.option.resources.references||[]),reference.dataset.builderReference])].filter(id=>id!==reference.dataset.builderReference||reference.checked);changes.resources={...active.option.resources,references};}
  else if(nodeInput&&selectedBuilderNodeId){const workflow=structuredClone(active.option.workflow_graph),type=nodeInput.dataset.valueType;workflow.source_graph[selectedBuilderNodeId].inputs[nodeInput.dataset.builderNodeInput]=type==='number'?Number(nodeInput.value):type==='boolean'?nodeInput.value==='true':nodeInput.value;changes.workflow_graph=workflow;}
  else return;
  await api('builder/option/update',{option_id:active.option.id,changes});await refreshBuilder($('builder-search').value);
});
on('builder-properties','click',async e=>{
  const active=activeBuilderOption();if(!active)return;
  const add=e.target.closest('[data-builder-add-lora]'),remove=e.target.closest('[data-builder-remove-lora]');
  if(add){const first=models.loras[0];if(!first)return;await api('builder/option/update',{option_id:active.option.id,changes:{resources:{...active.option.resources,loras:[...(active.option.resources.loras||[]),{name:first,model:1,clip:1}]}}});await refreshBuilder($('builder-search').value);}
  if(remove){const loras=(active.option.resources.loras||[]).filter((_,index)=>index!==Number(remove.dataset.builderRemoveLora));await api('builder/option/update',{option_id:active.option.id,changes:{resources:{...active.option.resources,loras}}});await refreshBuilder($('builder-search').value);}
});
on('builder-basic-workflow','click',async()=>{const active=activeBuilderOption();if(!active){message('Create an experiment first');return;}await api('builder/workflow/basic',{option_id:active.option.id});await refreshBuilder($('builder-search').value);message('Basic image workflow created');});
on('builder-workflow','change',()=>{$('builder-attach-workflow').disabled=!activeBuilderOption()||!$('builder-workflow').value;});
on('builder-attach-workflow','click',async()=>{const active=activeBuilderOption();if(!active||!$('builder-workflow').value)return;await api('builder/workflow/attach',{option_id:active.option.id,workflow_id:$('builder-workflow').value});await refreshBuilder($('builder-search').value);message('Workflow loaded into this option');});
on('builder-generate','click',async()=>{const active=activeBuilderOption();if(!active)return;$('builder-generate').disabled=true;const result=await api('builder/generate',{option_id:active.option.id});await load();await refreshBuilder($('builder-search').value);message(result.run.status==='queued'?'Builder option queued':'Builder generation '+result.run.status);});
on('builder-save-bundle','click',async()=>{const active=activeBuilderOption();if(!active||!active.option.prompt_board.blocks.length)return;await api('builder/bundle/save',{name:`${active.option.name} prompt`,prompt_board:active.option.prompt_board});await refreshBuilder($('builder-search').value);message('Reusable prompt bundle saved');});
on('builder-save-workflow','click',async()=>{const active=activeBuilderOption();if(!active?.option.workflow_graph.source_graph)return;const saved=await api('builder/workflow/save',{option_id:active.option.id,name:`${active.option.name} workflow`});await load();await refreshBuilder($('builder-search').value);message(`${saved.name} added to the workflow library`);});
on('builder-delete-option','click',async()=>{const active=activeBuilderOption();if(!active||!confirm(`Scrap ${active.option.name}? Generated revisions remain in history.`))return;await api('builder/option/delete',{option_id:active.option.id});activeBuilderOptionId=null;selectedBuilderNodeId=null;await refreshBuilder($('builder-search').value);message('Builder option scrapped');});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&studioViewModel.snapshot.activeDestination==='builder'&&!$('builder-generate').disabled){e.preventDefault();$('builder-generate').click();}});
on('filters','click', async e => { const button=e.target.closest('[data-filter]'); if(button) { category=button.dataset.filter; renderLibrary(); } });
on('search','input', renderLibrary);
on('character-search','input', renderCharacters);
on('character-list','click', e => { const button=e.target.closest('[data-character-select]'); if(button) { activeDiscoveryJobId=null; imageSelectionViewModel.hydrate(button.dataset.characterSelect,[]); studioViewModel.selectCharacter(button.dataset.characterSelect); } });
on('character-workspace','change', e => {
  const input=e.target.closest('[data-review-select]');
  if(input){reviewQueueViewModel.setSelected(input.dataset.reviewSelect,input.checked);renderCharacterWorkspace();}
  const imageInput=e.target.closest('[data-image-select]');
  if(imageInput){imageSelectionViewModel.setSelected(imageInput.dataset.imageSelect,imageInput.checked);renderCharacterWorkspace();}
  const sort=e.target.closest('[data-image-sort]');
  if(sort){const characterId=studioViewModel.snapshot.selectedCharacterId;galleryFilters.set(characterId,{...galleryFilter(characterId),sort:sort.value});refreshDuplicates(characterId).catch(error=>message(error.message));}
});
on('character-workspace','input', e => {
  const search=e.target.closest('[data-image-search]');if(!search)return;
  const characterId=studioViewModel.snapshot.selectedCharacterId;
  galleryFilters.set(characterId,{...galleryFilter(characterId),query:search.value});
  clearTimeout(gallerySearchTimer);gallerySearchTimer=setTimeout(()=>refreshDuplicates(characterId).catch(error=>message(error.message)),280);
});
on('character-workspace','click', async e => {
  const tab=e.target.closest('[data-character-view]');if(tab){studioViewModel.showCharacterView(tab.dataset.characterView);const character=studioViewModel.snapshot.catalog.characters.find(item=>item.id===studioViewModel.snapshot.selectedCharacterId);const jobId=activeDiscoveryJobId||character?.discovery_jobs?.[0]?.id;if(tab.dataset.characterView==='review'&&jobId)await refreshDiscovery(jobId);if(tab.dataset.characterView==='images'&&character)await refreshDuplicates(character.id);if(['families','sources'].includes(tab.dataset.characterView)&&character)await refreshFamilies(character.id);return;}
  const edit=e.target.closest('[data-edit-character]');if(edit)return openPreset(edit.dataset.editCharacter);
  const folder=e.target.closest('[data-open-folder]');if(folder)return openFolderBrowser(folder.dataset.openFolder);
  const find=e.target.closest('[data-find-folder]');if(find)return openFolderBrowser(find.dataset.findFolder,'discover');
  const job=e.target.closest('[data-review-job]');if(job){studioViewModel.showCharacterView('review');await refreshDiscovery(job.dataset.reviewJob);return;}
  const assign=e.target.closest('[data-assign-recommended]');if(assign){const ids=reviewQueueViewModel.selectedIds();if(!ids.length)return;assign.disabled=true;const result=await api('character/review/apply',{job_id:activeDiscoveryJobId,review_ids:ids});reviewQueueViewModel.forget(ids);message(`Assigned ${result.assigned} recommended image${result.assigned===1?'':'s'}`);await refreshDiscovery(activeDiscoveryJobId);}
  const assignAll=e.target.closest('[data-assign-all]');if(assignAll){assignAll.disabled=true;const result=await api('character/review/apply',{job_id:activeDiscoveryJobId,all_pending:true});reviewQueueViewModel.clear();message(`Assigned all ${result.assigned} pending recommendation${result.assigned===1?'':'s'}`);await refreshDiscovery(activeDiscoveryJobId);return;}
  const toggle=e.target.closest('[data-review-toggle]');if(toggle){const visible=discoveryCache.get(activeDiscoveryJobId)?.review||[];reviewQueueViewModel.selectVisible(visible,toggle.dataset.reviewToggle==='all');renderCharacterWorkspace();return;}
  const more=e.target.closest('[data-review-more]');if(more){more.disabled=true;await refreshDiscovery(activeDiscoveryJobId,true);return;}
  const imageMore=e.target.closest('[data-images-more]');if(imageMore){imageMore.disabled=true;await refreshDuplicates(studioViewModel.snapshot.selectedCharacterId,true);return;}
  const imageToggle=e.target.closest('[data-image-toggle]');if(imageToggle){const ids=(characterImageCache.get(studioViewModel.snapshot.selectedCharacterId)||[]).map(item=>item.id);imageSelectionViewModel.selectVisible(ids,imageToggle.dataset.imageToggle==='all');renderCharacterWorkspace();return;}
  const searchClear=e.target.closest('[data-image-search-clear]');if(searchClear){const characterId=studioViewModel.snapshot.selectedCharacterId;galleryFilters.set(characterId,{...galleryFilter(characterId),query:''});await refreshDuplicates(characterId);return;}
  const familyFromSelection=e.target.closest('[data-family-from-selection]');if(familyFromSelection){return openFamilyDialog(familyFromSelection.dataset.familyFromSelection,imageSelectionViewModel.selectedIds());}
  const viewAsset=e.target.closest('[data-view-asset]');if(viewAsset){$('image-viewer-title').textContent=viewAsset.dataset.viewName;$('image-viewer-img').src='/api/character/asset/'+encodeURIComponent(viewAsset.dataset.viewAsset);$('image-viewer-dialog').showModal();return;}
  const decision=e.target.closest('[data-review-decision]');if(decision){const ids=reviewQueueViewModel.selectedIds();if(!ids.length)return;decision.disabled=true;const result=await api('character/review/decide',{job_id:activeDiscoveryJobId,review_ids:ids,decision:decision.dataset.reviewDecision});reviewQueueViewModel.forget(ids);message(`${result.updated} recommendation${result.updated===1?'':'s'} ${decision.dataset.reviewDecision}`);await refreshDiscovery(activeDiscoveryJobId);return;}
  const cancel=e.target.closest('[data-cancel-discovery]');if(cancel){cancel.disabled=true;await api('character/discovery/cancel',{job_id:activeDiscoveryJobId});message('Scan cancellation requested');await refreshDiscovery(activeDiscoveryJobId);return;}
  const quarantine=e.target.closest('[data-quarantine-location]');if(quarantine){if(!confirm('Move this byte-exact copy to recoverable quarantine? The recommended keeper remains in place.'))return;quarantine.disabled=true;lastQuarantineOperation=await api('character/duplicate/quarantine',{location_id:quarantine.dataset.quarantineLocation});const characterId=studioViewModel.snapshot.selectedCharacterId;await refreshDuplicates(characterId);message('Duplicate copy moved to recoverable quarantine');return;}
  const restore=e.target.closest('[data-restore-quarantine]');if(restore){await api('character/duplicate/restore',{operation_id:restore.dataset.restoreQuarantine});lastQuarantineOperation=null;await refreshDuplicates(studioViewModel.snapshot.selectedCharacterId);message('Quarantined copy restored');}
  const newFamily=e.target.closest('[data-new-family]');if(newFamily)return openFamilyDialog(newFamily.dataset.newFamily);
  const editFamily=e.target.closest('[data-edit-family]');if(editFamily){const family=(familyCache.get(studioViewModel.snapshot.selectedCharacterId)||[]).find(item=>item.id===editFamily.dataset.editFamily);if(family)return openFamilyDialog(family.character_id,family.members.map(item=>item.asset_id),family);}
  const source=e.target.closest('[data-family-source]');if(source){source.disabled=true;await api('character/family/source',{family_id:source.dataset.familySource,asset_id:source.dataset.sourceAsset});await refreshFamilies(studioViewModel.snapshot.selectedCharacterId);message('Family source updated');}
  const lineage=e.target.closest('[data-view-lineage]');if(lineage)await openLineageGallery(lineage.dataset.viewLineage);
  const builder=e.target.closest('[data-use-builder]');if(builder){builder.disabled=true;await refreshBuilder();let active=activeBuilderOption();if(!active){const character=state.characters.find(item=>item.id===builder.dataset.builderCharacter);const experiment=await api('builder/experiment/create',{name:`${character?.name||'Character'} study`});activeBuilderOptionId=experiment.options[0].id;active={experiment,option:experiment.options[0]};}await api('character/use-in-builder',{character_id:builder.dataset.builderCharacter,asset_id:builder.dataset.useBuilder,option_id:active.option.id});await load();studioViewModel.navigate('builder');await refreshBuilder();message('Character source added to Builder references');return;}
  const compose=e.target.closest('[data-use-compose]');if(compose){compose.disabled=true;const result=await api('character/use-in-compose',{character_id:compose.dataset.composeCharacter,asset_id:compose.dataset.useCompose});await load();selected=[result.preset_id];referenceChoices[result.preset_id]=[result.reference_id];referenceBatch=null;studioViewModel.navigate('compose');await changed();message('Character source staged in Compose');}
});
on('new-character','click',()=>openPreset());
on('add-workflow-page','click',()=>openWorkflow());
on('workflow-list','click',e=>{const button=e.target.closest('[data-workflow-edit]');if(button)openWorkflow(button.dataset.workflowEdit);});
on('folder-list','click',e=>{const button=e.target.closest('[data-folder-path]');if(button)browseFolders(button.dataset.folderPath).catch(error=>showError('folder-error',error));});
on('folder-recent','click',e=>{const button=e.target.closest('[data-recent-folder]');if(button)browseFolders(button.dataset.recentFolder).catch(error=>showError('folder-error',error));});
on('folder-up','click',()=>browseFolders(folderBrowse.parent).catch(error=>showError('folder-error',error)));
on('folder-refresh','click',()=>browseFolders(folderBrowse.path).catch(error=>showError('folder-error',error)));
on('assign-folder','click',async()=>{
  const payload={character_id:folderBrowse.characterId,path:folderBrowse.path,recursive:$('folder-recursive').checked};
  rememberFolder(payload.path);
  if(folderBrowse.mode==='discover'){
    const job=await api('character/discovery/start',payload);activeDiscoveryJobId=job.id;$('folder-dialog').close();studioViewModel.showCharacterView('review');await refreshDiscovery(job.id);message('Manual scan started');
  }else{
    const job=await api('character/assignment/start',payload);assignmentJobCache.set(payload.character_id,job);$('folder-dialog').close();renderCharacterWorkspace();watchAssignmentJob(job.id,payload.character_id);message('Folder assignment started in the background');
  }
});
on('create-family','click',async()=>{
  const characterId=$('family-dialog').dataset.characterId;
  const assetIds=[...$('family-image-picker').querySelectorAll('input:checked')].map(input=>input.value);
  try {
    if(!assetIds.length)throw new Error('Choose at least one image');
    const familyId=$('family-dialog').dataset.familyId;
    await api(familyId?'character/family/update':'character/family/create',familyId?{family_id:familyId,name:$('family-name').value,asset_ids:assetIds}:{character_id:characterId,name:$('family-name').value,asset_ids:assetIds});
    $('family-dialog').close();await refreshFamilies(characterId);message(familyId?'Image family updated':'Image family created');
  } catch(error) { showError('family-error', error); }
});
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
    await load();$('workflow').value=saved.id;$('workflow-dialog').close();
    const builder=activeBuilderOption();if(studioViewModel.snapshot.activeDestination==='builder'&&builder){await api('builder/workflow/attach',{option_id:builder.option.id,workflow_id:saved.id});await refreshBuilder($('builder-search').value);}
    await changed();message(builder&&studioViewModel.snapshot.activeDestination==='builder'?'Workflow mapped and loaded into Builder':'Workflow mapping saved');
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
