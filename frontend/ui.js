// MINIMAP
// ═══════════════════════════════════════════════════════════════
function updateMinimap(){
  if(!data)return;const c=document.getElementById('mmCanvas'),ctx=c.getContext('2d');
  const w=c.width,h=c.height,IW=data.image_width,IH=data.image_height;
  ctx.fillStyle='#080c14';ctx.fillRect(0,0,w,h);
  const sx=w/IW,sy=h/IH;
  ctx.strokeStyle='rgba(212,200,168,0.5)';ctx.lineWidth=1.5;
  (data.outer_walls||[]).forEach(s=>{ctx.beginPath();ctx.moveTo(s.x1*sx,s.y1*sy);ctx.lineTo(s.x2*sx,s.y2*sy);ctx.stroke()});
  ctx.strokeStyle='rgba(96,168,208,0.3)';ctx.lineWidth=1;
  (data.inner_walls||[]).forEach(s=>{ctx.beginPath();ctx.moveTo(s.x1*sx,s.y1*sy);ctx.lineTo(s.x2*sx,s.y2*sy);ctx.stroke()});
  // Camera frustum indicator
  const cp=camera.position,WLD=P.world;
  const cx2=(cp.x+WLD/2)/WLD*w,cz2=(cp.z+WLD/2)/WLD*h;
  ctx.fillStyle='rgba(240,192,64,0.8)';ctx.beginPath();ctx.arc(cx2,cz2,3,0,Math.PI*2);ctx.fill();
  ctx.strokeStyle='rgba(240,192,64,0.3)';ctx.lineWidth=.5;
  const dir=walkMode?walkYaw:sph.th;const fov=.4;
  ctx.beginPath();ctx.moveTo(cx2,cz2);ctx.lineTo(cx2-Math.sin(dir-fov)*20,cz2-Math.cos(dir-fov)*20);ctx.lineTo(cx2-Math.sin(dir+fov)*20,cz2-Math.cos(dir+fov)*20);ctx.closePath();ctx.stroke();
}

// ═══════════════════════════════════════════════════════════════
// TOOLS
// ═══════════════════════════════════════════════════════════════
function setTool(tool,btn){
  if(walkMode&&tool!=='walk')exitWalkMode();
  if(tool==='walk'){enterWalkMode();document.querySelectorAll('.toolb').forEach(b=>b.classList.remove('on'));if(btn)btn.classList.add('on');return}
  currentTool=tool;document.querySelectorAll('.toolb').forEach(b=>b.classList.remove('on'));if(btn)btn.classList.add('on');
  cvs.style.cursor=tool==='orbit'?'grab':tool==='measure'?'crosshair':tool==='select'?'pointer':tool==='calibrate'?'pointer':'crosshair';
  if(tool!=='measure')clearMeasure();if(tool!=='addwall'){addWallStart=null}
}

