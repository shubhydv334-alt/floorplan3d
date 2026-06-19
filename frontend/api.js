// SERVER
// ═══════════════════════════════════════════════════════════════
async function checkServer(){const d=document.getElementById('sdot'),t=document.getElementById('stxt');d.className='sdot spin';t.textContent='…';try{const r=await fetch(API+'/health',{signal:AbortSignal.timeout(3000)});if(r.ok){const j=await r.json();d.className='sdot ok';t.textContent=`Connected`;return true}}catch{}d.className='sdot err';t.textContent='offline';return false}
checkServer();setInterval(checkServer,15000);

// ═══════════════════════════════════════════════════════════════
// FILE HANDLING
// ═══════════════════════════════════════════════════════════════
const dzEl=document.getElementById('dz');
dzEl.addEventListener('dragover',e=>{e.preventDefault();dzEl.classList.add('over')});
dzEl.addEventListener('dragleave',()=>dzEl.classList.remove('over'));
dzEl.addEventListener('drop',e=>{e.preventDefault();dzEl.classList.remove('over');const f=e.dataTransfer.files[0];if(f&&f.type.startsWith('image/'))loadFile(f)});
function handleFile(e){if(e.target.files[0])loadFile(e.target.files[0])}
function loadFile(file){imgFile=file;const url=URL.createObjectURL(file);const img=new Image();img.onload=()=>{const pw=document.getElementById('pw'),pc=document.getElementById('pc');pw.style.display='block';pc.width=240;pc.height=Math.round(240*img.height/img.width);pc.getContext('2d').drawImage(img,0,0,pc.width,pc.height);URL.revokeObjectURL(url)};img.src=url;document.getElementById('dzt').innerHTML=`<b>${file.name}</b><br>${(file.size/1024).toFixed(0)} KB`;document.getElementById('rb').disabled=false;setStatus('Ready — click Detect & Build 3D','')}

// ═══════════════════════════════════════════════════════════════
// DETECTION
// ═══════════════════════════════════════════════════════════════
async function runDetection(){if(!imgFile)return;resetPipe();showLoad('Processing…');setP(10);const fd=new FormData();fd.append('image',imgFile);fd.append('ortho_tol',P.orthoTol);try{actStep(0);const resp=await fetch(API+'/analyze',{method:'POST',body:fd});if(!resp.ok){const e=await resp.json().catch(()=>({error:resp.statusText}));throw new Error(e.error||`HTTP ${resp.status}`)}const result=await resp.json();const ms=resp.headers.get('X-Process-Time-Ms');if(ms)document.getElementById('ptbadge').textContent=`⏱ ${ms} ms`;for(let i=1;i<=11;i++){doneStep(i-1);actStep(i);setP(18+i*6);await tick(30)}doneStep(11);setP(95);resetEdits();data=result;validateModel(result);buildTopologyGraph(result);build3D(result);updateStats(result);updateDebug(result);updateRooms(result);hideLoad();setP(100);setStatus('Done ✓','ok');document.getElementById('vpe').style.display='none';document.getElementById('minimap').style.display='block';setTimeout(()=>setP(0),2e3)}catch(e){hideLoad();setP(0);setStatus('⚠ '+e.message,'err')}}

async function loadDemo(preset='complex'){resetPipe();showLoad(`Demo (${preset})…`);setP(15);try{const resp=await fetch(`${API}/demo?preset=${preset}`);if(!resp.ok)throw new Error('Backend offline');const result=await resp.json();if(result.source_image){const pw=document.getElementById('pw'),pc=document.getElementById('pc');pw.style.display='block';const img=new Image();img.onload=()=>{pc.width=240;pc.height=Math.round(240*img.height/img.width);pc.getContext('2d').drawImage(img,0,0,pc.width,pc.height)};img.src='data:image/png;base64,'+result.source_image}const ms=resp.headers.get('X-Process-Time-Ms');if(ms)document.getElementById('ptbadge').textContent=`⏱ ${ms} ms`;for(let i=0;i<=11;i++)doneStep(i);setP(90);resetEdits();data=result;validateModel(result);buildTopologyGraph(result);build3D(result);updateStats(result);updateDebug(result);updateRooms(result);document.getElementById('dzt').innerHTML=`<b>Demo (${preset})</b>`;document.getElementById('rb').disabled=false;document.getElementById('vpe').style.display='none';document.getElementById('minimap').style.display='block';hideLoad();setP(100);setStatus(`Demo ✓`,'ok');setTimeout(()=>setP(0),2e3)}catch(e){hideLoad();setP(0);setStatus('⚠ '+e.message,'err')}}

function resetEdits(){userEdits.addedWalls=[];userEdits.deletedIds=new Set();undoStack.length=0;redoStack.length=0}

// ═══════════════════════════════════════════════════════════════