function handleToolClick(e){
  const rect=cvs.getBoundingClientRect();mouse.x=((e.clientX-rect.left)/rect.width)*2-1;mouse.y=-((e.clientY-rect.top)/rect.height)*2+1;
  // P6: Calibrate tool
  if(currentTool==='calibrate'){raycaster.setFromCamera(mouse,camera);if(!grp)return;const hits=raycaster.intersectObjects(grp.children,false);
    for(const h of hits){if(h.object.userData&&(h.object.userData.type==='outer'||h.object.userData.type==='inner')){
      const ud=h.object.userData;
      if(h.object.material&&h.object.material.emissive){h.object.material.emissive.setHex(0x00cc66)}
      // Find the wall length from data
      const walls=[...(data.outer_walls||[]),...(data.inner_walls||[])];
      const wall=walls.find(w=>w.id===ud.index)||(ud.type==='outer'?(data.outer_walls||[])[ud.index]:(data.inner_walls||[])[ud.index]);
      if(wall){calibration.selectedWallLenPx=wall.length_px;
        const calEl=document.getElementById('calStatus');
        calEl.textContent=`Selected wall: ${wall.length_px} px. Enter real length.`;
        calEl.className='status ok';
      }
      break;
    }}
    return;
  }
  if(currentTool==='select'){raycaster.setFromCamera(mouse,camera);if(!grp)return;const hits=raycaster.intersectObjects(grp.children,false);clearSelection();
    for(const h of hits){if(h.object.userData&&h.object.userData.type&&h.object.userData.type!=='added'){selectedObject=h.object;if(h.object.material&&h.object.material.emissive){h.object.material._oe=h.object.material.emissive.getHex();h.object.material.emissive.setHex(0x2d68c4)}
    let dtx=''; if(h.object.userData.type==='room_floor') dtx=`AREA: ${h.object.userData.area} m² · TYPE: ${h.object.userData.rtype}`; else if(h.object.userData.length) dtx=`L:${h.object.userData.length}`;
    document.getElementById('selType').textContent=h.object.userData.label?h.object.userData.label.toUpperCase():h.object.userData.type.toUpperCase();
    document.getElementById('selDim').textContent=dtx;
    if(h.object.material&&h.object.material.color&&h.object.userData.type!=='room_floor'){document.getElementById('selColor').value='#'+h.object.material.color.getHexString();document.getElementById('selColor').style.display='block'}else document.getElementById('selColor').style.display='none';
    const isMatObj = ['outer','inner','closet','room_floor','bed frame','sofa','table','rug'].includes(h.object.userData.type);
    document.getElementById('selMaterials').style.display = isMatObj ? 'flex' : 'none';
    const isFurn = ['bed frame','sofa','table','rug'].includes(h.object.userData.type);
    const selFurnCtrls = document.getElementById('selFurnControls');
    if(selFurnCtrls) {
      selFurnCtrls.style.display = isFurn ? 'block' : 'none';
      if(isFurn && h.object.userData.index !== undefined && data && data.furniture) {
         const furn = data.furniture[h.object.userData.index];
         if(furn) {
            document.getElementById('furnScaleNum').value = furn.scale || 1.0;
            document.getElementById('furnRot').value = furn.angle || 0;
         }
      }
    }
    const isDoor = ['door', 'door frame'].includes(h.object.userData.type);
    const selDoorCtrls = document.getElementById('selDoorControls');
    if(selDoorCtrls) {
      selDoorCtrls.style.display = isDoor ? 'block' : 'none';
      if(isDoor && h.object.userData.opIndex !== undefined) {
         const wType = h.object.userData.wType;
         const wIdx = h.object.userData.wIndex;
         const opIdx = h.object.userData.opIndex;
         let wData = null;
         if(wType==='outer') wData = data.outer_walls[wIdx];
         if(wType==='inner') wData = data.inner_walls[wIdx];
         if(wType==='closet') wData = data.closets[wIdx];
         if(wData && wData.openings && wData.openings[opIdx]) {
            document.getElementById('doorWidth').value = (wData.openings[opIdx].width_px * (P.world/data.image_width)).toFixed(2);
         }
      }
    }
    document.getElementById('selInfo').classList.add('show');break}}}
  if(currentTool.startsWith('furn_')){raycaster.setFromCamera(mouse,camera);const pl=new THREE.Plane(new THREE.Vector3(0,1,0),0),pt=new THREE.Vector3();raycaster.ray.intersectPlane(pl,pt);if(!pt)return;
    if(!data)return;if(!data.furniture)data.furniture=[];
    const fType=currentTool.split('_')[1];
    const IW=data.image_width, IH=data.image_height, WLD=P.world;
    const cx_px = (pt.x + WLD/2) * (IW/WLD), cy_px = (pt.z + WLD/2) * (IH/WLD);
    data.furniture.push({type:fType, cx:cx_px, cy:cy_px, width:fType==='bed'?2:fType==='sofa'?2.2:fType==='table'?1.5:2.5, height:fType==='bed'?1.5:fType==='sofa'?0.9:fType==='table'?1.0:1.8, angle:0});
    rebuild(); setTool('select',document.getElementById('tool-select')); return;}
  if(currentTool==='measure'){raycaster.setFromCamera(mouse,camera);const pl=new THREE.Plane(new THREE.Vector3(0,1,0),0),pt=new THREE.Vector3();raycaster.ray.intersectPlane(pl,pt);if(!pt)return;
    if(!measurePoints.length){measurePoints.push(pt.clone());const dot=new THREE.Mesh(new THREE.SphereGeometry(.08,8,8),new THREE.MeshBasicMaterial({color:0x40b8f0}));dot.position.copy(pt);dot.position.y=.05;grp.add(dot);measureLabels.push(dot)}
    else{measurePoints.push(pt.clone());const geo=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(measurePoints[0].x,.05,measurePoints[0].z),new THREE.Vector3(measurePoints[1].x,.05,measurePoints[1].z)]);measureLine=new THREE.Line(geo,new THREE.LineBasicMaterial({color:0x40b8f0}));grp.add(measureLine);
    const dot=new THREE.Mesh(new THREE.SphereGeometry(.08,8,8),new THREE.MeshBasicMaterial({color:0x40b8f0}));dot.position.copy(pt);dot.position.y=.05;grp.add(dot);measureLabels.push(dot);
    const dist=measurePoints[0].distanceTo(measurePoints[1]).toFixed(2);const label=document.createElement('div');label.className='measure-label';label.style.cssText='position:absolute;padding:3px 8px;background:rgba(10,14,24,.9);border:1px solid var(--a2);border-radius:4px;font-family:JetBrains Mono,monospace;font-size:.6rem;color:var(--a2);pointer-events:none;z-index:50;white-space:nowrap';
    label.textContent=`${dist} m`;const mid=new THREE.Vector3().addVectors(measurePoints[0],measurePoints[1]).multiplyScalar(.5);mid.y=.1;const sp=mid.clone().project(camera);const r2=cvs.getBoundingClientRect();label.style.left=((sp.x+1)/2*r2.width)+'px';label.style.top=((-sp.y+1)/2*r2.height)+'px';vpEl.appendChild(label);measureLabels.push({isDOM:true,el:label});measurePoints=[]}}
  if(currentTool==='addwall'){raycaster.setFromCamera(mouse,camera);const pl=new THREE.Plane(new THREE.Vector3(0,1,0),0),pt=new THREE.Vector3();raycaster.ray.intersectPlane(pl,pt);if(!pt)return;
    if(data) {
       const allWalls = [...(data.outer_walls||[]), ...(data.inner_walls||[])];
       const IW=data.image_width, IH=data.image_height, WLD=P.world;
       const px = x => x*(WLD/IW)-WLD/2, pz = y => y*(WLD/IH)-WLD/2;
       let bestDist = 0.5, bestPt = null;
       allWalls.forEach(w => {
          if(w.x1 !== undefined) {
             if(Math.hypot(pt.x-px(w.x1), pt.z-pz(w.y1)) < bestDist) { bestDist = Math.hypot(pt.x-px(w.x1), pt.z-pz(w.y1)); bestPt = {x:px(w.x1), z:pz(w.y1)}; }
             if(Math.hypot(pt.x-px(w.x2), pt.z-pz(w.y2)) < bestDist) { bestDist = Math.hypot(pt.x-px(w.x2), pt.z-pz(w.y2)); bestPt = {x:px(w.x2), z:pz(w.y2)}; }
          }
       });
       if(bestPt) { pt.x = bestPt.x; pt.z = bestPt.z; }
    }
    if(addWallStart && window.event && window.event.shiftKey) {
        const dx = pt.x - addWallStart.x;
        const dz = pt.z - addWallStart.z;
        if (Math.abs(dx) > Math.abs(dz)) pt.z = addWallStart.z;
        else pt.x = addWallStart.x;
    }
    if(!addWallStart){addWallStart=pt.clone();const dot=new THREE.Mesh(new THREE.SphereGeometry(.1,8,8),new THREE.MeshBasicMaterial({color:0x40f090}));dot.position.copy(pt);dot.position.y=.05;grp.add(dot);measureLabels.push(dot)}
    else{const end=pt.clone(),dx=end.x-addWallStart.x,dz=end.z-addWallStart.z,len=Math.sqrt(dx*dx+dz*dz);
      if(len>.1){const id=Date.now(),wd={id,mx:(addWallStart.x+end.x)/2,mz:(addWallStart.z+end.z)/2,len,tk:.2,angle:-Math.atan2(dz,dx)};userEdits.addedWalls.push(wd);undoStack.push({type:'addWall',id});redoStack.length=0;rebuild()}
      addWallStart=end.clone();
      const dot=new THREE.Mesh(new THREE.SphereGeometry(.1,8,8),new THREE.MeshBasicMaterial({color:0x40f090}));dot.position.copy(end);dot.position.y=.05;grp.add(dot);measureLabels.push(dot);
    }
  }
}
function applyTexture(matName){
  if(!selectedObject||!selectedObject.userData)return;
  const tMap={'wood':texWood,'brick':texBrick,'drywall':texDrywall,'concrete':texConcrete,'tile':texTile,'none':()=>null};
  const ud=selectedObject.userData;
  if(ud.index!==undefined){
    userEdits.materials[ud.type+'_'+ud.index] = tMap[matName]();
    rebuild();
    // After rebuild, selection is lost, but we just applied it.
  }
}
function changeObjColor(hex){if(selectedObject&&selectedObject.material&&selectedObject.material.color){selectedObject.material.color.set(hex)}}

function scaleFurniture(val){
  if(selectedObject && data && data.furniture){
     const idx = selectedObject.userData.index;
     if(idx !== undefined && data.furniture[idx]){
         data.furniture[idx].scale = parseFloat(val);
         rebuild();
     }
  }
}

function rotateFurniture(val){
  if(selectedObject && data && data.furniture){
     const idx = selectedObject.userData.index;
     if(idx !== undefined && data.furniture[idx]){
         data.furniture[idx].angle = parseFloat(val);
         rebuild();
     }
  }
}

function resizeDoor(val){
  if(selectedObject && selectedObject.userData.opIndex !== undefined){
      const ud = selectedObject.userData;
      let wData = null;
      if(ud.wType==='outer') wData = data.outer_walls[ud.wIndex];
      if(ud.wType==='inner') wData = data.inner_walls[ud.wIndex];
      if(ud.wType==='closet') wData = data.closets[ud.wIndex];
      if(wData && wData.openings && wData.openings[ud.opIndex]){
          wData.openings[ud.opIndex].width_px = parseFloat(val) * (data.image_width/P.world);
          rebuild();
      }
  }
}

function deleteFurniture(){
  if(selectedObject && data && data.furniture){
     const idx = selectedObject.userData.index;
     if(idx !== undefined && data.furniture[idx]){
         data.furniture.splice(idx, 1);
         clearSelection();
         rebuild();
     }
  }
}

function clearSelection(){if(selectedObject&&selectedObject.material&&selectedObject.material._oe!==undefined){selectedObject.material.emissive.setHex(selectedObject.material._oe);delete selectedObject.material._oe}selectedObject=null;document.getElementById('selInfo').classList.remove('show')}
function clearMeasure(){measurePoints=[];if(measureLine&&grp){grp.remove(measureLine);measureLine=null}measureLabels.forEach(i=>{if(i.isDOM)i.el.remove();else if(grp)grp.remove(i)});measureLabels=[]}
function deleteSelected(){if(!selectedObject||!selectedObject.userData)return;const ud=selectedObject.userData;if(ud.type==='added'){const idx=userEdits.addedWalls.findIndex(w=>w.id===ud.index);if(idx>=0){undoStack.push({type:'rmAdd',wall:userEdits.addedWalls[idx]});userEdits.addedWalls.splice(idx,1)}}else{const key=ud.type+'_'+ud.index;userEdits.deletedIds.add(key);undoStack.push({type:'del',key})}redoStack.length=0;clearSelection();rebuild()}
function undoAction(){if(!undoStack.length)return;const a=undoStack.pop();if(a.type==='addWall'){const i=userEdits.addedWalls.findIndex(w=>w.id===a.id);if(i>=0){redoStack.push({type:'rAdd',wall:userEdits.addedWalls[i]});userEdits.addedWalls.splice(i,1)}}else if(a.type==='del'){userEdits.deletedIds.delete(a.key);redoStack.push({type:'rDel',key:a.key})}else if(a.type==='rmAdd'){userEdits.addedWalls.push(a.wall);redoStack.push({type:'rRmAdd',id:a.wall.id})}clearSelection();rebuild()}
function redoAction(){if(!redoStack.length)return;const a=redoStack.pop();if(a.type==='rAdd'){userEdits.addedWalls.push(a.wall);undoStack.push({type:'addWall',id:a.wall.id})}else if(a.type==='rDel'){userEdits.deletedIds.add(a.key);undoStack.push({type:'del',key:a.key})}else if(a.type==='rRmAdd'){const i=userEdits.addedWalls.findIndex(w=>w.id===a.id);if(i>=0){undoStack.push({type:'rmAdd',wall:userEdits.addedWalls[i]});userEdits.addedWalls.splice(i,1)}}clearSelection();rebuild()}

// ═══════════════════════════════════════════════════════════════
// LIGHTING, CLIPPING, THEME, VIEW
// ═══════════════════════════════════════════════════════════════
function updateSun(){const az=parseFloat(document.getElementById('sl-sa').value)*Math.PI/180,el=parseFloat(document.getElementById('sl-se').value)*Math.PI/180,int=parseFloat(document.getElementById('sl-si').value),r=35;sun.position.set(r*Math.cos(el)*Math.sin(az),r*Math.sin(el),r*Math.cos(el)*Math.cos(az));sun.intensity=int;document.getElementById('v-sa').textContent=document.getElementById('sl-sa').value+'°';document.getElementById('v-se').textContent=document.getElementById('sl-se').value+'°';document.getElementById('v-si').textContent=int.toFixed(1)}
function setLighting(pr,btn){document.querySelectorAll('.ltb').forEach(b=>b.classList.remove('on'));if(btn)btn.classList.add('on');const p={morning:{az:280,el:20,int:2,c:0xffcc88,a:.6,bg:0xFAFAFA,e:1},noon:{az:45,el:60,int:2.8,c:0xffffff,a:.9,bg:0xEEF0F4,e:1.1},evening:{az:100,el:12,int:1.8,c:0xffa477,a:.5,bg:0xFDF2ED,e:.95},night:{az:180,el:45,int:.6,c:0xaabbff,a:.3,bg:0x1E293B,e:.8}}[pr];document.getElementById('sl-sa').value=p.az;document.getElementById('sl-se').value=p.el;document.getElementById('sl-si').value=p.int;sun.color.setHex(p.c);ambientLight.intensity=p.a;scene.background.setHex(p.bg);scene.fog.color.setHex(p.bg);renderer.toneMappingExposure=p.e;updateSun()}
function toggleClipping(tog){clippingEnabled=!clippingEnabled;tog.classList.toggle('on',clippingEnabled);document.getElementById('clipInd').style.display=clippingEnabled?'block':'none';rebuild()}
function updateClip(){clipPlanes[0].constant=parseFloat(document.getElementById('sl-cx').value);clipPlanes[1].constant=parseFloat(document.getElementById('sl-cz').value);clipPlanes[2].constant=parseFloat(document.getElementById('sl-cy').value);document.getElementById('v-cx').textContent=parseFloat(document.getElementById('sl-cx').value).toFixed(1);document.getElementById('v-cz').textContent=parseFloat(document.getElementById('sl-cz').value).toFixed(1);document.getElementById('v-cy').textContent=parseFloat(document.getElementById('sl-cy').value).toFixed(1)}
function setTheme(n,btn){document.querySelectorAll('.thm').forEach(b=>b.classList.remove('on'));if(btn)btn.classList.add('on');applyTheme(n);rebuild()}
function setView(mode,btn){if(walkMode)exitWalkMode();document.querySelectorAll('.cb').forEach(b=>b.classList.remove('on'));if(btn)btn.classList.add('on');const v={persp:{th:Math.PI/4,ph:Math.PI/3.5,r:28,l:'3D PERSPECTIVE'},top:{th:0,ph:.01,r:36,l:'TOP VIEW'},iso:{th:Math.PI/4,ph:Math.PI/4,r:32,l:'ISOMETRIC'},front:{th:0,ph:Math.PI/2-.01,r:28,l:'FRONT ELEVATION'},walkthrough:{th:Math.PI/6,ph:Math.PI/2.3,r:8,l:'WALKTHROUGH'},corner:{th:Math.PI/5,ph:Math.PI/5,r:22,l:'CORNER VIEW'}}[mode]||{th:Math.PI/4,ph:Math.PI/3.5,r:28,l:'3D PERSPECTIVE'};
  const toPos={x:tgt.x+v.r*Math.sin(v.ph)*Math.sin(v.th),y:tgt.y+v.r*Math.cos(v.ph),z:tgt.z+v.r*Math.sin(v.ph)*Math.cos(v.th)};
  animateCamera(toPos,{x:tgt.x,y:tgt.y,z:tgt.z},500);document.getElementById('vmode').textContent=v.l}

// ═══════════════════════════════════════════════════════════════
// COMMAND BAR
// ═══════════════════════════════════════════════════════════════
const cmdSuggestions=[
  {icon:'🏠',label:'Navigate to a room',hint:'go to kitchen'},
  {icon:'🎨',label:'Change material theme',hint:'switch to classic'},
  {icon:'💡',label:'Change lighting',hint:'set evening light'},
  {icon:'📐',label:'Switch camera view',hint:'top view'},
  {icon:'📏',label:'Measure tool',hint:'measure'},
  {icon:'🧱',label:'Add wall',hint:'add wall'},
  {icon:'📦',label:'Export model',hint:'export obj'},
  {icon:'📊',label:'Bill of Materials',hint:'show bom'},
  {icon:'✅',label:'Code compliance',hint:'compliance check'},
  {icon:'✂️',label:'Toggle section cut',hint:'enable clipping'},
  {icon:'🔧',label:'Toggle wireframe',hint:'wireframe'},
  {icon:'📸',label:'Screenshot',hint:'screenshot'},
];

function toggleCmdBar(){const o=document.getElementById('cmdOverlay');o.classList.toggle('show');if(o.classList.contains('show')){document.getElementById('cmdInput').value='';document.getElementById('cmdInput').focus();renderCmdSuggestions('')}else{document.getElementById('cmdInput').blur()}}

document.getElementById('cmdInput').addEventListener('input',e=>renderCmdSuggestions(e.target.value));
document.getElementById('cmdInput').addEventListener('keydown',e=>{if(e.key==='Enter'){executeCommand(e.target.value);toggleCmdBar()}if(e.key==='Escape')toggleCmdBar()});

function renderCmdSuggestions(q){
  const r=document.getElementById('cmdResults');r.innerHTML='';
  const filtered=q?cmdSuggestions.filter(s=>s.label.toLowerCase().includes(q.toLowerCase())||s.hint.includes(q.toLowerCase())):cmdSuggestions;
  filtered.forEach(s=>{const d=document.createElement('div');d.className='cmd-item';d.innerHTML=`<span class="ci-icon">${s.icon}</span><span class="ci-label">${s.label}</span><span class="ci-hint">${s.hint}</span>`;d.onclick=()=>{executeCommand(s.hint);toggleCmdBar()};r.appendChild(d)});
}

async function executeCommand(text){
  if(!text.trim())return;
  try{
    const resp=await fetch(API+'/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    const result=await resp.json();
    const action=result.action;if(!action)return;
    if(action.type==='navigate'&&data){
      const room=(data.rooms||[]).find(r=>(r.label||'').toLowerCase().includes(action.target)||(r.room_type||'').toLowerCase().includes(action.target));
      if(room){const IW=data.image_width,IH=data.image_height,WLD=P.world;const rx=room.cx*(WLD/IW)-WLD/2,rz=room.cy*(WLD/IH)-WLD/2;animateCamera({x:rx+6,y:8,z:rz+6},{x:rx,y:0,z:rz},700);setStatus(`→ ${room.label}`,'ok')}
      else setStatus(`Room "${action.target}" not found`,'err');
    }
    else if(action.type==='theme')setTheme(action.name,document.querySelector(`.thm:nth-child(${['modern','classic','industrial'].indexOf(action.name)+1})`));
    else if(action.type==='lighting')setLighting(action.preset,null);
    else if(action.type==='camera')setView(action.view,null);
    else if(action.type==='tool')setTool(action.name,document.getElementById('tool-'+action.name));
    else if(action.type==='export'){if(action.format==='screenshot')exportScreenshot();else if(action.format==='obj')exportOBJ();else if(action.format==='svg')exportSVG();else if(action.format==='dxf')exportDXF();else if(action.format==='stl')exportSTL()}
    else if(action.type==='action'){if(action.name==='undo')undoAction();else if(action.name==='redo')redoAction();else if(action.name==='delete_selected')deleteSelected();else if(action.name==='fullscreen')toggleFullscreen();else if(action.name==='show_bom')showBOM();else if(action.name==='show_compliance')showCompliance()}
    else if(action.type==='clipping'){const tog=document.getElementById('tog-clip');if(clippingEnabled!==action.enabled)toggleClipping(tog)}
    else if(action.type==='wireframe'){V.wire=action.enabled;rebuild()}
    else if(action.type==='visibility'){/* TODO: map elements to visibility flags */}
    else if(action.type==='unknown')setStatus(action.message,'err');
  }catch(e){setStatus('Command error: '+e.message,'err')}
}

// ═══════════════════════════════════════════════════════════════
// VOICE COMMANDS
// ═══════════════════════════════════════════════════════════════
let voiceActive=false,recognition=null;
function toggleVoice(){
  if(!('webkitSpeechRecognition' in window)&&!('SpeechRecognition' in window)){setStatus('Voice not supported in this browser','err');return}
  if(voiceActive){stopVoice();return}
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  recognition=new SR();recognition.continuous=false;recognition.interimResults=false;recognition.lang='en-US';
  recognition.onresult=e=>{const t=e.results[0][0].transcript;setStatus(`🎤 "${t}"`,'');executeCommand(t);stopVoice()};
  recognition.onerror=()=>stopVoice();recognition.onend=()=>stopVoice();
  recognition.start();voiceActive=true;
  document.getElementById('voiceInd').classList.add('show');document.getElementById('voiceBtn').style.color='var(--a3)';
}
function stopVoice(){voiceActive=false;if(recognition){try{recognition.stop()}catch{}}document.getElementById('voiceInd').classList.remove('show');document.getElementById('voiceBtn').style.color=''}

// ═══════════════════════════════════════════════════════════════
// BOM & COMPLIANCE
// ═══════════════════════════════════════════════════════════════
async function showBOM(){
  if(!data){setStatus('No model loaded','err');return}
  try{
    const resp=await fetch(API+'/bom',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,world_size:P.world,wall_height:gN('a-wh',2.8)})});
    const r=await resp.json();
    const body=document.getElementById('bomBody');
    let html=`<div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">`;
    html+=`<div style="flex:1;min-width:120px;background:var(--glass);border:var(--glass-border);border-radius:8px;padding:12px;text-align:center"><div style="font-size:1.6rem;font-weight:800;color:var(--a2)">${r.totals?.floor_area_m2||0}</div><div style="font-size:.5rem;color:var(--mu);margin-top:4px">FLOOR AREA m²</div></div>`;
    html+=`<div style="flex:1;min-width:120px;background:var(--glass);border:var(--glass-border);border-radius:8px;padding:12px;text-align:center"><div style="font-size:1.6rem;font-weight:800;color:var(--ac)">${r.totals?.wall_length_m||0}</div><div style="font-size:.5rem;color:var(--mu);margin-top:4px">WALL LENGTH m</div></div>`;
    html+=`<div style="flex:1;min-width:120px;background:var(--glass);border:var(--glass-border);border-radius:8px;padding:12px;text-align:center"><div style="font-size:1.6rem;font-weight:800;color:var(--a4)">${r.totals?.doors||0}/${r.totals?.windows||0}</div><div style="font-size:.5rem;color:var(--mu);margin-top:4px">DOORS / WINDOWS</div></div>`;
    html+=`</div><table class="bom-table"><tr><th>Category</th><th>Item</th><th style="text-align:right">Qty</th><th>Unit</th></tr>`;
    (r.bom||[]).forEach(i=>{html+=`<tr><td class="bom-cat">${i.category}</td><td>${i.item}</td><td class="bom-qty">${i.quantity}</td><td>${i.unit}</td></tr>`});
    html+=`</table>`;body.innerHTML=html;
    document.getElementById('bomPanel').classList.add('show');
  }catch(e){setStatus('BOM error: '+e.message,'err')}
}
function closeBOM(){document.getElementById('bomPanel').classList.remove('show')}

async function showCompliance(){
  if(!data){setStatus('No model loaded','err');return}
  try{
    const resp=await fetch(API+'/compliance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,world_size:P.world,wall_height:gN('a-wh',2.8),step_rise:gN('a-sr',.18)})});
    const r=await resp.json();const body=document.getElementById('compBody');
    const score=r.summary?.score||0;const cls=score>=80?'good':score>=50?'ok':'bad';
    let html=`<div class="comp-score ${cls}">${score}/100</div>`;
    html+=`<div style="text-align:center;margin-bottom:16px;font-family:JetBrains Mono,monospace;font-size:.6rem;color:var(--mu)">${r.summary?.errors||0} errors · ${r.summary?.warnings||0} warnings · ${r.summary?.passed||0} passed</div>`;
    (r.issues||[]).forEach(i=>{html+=`<div class="comp-item error"><span class="comp-icon">❌</span><div class="comp-text">${i.message}<div class="comp-code">${i.code}</div></div></div>`});
    (r.warnings||[]).forEach(i=>{html+=`<div class="comp-item warning"><span class="comp-icon">⚠️</span><div class="comp-text">${i.message}<div class="comp-code">${i.code}</div></div></div>`});
    (r.passed||[]).forEach(i=>{html+=`<div class="comp-item passed"><span class="comp-icon">✅</span><div class="comp-text">${i.message}<div class="comp-code">${i.code}</div></div></div>`});
    body.innerHTML=html;document.getElementById('compPanel').classList.add('show');
  }catch(e){setStatus('Compliance error: '+e.message,'err')}
}
function closeCompliance(){document.getElementById('compPanel').classList.remove('show')}

// ═══════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════
function dl(text,name,type){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click()}
function exportOBJ(){if(!data)return;const IW=data.image_width,IH=data.image_height,WLD=P.world,px2=x=>x*(WLD/IW)-WLD/2,pz2=y=>y*(WLD/IH)-WLD/2,wH=gN('a-wh',2.8);let obj='# Floor Plan\n',v=1;
  [...(data.outer_walls||[]).map(w=>({...w,g:'outer'})),...(data.inner_walls||[]).map(w=>({...w,g:'inner'})),...(data.closets||[]).map(w=>({...w,g:'closet'}))].forEach((s,i)=>{const x1=px2(s.x1),z1=pz2(s.y1),x2=px2(s.x2),z2=pz2(s.y2),dx=x2-x1,dz=z2-z1,len=Math.sqrt(dx*dx+dz*dz);if(len<.04)return;const t=Math.max(.08,(s.thickness_px||8)*(WLD/IW)*P.thk*2),a=-Math.atan2(dz,dx),cos=Math.cos(a),sin=Math.sin(a),cx=(x1+x2)/2,cz=(z1+z2)/2;obj+=`\ng ${s.g}_${i+1}\n`;[[-len/2,0,-t/2],[len/2,0,-t/2],[len/2,wH,-t/2],[-len/2,wH,-t/2],[-len/2,0,t/2],[len/2,0,t/2],[len/2,wH,t/2],[-len/2,wH,t/2]].forEach(([lx,ly,lz])=>{obj+=`v ${(cx+cos*lx-sin*lz).toFixed(3)} ${ly.toFixed(3)} ${(cz+sin*lx+cos*lz).toFixed(3)}\n`});const o=v;v+=8;obj+=`f ${o} ${o+1} ${o+2} ${o+3}\nf ${o+4} ${o+5} ${o+6} ${o+7}\nf ${o} ${o+4} ${o+7} ${o+3}\nf ${o+1} ${o+5} ${o+6} ${o+2}\nf ${o} ${o+1} ${o+5} ${o+4}\nf ${o+3} ${o+2} ${o+6} ${o+7}\n`});
  dl(obj,'floor-plan.obj','text/plain')}
function exportGLTF(){if(!data)return;dl(JSON.stringify({format:'Floor Plan',theme:currentTheme,params:P,data:{outer_walls:data.outer_walls,inner_walls:data.inner_walls,closets:data.closets,windows:data.windows,doors:data.doors,stairs:data.stairs,rooms:data.rooms,fixtures:data.fixtures}},null,2),'floor-plan.gltf.json','application/json')}
async function exportSVG(){if(!data)return;try{const r=await fetch(API+'/export/svg',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(r.ok)dl(await r.text(),'floor-plan.svg','image/svg+xml')}catch{}}
async function exportDXF(){if(!data)return;try{const r=await fetch(API+'/export/dxf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(r.ok)dl(await r.text(),'floor-plan.dxf','application/dxf')}catch{}}
async function exportSTL(){if(!data)return;try{const r=await fetch(API+'/export/stl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,world_size:P.world,wall_height:gN('a-wh',2.8)})});if(r.ok){const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='floor-plan.stl';a.click()}}catch(e){setStatus('STL error: '+e.message,'err')}}
function exportScreenshot(){renderer.render(scene,camera);const a=document.createElement('a');a.download='floor-plan_screenshot.png';a.href=cvs.toDataURL('image/png');a.click()}

// P15: IFC Export
async function exportIFC(){if(!data)return;setStatus('Generating IFC…','');try{const r=await fetch(API+'/export/ifc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,world_size:P.world,wall_height:gN('a-wh',2.8)})});if(!r.ok){const e=await r.json().catch(()=>({error:r.statusText}));throw new Error(e.error||'IFC failed')}const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='floor-plan.ifc';a.click();setStatus('IFC exported ✓','ok')}catch(e){setStatus('IFC error: '+e.message,'err')}}

// P16: Research Metrics Dashboard
function showMetrics(){
  if(!data||!data.summary)return;
  const m=data.summary.metrics||{};
  const panel=document.getElementById('metricsPanel');
  const body=document.getElementById('metricsBody');
  let html='';
  // Timing breakdown
  html+='<div style="margin-bottom:12px"><b style="font-size:.75rem;color:var(--fg)">⏱ Pipeline Timing</b></div>';
  const timings=[
    {label:'Preprocess', ms:m.time_preprocess_ms||0, color:'#40b8f0'},
    {label:'Skeletonize', ms:m.time_skeleton_ms||0, color:'#f0a840'},
    {label:'Vectorize', ms:m.time_vectorize_ms||0, color:'#40f080'},
    {label:'Room Detection', ms:m.time_rooms_ms||0, color:'#f04080'},
  ];
  const maxMs=Math.max(1,...timings.map(t=>t.ms));
  timings.forEach(t=>{
    const pct=Math.round((t.ms/maxMs)*100);
    html+=`<div style="margin-bottom:6px"><div style="display:flex;justify-content:space-between;font-size:.65rem;color:var(--mu);margin-bottom:2px"><span>${t.label}</span><span>${t.ms} ms</span></div><div style="background:rgba(255,255,255,.05);border-radius:3px;overflow:hidden;height:8px"><div style="width:${pct}%;height:100%;background:${t.color};border-radius:3px;transition:width .5s"></div></div></div>`;
  });
  // Topology stats
  html+='<div style="margin:16px 0 8px"><b style="font-size:.75rem;color:var(--fg)">🧬 Topology Metrics</b></div>';
  html+='<table style="width:100%;font-size:.65rem;color:var(--mu);border-collapse:collapse">';
  html+=`<tr><td style="padding:3px 0">Total Nodes</td><td style="text-align:right;font-family:JetBrains Mono,monospace">${m.total_nodes||0}</td></tr>`;
  html+=`<tr><td style="padding:3px 0">Outer Walls</td><td style="text-align:right;font-family:JetBrains Mono,monospace">${data.summary.outer_walls||0}</td></tr>`;
  html+=`<tr><td style="padding:3px 0">Inner Walls</td><td style="text-align:right;font-family:JetBrains Mono,monospace">${data.summary.inner_walls||0}</td></tr>`;
  html+=`<tr><td style="padding:3px 0">Doors</td><td style="text-align:right;font-family:JetBrains Mono,monospace">${data.summary.doors||0}</td></tr>`;
  html+=`<tr><td style="padding:3px 0">Windows</td><td style="text-align:right;font-family:JetBrains Mono,monospace">${data.summary.windows||0}</td></tr>`;
  html+=`<tr><td style="padding:3px 0">Rooms</td><td style="text-align:right;font-family:JetBrains Mono,monospace">${data.summary.rooms||0}</td></tr>`;
  html+=`<tr><td style="padding:3px 0">Fixtures</td><td style="text-align:right;font-family:JetBrains Mono,monospace">${data.summary.fixtures||0}</td></tr>`;
  html+='</table>';
  // Validation summary
  html+='<div style="margin:16px 0 8px"><b style="font-size:.75rem;color:var(--fg)">🚨 Validation Summary</b></div>';
  const errs=validationErrors.filter(e=>e.type==='error').length;
  const warns=validationErrors.filter(e=>e.type==='warning').length;
  html+=`<div style="font-size:.65rem;color:var(--mu)">Errors: <b style="color:${errs>0?'#ff4444':'#40f080'}">${errs}</b> · Warnings: <b style="color:${warns>0?'#ffaa00':'#40f080'}">${warns}</b></div>`;
  body.innerHTML=html;
  panel.classList.add('show');
}
function closeMetrics(){document.getElementById('metricsPanel').classList.remove('show')}

function applyCalibration() {
  const input = document.getElementById('a-cal').value;
  const realLen = parseFloat(input);
  if (!realLen || !calibration.selectedWallLenPx) {
    setStatus('Please select a wall and enter a valid length.', 'err');
    return;
  }
  
  calibration.pxToMeter = realLen / calibration.selectedWallLenPx;
  if(data) {
    P.world = (realLen * data.image_width) / calibration.selectedWallLenPx;
    
    setStatus(`Calibration applied: Scale set to 1 px = ${calibration.pxToMeter.toFixed(4)}m`, 'ok');
    const calEl = document.getElementById('calStatus');
    calEl.textContent = `Applied! Model scaled to match.`;
    calEl.className = 'status ok';
    
    rebuild();
  }
}

// ═══════════════════════════════════════════════════════════════
// UI & EVENT BINDINGS
// ═══════════════════════════════════════════════════════════════
function rebuild(){if(data)build3D(data)}
function gN(id,def){return parseFloat(document.getElementById(id).value)||def}
function setP(p){document.getElementById('prog').style.width=p+'%'}
function setStatus(m,c){const e=document.getElementById('stat');e.textContent=m;e.className='status'+(c?' '+c:'')}
function showLoad(m){document.getElementById('load').classList.add('show');document.getElementById('lm').textContent=m}
function hideLoad(){document.getElementById('load').classList.remove('show')}
function tick(ms){return new Promise(r=>setTimeout(r,ms))}
function resetPipe(){document.querySelectorAll('.ps').forEach(e=>e.className='ps')}
function actStep(i){const e=document.getElementById('p'+i);if(e)e.className='ps active'}
function doneStep(i){const e=document.getElementById('p'+i);if(e)e.className='ps done'}
function togV(k,el){V[k]=V[k]?0:1;el.classList.toggle('on',!!V[k]);if(k==='iLights')rebuild();else rebuild()}
function toggleSec(sh){const body=sh.nextElementSibling;if(body){body.classList.toggle('hidden');sh.classList.toggle('collapsed')}}
function toggleFullscreen(){if(!document.fullscreenElement)document.documentElement.requestFullscreen();else document.exitFullscreen()}
function toggleKB(){document.getElementById('kbModal').classList.toggle('show')}
function updateStats(d){const s=d.summary||{};[['nw',s.outer_walls],['ni',s.inner_walls],['nc',s.closets],['nwin',s.windows],['nd',s.doors],['ns',s.stairs],['nr',s.rooms],['nf',s.fixtures]].forEach(([id,n])=>{const e=document.getElementById(id);if(e){e.textContent=n??'—';e.parentElement.classList.toggle('hi',(n||0)>0)}})}
function updateRooms(d){const c=document.getElementById('room-chips');c.innerHTML='';(d.rooms||[]).forEach(r=>{const ch=document.createElement('div');ch.className='rchip has';ch.innerHTML=r.label;ch.style.borderColor=r.color||'';ch.style.color=r.color||'';ch.onclick=()=>{if(!data)return;const IW=data.image_width,IH=data.image_height,WLD=P.world;animateCamera({x:r.cx*(WLD/IW)-WLD/2+6,y:8,z:r.cy*(WLD/IH)-WLD/2+6},{x:r.cx*(WLD/IW)-WLD/2,y:0,z:r.cy*(WLD/IH)-WLD/2},700)};c.appendChild(ch)})}
function updateDebug(d){if(!d.debug_images)return;[['di-pre','preprocessed'],['di-thk','thickness'],['di-cls','classification'],['di-sk','skeleton'],['di-rm','rooms']].forEach(([id,key])=>{const b=d.debug_images[key];if(b)document.getElementById(id).src='data:image/png;base64,'+b});document.getElementById('dbg-sec').style.display='block';const tbl=document.getElementById('thr-tbl');tbl.innerHTML='';const th=d.thresholds||{};[['t_line','Thin line'],['t_closet_max','Closet max'],['t_inner_max','Inner max'],['p10','p10'],['p35','p35'],['p75','p75'],['spread','Spread']].forEach(([k,l])=>{if(th[k]===undefined)return;const tr=document.createElement('tr');tr.innerHTML=`<td>${l}</td><td>${parseFloat(th[k]).toFixed(2)} px</td>`;tbl.appendChild(tr)});
  // Show thickness stats (P3)
  if(th.thickness_stats){const ts=th.thickness_stats;['outer','inner','closet','line'].forEach(cls=>{if(!ts[cls]||!ts[cls].count)return;const tr=document.createElement('tr');tr.innerHTML=`<td>${cls} orig_thick</td><td>${ts[cls].median} px (n=${ts[cls].count})</td>`;tbl.appendChild(tr)})}
}

// P6: Calibration
function applyCalibration(){
  const calEl=document.getElementById('calStatus');
  const realLen=parseFloat(document.getElementById('a-cal').value);
  if(!realLen||realLen<=0){calEl.textContent='Enter a valid length in meters.';calEl.className='status err';return}
  if(!calibration.selectedWallLenPx){calEl.textContent='Select a wall first (use Select tool or click a wall).';calEl.className='status err';return}
  if(!data){calEl.textContent='No model loaded.';calEl.className='status err';return}

  calibration.pxToMeter=realLen/calibration.selectedWallLenPx;
  P.world=calibration.pxToMeter*data.image_width;
  // Update the world slider
  const wsSlider=document.querySelector('#v-ws');
  if(wsSlider)wsSlider.textContent=P.world.toFixed(1)+'m';
  calEl.textContent=`Calibrated: 1px = ${(calibration.pxToMeter*1000).toFixed(2)} mm. World = ${P.world.toFixed(1)}m`;
  calEl.className='status ok';
  rebuild();
  currentTool='orbit';document.getElementById('tool-orbit').classList.add('on');
}

// ═══════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ═══════════════════════════════════════════════════════════════
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA')return;
  if(walkMode){if(['w','a','s','d'].includes(e.key.toLowerCase()))walkKeys[e.key.toLowerCase()]=true;if(e.key==='Shift')walkKeys.shift=true;if(e.key==='Escape')exitWalkMode();return}
  if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();toggleCmdBar();return}
  if(e.key==='1')setTool('orbit',document.getElementById('tool-orbit'));
  if(e.key==='2')setTool('measure',document.getElementById('tool-measure'));
  if(e.key==='3')setTool('select',document.getElementById('tool-select'));
  if(e.key==='4')setTool('addwall',document.getElementById('tool-addwall'));
  if(e.key==='5')setTool('walk',document.getElementById('tool-walk'));
  if(e.key==='z'&&(e.ctrlKey||e.metaKey)&&!e.shiftKey){undoAction();e.preventDefault()}
  if(e.key==='y'&&(e.ctrlKey||e.metaKey)){redoAction();e.preventDefault()}
  if(e.key==='Delete'||e.key==='Backspace'){deleteSelected();e.preventDefault()}
  if(e.key==='w'||e.key==='W'){V.wire=V.wire?0:1;rebuild()}
  if(e.key==='c'||e.key==='C')toggleClipping(document.getElementById('tog-clip'));
  if(e.key==='f'||e.key==='F')toggleFullscreen();
  if(e.key==='p'||e.key==='P')exportScreenshot();
  if(e.key==='v'||e.key==='V')toggleVoice();
  if(e.key==='?'||e.key==='/')toggleKB();
  if(e.key==='Escape'){clearSelection();clearMeasure();if(document.getElementById('kbModal').classList.contains('show'))toggleKB();if(document.getElementById('cmdOverlay').classList.contains('show'))toggleCmdBar()}
});
document.addEventListener('keyup',e=>{if(walkMode){if(['w','a','s','d'].includes(e.key.toLowerCase()))walkKeys[e.key.toLowerCase()]=false;if(e.key==='Shift')walkKeys.shift=false}});

// ═══════════════════════════════════════════════════════════════
// RENDER LOOP
// ═══════════════════════════════════════════════════════════════
let lastFps=performance.now(),fpsCt=0;
(function loop(){
  requestAnimationFrame(loop);fpsCt++;
  if(walkMode)updateWalk();
  else if(!drag&&!data&&!animating){sph.th+=.002;camUpd()}
  // P5: Adaptive damping (when not dragging)
  if(!drag&&!walkMode&&!animating){const df=getCameraScale().damp;dampVel.th*=df;dampVel.ph*=df;if(Math.abs(dampVel.th)>.0001){sph.th+=dampVel.th;sph.ph=Math.max(.08,Math.min(Math.PI/2.05,sph.ph+dampVel.ph));camUpd()}}
  renderer.render(scene,camera);
  const now=performance.now();if(now-lastFps>=1000){document.getElementById('fpsCounter').textContent=fpsCt+' FPS · '+renderer.info.render.triangles.toLocaleString()+' △';fpsCt=0;lastFps=now;updateMinimap()}
})();

// Particles
(()=>{const g=new THREE.BufferGeometry(),N=200,p=new Float32Array(N*3);for(let i=0;i<N;i++){p[i*3]=(Math.random()-.5)*80;p[i*3+1]=Math.random()*12;p[i*3+2]=(Math.random()-.5)*80}g.setAttribute('position',new THREE.BufferAttribute(p,3));scene.add(new THREE.Points(g,new THREE.PointsMaterial({color:0x101830,size:.06,transparent:true,opacity:.35})))})();
const hoverRay=new THREE.Raycaster();let hoveredObj=null,lastEmissive=null;
let previewWall = null;
window.addEventListener('pointermove',e=>{
  if (currentTool==='addwall' && addWallStart && grp) {
     const r=cvs.getBoundingClientRect();const mx=((e.clientX-r.left)/r.width)*2-1,my=-((e.clientY-r.top)/r.height)*2+1;
     hoverRay.setFromCamera({x:mx,y:my},camera);
     const pl=new THREE.Plane(new THREE.Vector3(0,1,0),0),pt=new THREE.Vector3();
     hoverRay.ray.intersectPlane(pl,pt);
     if(pt) {
        if(data) {
           const allWalls = [...(data.outer_walls||[]), ...(data.inner_walls||[])];
           const IW=data.image_width, IH=data.image_height, WLD=P.world;
           const px = x => x*(WLD/IW)-WLD/2, pz = y => y*(WLD/IH)-WLD/2;
           let bestDist = 0.5, bestPt = null;
           allWalls.forEach(w => {
              if(w.x1 !== undefined) {
                 if(Math.hypot(pt.x-px(w.x1), pt.z-pz(w.y1)) < bestDist) { bestDist = Math.hypot(pt.x-px(w.x1), pt.z-pz(w.y1)); bestPt = {x:px(w.x1), z:pz(w.y1)}; }
                 if(Math.hypot(pt.x-px(w.x2), pt.z-pz(w.y2)) < bestDist) { bestDist = Math.hypot(pt.x-px(w.x2), pt.z-pz(w.y2)); bestPt = {x:px(w.x2), z:pz(w.y2)}; }
              }
           });
           if(bestPt) { pt.x = bestPt.x; pt.z = bestPt.z; }
        }
        if(e.shiftKey) {
            const dx = pt.x - addWallStart.x;
            const dz = pt.z - addWallStart.z;
            if (Math.abs(dx) > Math.abs(dz)) pt.z = addWallStart.z;
            else pt.x = addWallStart.x;
        }
        if(!previewWall) {
           const geo = new THREE.BufferGeometry().setFromPoints([addWallStart, pt]);
           previewWall = new THREE.Line(geo, new THREE.LineBasicMaterial({color:0x40f090, linewidth:3}));
           previewWall.position.y = 0.1;
           grp.add(previewWall);
        } else {
           previewWall.geometry.setFromPoints([addWallStart, pt]);
        }
     }
  } else if (previewWall && grp) {
     grp.remove(previewWall);
     previewWall = null;
  }

  if(currentTool==='select'&&grp){
    const r=cvs.getBoundingClientRect();const mx=((e.clientX-r.left)/r.width)*2-1,my=-((e.clientY-r.top)/r.height)*2+1;
    hoverRay.setFromCamera({x:mx,y:my},camera);const hits=hoverRay.intersectObjects(grp.children,false);
    let hit=hits.find(h=>h.object.userData&&h.object.userData.type&&h.object.userData.type!=='added');
    if(hit){
      if(hoveredObj!==hit.object){
        if(hoveredObj&&hoveredObj!==selectedObject&&hoveredObj.material.emissive)hoveredObj.material.emissive.setHex(lastEmissive);
        hoveredObj=hit.object;
        if(hoveredObj!==selectedObject&&hoveredObj.material.emissive){lastEmissive=hoveredObj.material.emissive.getHex();hoveredObj.material.emissive.setHex(0x2d68c4);}
      }
    }else{
      if(hoveredObj){if(hoveredObj!==selectedObject&&hoveredObj.material.emissive)hoveredObj.material.emissive.setHex(lastEmissive);hoveredObj=null;}
    }
  }else if(hoveredObj){
    if(hoveredObj!==selectedObject&&hoveredObj.material.emissive)hoveredObj.material.emissive.setHex(lastEmissive);hoveredObj=null;
  }
});

// Cancel wall tool polyline
window.addEventListener('contextmenu', e => {
  if (currentTool === 'addwall' && addWallStart) {
    addWallStart = null;
    clearMeasure(); // removes dots
    e.preventDefault();
  }
});
