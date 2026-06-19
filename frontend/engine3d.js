// ═══════════════════════════════════════════════════════════════
// THREE.JS CORE
// ═══════════════════════════════════════════════════════════════
const API='',cvs=document.getElementById('c3'),vpEl=document.getElementById('vp');
const renderer=new THREE.WebGLRenderer({canvas:cvs,antialias:true,preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.12;
renderer.localClippingEnabled=true;

const scene=new THREE.Scene();scene.background=new THREE.Color(0xEEF0F4);
scene.fog=new THREE.Fog(0xEEF0F4,45,110);

const camera=new THREE.PerspectiveCamera(56,1,0.01,250);camera.position.set(16,18,16);

// Lights
const ambientLight=new THREE.AmbientLight(0x334466,.85);scene.add(ambientLight);
const sun=new THREE.DirectionalLight(0xfff8e0,2.8);
sun.position.set(22,35,14);sun.castShadow=true;
sun.shadow.mapSize.set(2048,2048);
Object.assign(sun.shadow.camera,{near:.1,far:150,left:-40,right:40,top:40,bottom:-40});
scene.add(sun);
scene.add(new THREE.DirectionalLight(0x4080cc,.55).translateX(-14).translateY(10).translateZ(-12));
scene.add(new THREE.HemisphereLight(0x88aabb,0x112211,.35));

// Helper: create mesh and set position/rotation (Object.assign fails on read-only properties)
function mkM(geo,mat,px,py,pz,rx,ry,rz,ud){
  let useMat = mat;
  if(ud && ud.type && ud.index !== undefined && userEdits.materials[ud.type+'_'+ud.index]) {
    useMat = mat.clone();
    useMat.map = userEdits.materials[ud.type+'_'+ud.index];
    useMat.color.setHex(0xffffff); // clear base color so map shows purely
    useMat.needsUpdate = true;
  }
  const m=new THREE.Mesh(geo,useMat);m.position.set(px||0,py||0,pz||0);if(rx||ry||rz)m.rotation.set(rx||0,ry||0,rz||0);if(ud)m.userData=ud;m.castShadow=m.receiveShadow=true;return m
}

const gridHelper=new THREE.GridHelper(70,70,0xCFD4DC,0xE2E6EB);gridHelper.position.y=-.02;scene.add(gridHelper);
const interiorLightsGrp=new THREE.Group();scene.add(interiorLightsGrp);

// Clipping
const clipPlanes=[new THREE.Plane(new THREE.Vector3(-1,0,0),15),new THREE.Plane(new THREE.Vector3(0,0,-1),15),new THREE.Plane(new THREE.Vector3(0,-1,0),3)];
let clippingEnabled=false;

// Orbit
let drag=false,rightDrag=false,pM={x:0,y:0},sph={th:Math.PI/4,ph:Math.PI/3.5,r:28};
const tgt=new THREE.Vector3(0,1.5,0);
let dampVel={th:0,ph:0}; // damping

// P5: Adaptive camera scale
function getCameraScale(){
  const bbSize=P.world||20;
  const distFactor=Math.max(0.5,sph.r/15);
  return {
    rotate: 0.005 * (bbSize/20) / distFactor,
    pan: 0.01 * (bbSize/20),
    zoom: 0.025 * (bbSize/20),
    damp: Math.min(0.95, Math.max(0.85, 0.88 + sph.r * 0.001))
  };
}

function camUpd(){
  camera.position.set(tgt.x+sph.r*Math.sin(sph.ph)*Math.sin(sph.th),tgt.y+sph.r*Math.cos(sph.ph),tgt.z+sph.r*Math.sin(sph.ph)*Math.cos(sph.th));
  camera.lookAt(tgt);
}

// Smooth damping orbit + drag logic
let dragOffset = new THREE.Vector3();
cvs.addEventListener('mousedown',e=>{
  if(walkMode)return;
  if(e.button===2){rightDrag=true;pM={x:e.clientX,y:e.clientY};e.preventDefault();return}
  if(currentTool==='select'){
    handleToolClick(e);
    if(selectedObject && selectedObject.userData && ['bed frame','sofa','table','rug'].includes(selectedObject.userData.type)){
      draggedObject = selectedObject;
      const rect=cvs.getBoundingClientRect();const mx=((e.clientX-rect.left)/rect.width)*2-1,my=-((e.clientY-rect.top)/rect.height)*2+1;
      raycaster.setFromCamera({x:mx,y:my},camera);
      const pl=new THREE.Plane(new THREE.Vector3(0,1,0),0), pt=new THREE.Vector3(); raycaster.ray.intersectPlane(pl,pt);
      if(pt) dragOffset.copy(draggedObject.position).sub(pt);
      return; // prevent orbit
    }
  } else if(currentTool.startsWith('furn_')) {
    handleToolClick(e); return;
  }
  if(currentTool!=='orbit'&&currentTool!=='calibrate'&&currentTool!=='select'){handleToolClick(e);return}
  if(currentTool==='calibrate'||currentTool==='select'){if(currentTool==='calibrate')handleToolClick(e);return}
  drag=true;pM={x:e.clientX,y:e.clientY};
});
cvs.addEventListener('contextmenu',e=>e.preventDefault());
addEventListener('mouseup',e=>{drag=false;rightDrag=false;
  if(draggedObject){
    const ud = draggedObject.userData;
    if(ud && ud.index !== undefined && data.furniture && data.furniture[ud.index]) {
      const IW=data.image_width, IH=data.image_height, WLD=P.world;
      data.furniture[ud.index].cx = (draggedObject.position.x + WLD/2) * (IW/WLD);
      data.furniture[ud.index].cy = (draggedObject.position.z + WLD/2) * (IH/WLD);
    }
    draggedObject=null;
  }
});
addEventListener('mousemove',e=>{
  if(walkMode)return;
  if(draggedObject){
    const rect=cvs.getBoundingClientRect();const mx=((e.clientX-rect.left)/rect.width)*2-1,my=-((e.clientY-rect.top)/rect.height)*2+1;
    raycaster.setFromCamera({x:mx,y:my},camera);
    const pl=new THREE.Plane(new THREE.Vector3(0,1,0),0), pt=new THREE.Vector3(); raycaster.ray.intersectPlane(pl,pt);
    if(pt){
      draggedObject.position.x = pt.x + dragOffset.x;
      draggedObject.position.z = pt.z + dragOffset.z;
    }
    return;
  }
  const cs=getCameraScale();
  // Right-click pan
  if(rightDrag){
    const panX=(e.clientX-pM.x)*cs.pan*sph.r*0.003;
    const panY=(e.clientY-pM.y)*cs.pan*sph.r*0.003;
    const right=new THREE.Vector3();camera.getWorldDirection(right);right.cross(camera.up).normalize();
    const up=new THREE.Vector3(0,1,0);
    tgt.addScaledVector(right,-panX);
    tgt.addScaledVector(up,panY);
    pM={x:e.clientX,y:e.clientY};camUpd();return;
  }
  if(currentTool!=='orbit'||!drag)return;
  const dx=(e.clientX-pM.x)*cs.rotate,dy=(e.clientY-pM.y)*cs.rotate;
  dampVel.th=-dx;dampVel.ph=dy;
  sph.th+=dampVel.th;sph.ph=Math.max(.08,Math.min(Math.PI/2.05,sph.ph+dampVel.ph));
  pM={x:e.clientX,y:e.clientY};camUpd();
});
cvs.addEventListener('wheel',e=>{if(!walkMode){const cs=getCameraScale();sph.r=Math.max(3,Math.min(90,sph.r+e.deltaY*cs.zoom));camUpd();e.preventDefault()}},{passive:false});

// Double-click to focus
cvs.addEventListener('dblclick',e=>{
  if(walkMode||!grp)return;
  const rect=cvs.getBoundingClientRect();
  const mx=((e.clientX-rect.left)/rect.width)*2-1;
  const my=-((e.clientY-rect.top)/rect.height)*2+1;
  raycaster.setFromCamera(new THREE.Vector2(mx,my),camera);
  const hits=raycaster.intersectObjects(grp.children,false);
  if(hits.length){
    const p=hits[0].point;
    animateCamera({x:p.x+6,y:8,z:p.z+6},{x:p.x,y:0,z:p.z},600);
  }
});

// Touch
let ltd=0;
cvs.addEventListener('touchstart',e=>{if(e.touches.length===1){drag=true;pM={x:e.touches[0].clientX,y:e.touches[0].clientY}}if(e.touches.length===2)ltd=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY)});
cvs.addEventListener('touchmove',e=>{const cs=getCameraScale();if(e.touches.length===1&&drag){sph.th-=(e.touches[0].clientX-pM.x)*cs.rotate;sph.ph=Math.max(.08,Math.min(Math.PI/2.05,sph.ph+(e.touches[0].clientY-pM.y)*cs.rotate));pM={x:e.touches[0].clientX,y:e.touches[0].clientY};camUpd()}if(e.touches.length===2){const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);sph.r=Math.max(3,Math.min(90,sph.r-(d-ltd)*cs.zoom*1.6));ltd=d;camUpd()}e.preventDefault()},{passive:false});
cvs.addEventListener('touchend',()=>drag=false);

function resize(){const w=vpEl.clientWidth,h=vpEl.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}
resize();new ResizeObserver(resize).observe(vpEl);camUpd();

// ═══════════════════════════════════════════════════════════════
// WALK MODE (First Person)
// ═══════════════════════════════════════════════════════════════
let walkMode=false,walkKeys={w:false,a:false,s:false,d:false,shift:false};
let walkYaw=0,walkPitch=0;
const WALK_SPEED=.12,WALK_EYE=1.7;

function enterWalkMode(){
  walkMode=true;walkYaw=0;walkPitch=0;
  camera.position.set(0,WALK_EYE,0);
  document.getElementById('walkHud').classList.add('show');
  document.getElementById('vmode').textContent='FIRST PERSON';
  cvs.requestPointerLock();
}
function exitWalkMode(){
  walkMode=false;
  document.getElementById('walkHud').classList.remove('show');
  document.exitPointerLock();
  setView('persp',document.querySelector('.cb'));camUpd();
}

document.addEventListener('pointerlockchange',()=>{if(!document.pointerLockElement&&walkMode)exitWalkMode()});
cvs.addEventListener('mousemove',e=>{
  if(!walkMode||!document.pointerLockElement)return;
  walkYaw-=e.movementX*.002;walkPitch=Math.max(-1.2,Math.min(1.2,walkPitch-e.movementY*.002));
});

function updateWalk(){
  if(!walkMode)return;
  const spd=walkKeys.shift?WALK_SPEED*2:WALK_SPEED;
  const dx=Math.sin(walkYaw)*spd,dz=Math.cos(walkYaw)*spd;
  let nx = camera.position.x, nz = camera.position.z;
  
  if(walkKeys.w){nx-=dx;nz-=dz}
  if(walkKeys.s){nx+=dx;nz+=dz}
  if(walkKeys.a){nx-=dz;nz+=dx}
  if(walkKeys.d){nx+=dz;nz-=dx}

  if(grp && (nx !== camera.position.x || nz !== camera.position.z)) {
      const collidables = grp.children.filter(c => c.userData && ['outer','inner','closet','door','window'].includes(c.userData.type));
      const testMove = (targetX, targetZ) => {
          const dir = new THREE.Vector3(targetX - camera.position.x, 0, targetZ - camera.position.z);
          const dist = dir.length();
          if(dist < 0.001) return true;
          dir.normalize();
          const ray = new THREE.Raycaster(camera.position, dir, 0, dist + 0.3);
          return ray.intersectObjects(collidables, false).length === 0;
      };
      
      if(!testMove(nx, nz)) {
          // Attempt sliding
          let canX = testMove(nx, camera.position.z);
          let canZ = testMove(camera.position.x, nz);
          if(canX) nz = camera.position.z;
          else if(canZ) nx = camera.position.x;
          else { nx = camera.position.x; nz = camera.position.z; }
      }
  }

  camera.position.x = nx;
  camera.position.z = nz;
  camera.position.y=WALK_EYE;
  camera.rotation.order='YXZ';
  camera.rotation.y=walkYaw;camera.rotation.x=walkPitch;
}

// ═══════════════════════════════════════════════════════════════
// ANIMATED CAMERA TRANSITIONS
// ═══════════════════════════════════════════════════════════════
let animating=false;
function animateCamera(toPos,toTgt,dur=800){
  if(animating)return;animating=true;
  const fromPos={x:camera.position.x,y:camera.position.y,z:camera.position.z};
  const fromTgt={x:tgt.x,y:tgt.y,z:tgt.z};
  const start=performance.now();
  function step(now){
    const t=Math.min(1,(now-start)/dur);
    const e=t<.5?2*t*t:1-Math.pow(-2*t+2,2)/2; // easeInOut
    camera.position.set(fromPos.x+(toPos.x-fromPos.x)*e,fromPos.y+(toPos.y-fromPos.y)*e,fromPos.z+(toPos.z-fromPos.z)*e);
    tgt.set(fromTgt.x+(toTgt.x-fromTgt.x)*e,fromTgt.y+(toTgt.y-fromTgt.y)*e,fromTgt.z+(toTgt.z-fromTgt.z)*e);
    camera.lookAt(tgt);
    if(t<1)requestAnimationFrame(step);else{animating=false;
      // Update spherical from final position
      const dx=camera.position.x-tgt.x,dy=camera.position.y-tgt.y,dz=camera.position.z-tgt.z;
      sph.r=Math.sqrt(dx*dx+dy*dy+dz*dz);sph.ph=Math.acos(dy/sph.r);sph.th=Math.atan2(dx,dz);
    }
  }
  requestAnimationFrame(step);
}

// ═══════════════════════════════════════════════════════════════
// PROCEDURAL TEXTURES
// ═══════════════════════════════════════════════════════════════
function mkTex(w,h,fn){const c=document.createElement('canvas');c.width=w;c.height=h;fn(c.getContext('2d'),w,h);const t=new THREE.CanvasTexture(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function texBrick(){return mkTex(256,256,(ctx,w,h)=>{ctx.fillStyle='#b8906a';ctx.fillRect(0,0,w,h);const bw=w/4,bh=h/8;for(let r=0;r<8;r++){const o=(r%2)*(bw/2);for(let c=-1;c<5;c++){const x=c*bw+o,y=r*bh,v=Math.random()*20-10;ctx.fillStyle=`rgb(${164+v},${120+v},${88+v})`;ctx.fillRect(x+1,y+1,bw-2,bh-2);ctx.strokeStyle='rgba(80,60,40,0.4)';ctx.lineWidth=1;ctx.strokeRect(x+1,y+1,bw-2,bh-2)}}})}
function texDrywall(){return mkTex(128,128,(ctx,w,h)=>{ctx.fillStyle='#e8e4dc';ctx.fillRect(0,0,w,h);for(let i=0;i<500;i++){ctx.fillStyle=`rgba(${180+Math.random()*30},${175+Math.random()*30},${165+Math.random()*30},0.3)`;ctx.fillRect(Math.random()*w,Math.random()*h,1+Math.random()*2,1+Math.random()*2)}})}
function texWood(){return mkTex(256,128,(ctx,w,h)=>{ctx.fillStyle='#8b6914';ctx.fillRect(0,0,w,h);for(let y=0;y<h;y++){const v=Math.sin(y*0.15)*8+Math.sin(y*0.05+2)*12;ctx.fillStyle=`rgba(${120+v},${80+v*0.7},${20+v*0.3},0.5)`;ctx.fillRect(0,y,w,1)}})}
function texConcrete(){return mkTex(128,128,(ctx,w,h)=>{ctx.fillStyle='#888';ctx.fillRect(0,0,w,h);for(let i=0;i<800;i++){const v=Math.random()*30;ctx.fillStyle=`rgba(${120+v},${120+v},${120+v},0.3)`;ctx.fillRect(Math.random()*w,Math.random()*h,1+Math.random()*3,1+Math.random()*3)}})}
function texTile(){return mkTex(256,256,(ctx,w,h)=>{ctx.fillStyle='#d0d0d0';ctx.fillRect(0,0,w,h);ctx.strokeStyle='#aaa';ctx.lineWidth=2;for(let x=0;x<=w;x+=64){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke()}for(let y=0;y<=h;y+=64){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}})}

// ═══════════════════════════════════════════════════════════════
// MATERIAL THEMES
// ═══════════════════════════════════════════════════════════════
const THEMES={
  modern:{
    oWall:()=>new THREE.MeshStandardMaterial({color:0xf0ece4,roughness:.75,metalness:.02,map:texDrywall()}),
    iWall:()=>new THREE.MeshStandardMaterial({color:0xe8e4dc,roughness:.72,metalness:.04,map:texDrywall()}),
    closet:()=>new THREE.MeshStandardMaterial({color:0xc0a880,roughness:.65,metalness:.08,transparent:true,opacity:.85,map:texWood()}),
    cSlide:()=>new THREE.MeshStandardMaterial({color:0xd0c0a0,roughness:.55,metalness:.12}),
    glass:()=>new THREE.MeshPhysicalMaterial({color:0x88ddff,roughness:.05,metalness:.1,transmission:.9,ior:1.5,transparent:true,side:THREE.DoubleSide}),
    wFrame:()=>new THREE.MeshStandardMaterial({color:0x333333,roughness:.25,metalness:.6}),
    lintel:()=>new THREE.MeshStandardMaterial({color:0xe0dcd0,roughness:.85,metalness:.02}),
    dPanel:()=>new THREE.MeshStandardMaterial({color:0xf8f4ee,roughness:.55,metalness:.04}),
    dFrame:()=>new THREE.MeshStandardMaterial({color:0x404040,roughness:.45,metalness:.3}),
    stair:()=>new THREE.MeshStandardMaterial({color:0xd0c8b8,roughness:.72,metalness:.06}),
    sNose:()=>new THREE.MeshStandardMaterial({color:0xa09888,roughness:.45,metalness:.15}),
    floor:()=>new THREE.MeshStandardMaterial({color:0x0c1218,roughness:.94}),
  },
  classic:{
    oWall:()=>new THREE.MeshStandardMaterial({color:0xd4b896,roughness:.88,metalness:.02,map:texBrick()}),
    iWall:()=>new THREE.MeshStandardMaterial({color:0xc8b8a0,roughness:.82,metalness:.03,map:texDrywall()}),
    closet:()=>new THREE.MeshStandardMaterial({color:0x806030,roughness:.78,metalness:.04,transparent:true,opacity:.82,map:texWood()}),
    cSlide:()=>new THREE.MeshStandardMaterial({color:0x906838,roughness:.65,metalness:.08}),
    glass:()=>new THREE.MeshPhysicalMaterial({color:0x90d8f0,roughness:.05,metalness:.1,transmission:.85,ior:1.5,transparent:true,side:THREE.DoubleSide}),
    wFrame:()=>new THREE.MeshStandardMaterial({color:0xf8f0e8,roughness:.35,metalness:.2}),
    lintel:()=>new THREE.MeshStandardMaterial({color:0xa09080,roughness:.92,metalness:.02}),
    dPanel:()=>new THREE.MeshStandardMaterial({color:0x8b6914,roughness:.72,metalness:.04,map:texWood()}),
    dFrame:()=>new THREE.MeshStandardMaterial({color:0x6b4910,roughness:.78,metalness:.04}),
    stair:()=>new THREE.MeshStandardMaterial({color:0xb8a070,roughness:.8,metalness:.05}),
    sNose:()=>new THREE.MeshStandardMaterial({color:0xc8b480,roughness:.5,metalness:.1}),
    floor:()=>new THREE.MeshStandardMaterial({color:0x0c1218,roughness:.94}),
  },
  industrial:{
    oWall:()=>new THREE.MeshStandardMaterial({color:0x909090,roughness:.92,metalness:.08,map:texConcrete()}),
    iWall:()=>new THREE.MeshStandardMaterial({color:0x808080,roughness:.88,metalness:.1,map:texConcrete()}),
    closet:()=>new THREE.MeshStandardMaterial({color:0x606060,roughness:.7,metalness:.25,transparent:true,opacity:.85}),
    cSlide:()=>new THREE.MeshStandardMaterial({color:0x505050,roughness:.5,metalness:.4}),
    glass:()=>new THREE.MeshPhysicalMaterial({color:0x60b8d8,roughness:.05,metalness:.1,transmission:.95,ior:1.5,transparent:true,side:THREE.DoubleSide}),
    wFrame:()=>new THREE.MeshStandardMaterial({color:0x2a2a2a,roughness:.3,metalness:.7}),
    lintel:()=>new THREE.MeshStandardMaterial({color:0x707070,roughness:.9,metalness:.15}),
    dPanel:()=>new THREE.MeshStandardMaterial({color:0x404040,roughness:.65,metalness:.35}),
    dFrame:()=>new THREE.MeshStandardMaterial({color:0x303030,roughness:.55,metalness:.5}),
    stair:()=>new THREE.MeshStandardMaterial({color:0x787878,roughness:.75,metalness:.2}),
    sNose:()=>new THREE.MeshStandardMaterial({color:0x606060,roughness:.45,metalness:.35}),
    floor:()=>new THREE.MeshStandardMaterial({color:0x080c12,roughness:.96}),
  }
};
let currentTheme='modern',M={};
function applyTheme(n){currentTheme=n;const t=THEMES[n];M={};for(const k in t)M[k]=t[k]();M.edge=new THREE.LineBasicMaterial({color:0x706050,transparent:true,opacity:.1});M.wire=new THREE.MeshStandardMaterial({wireframe:true,color:0xd4c8a8,transparent:true,opacity:.25});M.fixture=new THREE.MeshStandardMaterial({color:0xe0e0e0,roughness:.3,metalness:.5});M.fixChrome=new THREE.MeshStandardMaterial({color:0xcccccc,roughness:.1,metalness:.85});M.fixWater=new THREE.MeshStandardMaterial({color:0x80ccee,roughness:.05,metalness:.3,transparent:true,opacity:.4})}
applyTheme('modern');

// ═══ STATE ═══
let grp=null,data=null,imgFile=null,P={world:20,thk:1.0,orthoTol:0.5}; // P8
let V={sO:1,sI:1,sC:1,sW:1,sD:1,sS:1,sF:1,sR:1,sRF:1,sFX:1,sRoof:0,wire:0,iLights:0};
let currentTool='orbit',selectedObject=null,draggedObject=null,measurePoints=[],measureLine=null,measureLabels=[],addWallStart=null;
let calibration={active:false,pxToMeter:null,selectedWallLenPx:null}; // P6
const undoStack=[],redoStack=[],userEdits={addedWalls:[],deletedIds:new Set(),materials:{}};
const raycaster=new THREE.Raycaster(),mouse=new THREE.Vector2();
let validationErrors=[]; // P10

// ═══════════════════════════════════════════════════════════════

// BIM VALIDATION, TOPOLOGY & HEALING (P9, P10, P11, P12)
// ═══════════════════════════════════════════════════════════════

function validateModel(d){
  validationErrors=[];
  if(!d)return;
  // Check rooms
  (d.rooms||[]).forEach((r, i)=>{
    if(!r.boundary_closed){
      if(r.validation==='bridged'){
        validationErrors.push({type:'warning', msg:`Room ${i+1}: Open boundary was bridged`, objType:'room', idx:i, bbox:r.bbox});
      } else {
        validationErrors.push({type:'error', msg:`Room ${i+1}: Unclosed boundary`, objType:'room', idx:i, bbox:r.bbox});
      }
    }
  });
  // Check doors
  (d.doors||[]).forEach((dr, i)=>{
    if(dr.wallId===-1 || dr.wallId===undefined) validationErrors.push({type:'error', msg:`Door ${i+1}: Floating (not snapped to wall)`, objType:'door', idx:i, cx:dr.cx, cy:dr.cy});
  });
  // Check windows
  (d.windows||[]).forEach((w, i)=>{
    if(w.wallId===-1 || w.wallId===undefined) validationErrors.push({type:'error', msg:`Window ${i+1}: Floating (not snapped to wall)`, objType:'window', idx:i, cx:(w.x1+w.x2)/2, cy:(w.y1+w.y2)/2});
  });
  
  renderValidationUI();
}

function renderValidationUI(){
  const list=document.getElementById('valList');
  const stat=document.getElementById('valStatus');
  list.innerHTML='';
  if(!validationErrors.length){
    stat.textContent='No issues found.'; stat.style.color='var(--ok)';
    return;
  }
  const errCount=validationErrors.filter(e=>e.type==='error').length;
  const wrnCount=validationErrors.filter(e=>e.type==='warning').length;
  stat.textContent=`Found ${errCount} errors, ${wrnCount} warnings.`; stat.style.color=errCount>0?'#ff4444':'#ffaa00';
  
  validationErrors.forEach((e, arrIdx) => {
    const el=document.createElement('div');
    el.className='val-item';
    el.style.cssText=`font-size:0.65rem; padding:4px; margin-bottom:2px; border-radius:3px; cursor:pointer; background:rgba(0,0,0,0.2); border-left:3px solid ${e.type==='error'?'#ff4444':'#ffaa00'}`;
    el.innerHTML=`<b>${e.type.toUpperCase()}:</b> ${e.msg}`;
    el.onclick=()=>flyToError(arrIdx);
    list.appendChild(el);
  });
}

function flyToError(idx){
  if(!data || !grp) return;
  const e=validationErrors[idx];
  const IW=data.image_width, IH=data.image_height, WLD=P.world;
  let px=0, pz=0;
  
  if(e.bbox){
    px=(e.bbox[0]+e.bbox[2]/2)*(WLD/IW)-WLD/2;
    pz=(e.bbox[1]+e.bbox[3]/2)*(WLD/IH)-WLD/2;
  } else if(e.cx!==undefined){
    px=e.cx*(WLD/IW)-WLD/2;
    pz=e.cy*(WLD/IH)-WLD/2;
  } else return;
  
  animateCamera({x:px+4, y:6, z:pz+4}, {x:px, y:0, z:pz}, 800);
  
  // Highlight geometry
  let found=null;
  grp.children.forEach(c=>{
    if(c.userData && c.userData.type && c.userData.type.includes(e.objType)){
      if(e.objType==='door'){
        const wx=e.cx*(WLD/IW)-WLD/2, wz=e.cy*(WLD/IH)-WLD/2;
        if(Math.hypot(c.position.x-wx, c.position.z-wz)<0.5) found=c;
      }
      if(e.objType==='window'){
        const wx=e.cx*(WLD/IW)-WLD/2, wz=e.cy*(WLD/IH)-WLD/2;
        if(Math.hypot(c.position.x-wx, c.position.z-wz)<0.5) found=c;
      }
      if(e.objType==='room'){
        if(c.userData.index===e.idx) found=c;
      }
    }
  });
  if(found && found.material && found.material.emissive){
    const old=found.material.emissive.getHex();
    found.material.emissive.setHex(0xff0000);
    setTimeout(()=>found.material.emissive.setHex(old), 1500);
  }
}

function autoHeal(){
  if(!data) return;
  let healedCount=0;
  
  // Heal floating doors by forcing snap to nearest any wall
  const allWalls=[...(data.outer_walls||[]), ...(data.inner_walls||[]), ...(data.closets||[])];
  (data.doors||[]).forEach(dr=>{
    if(dr.wallId===-1 || dr.wallId===undefined){
      let bestW=null, bestD=Infinity, bestT=0;
      allWalls.forEach(w=>{
        const L=Math.hypot(w.x2-w.x1, w.y2-w.y1);
        if(L<1)return;
        const t=((dr.cx-w.x1)*(w.x2-w.x1) + (dr.cy-w.y1)*(w.y2-w.y1))/(L*L);
        const tc=Math.max(0.01, Math.min(0.99, t));
        const projx=w.x1+tc*(w.x2-w.x1), projy=w.y1+tc*(w.y2-w.y1);
        const dist=Math.hypot(dr.cx-projx, dr.cy-projy);
        if(dist<bestD && dist<50){bestD=dist;bestW=w;bestT=tc;}
      });
      if(bestW){
        dr.wallId=bestW.id; dr.position_t=bestT;
        bestW.openings=bestW.openings||[];
        bestW.openings.push({type:'door', position_t:bestT, span:dr.radius_px/Math.hypot(bestW.x2-bestW.x1, bestW.y2-bestW.y1), width_px:dr.radius_px*2, door_data:dr});
        healedCount++;
      }
    }
  });
  
  // Heal bridged gaps by injecting invisible bridge walls
  let newW=0;
  (data.rooms||[]).forEach(r=>{
    if(r.bridged_gaps && r.bridged_gaps.length && !r.boundary_closed){
      r.bridged_gaps.forEach(g=>{
        const wd={
          id: Date.now()+Math.random(),
          x1: g.from[0], y1: g.from[1], x2: g.to[0], y2: g.to[1],
          thickness_px: 2, original_thickness_px: 2,
          openings: [], length_px: g.gap_px
        };
        data.inner_walls.push(wd);
        newW++;
      });
      r.boundary_closed=true; r.validation='valid';
      healedCount++;
    }
  });
  
  if(healedCount>0){
    setStatus(`Auto-Healed ${healedCount} issues (Added ${newW} bridge walls). Rebuilding...`, 'ok');
    validateModel(data);
    buildTopologyGraph(data);
    build3D(data);
  } else {
    setStatus('No healable issues found.', '');
  }
}

function buildTopologyGraph(d){
  if(!d)return;
  const graph={rooms:[], walls:[], openings:[]};
  let oCount=0;
  const walls=[...(d.outer_walls||[]), ...(d.inner_walls||[]), ...(d.closets||[])];
  walls.forEach(w=>{
    graph.walls.push({id:w.id, type:w.seg_type||'wall', len:w.length_px, children: (w.openings||[]).map(o=>o.type)});
    oCount+=(w.openings||[]).length;
  });
  (d.rooms||[]).forEach(r=>graph.rooms.push({id:r.id, type:r.room_type, area:r.area_px, valid:r.validation}));
  
  document.getElementById('topoStats').textContent=`Nodes: ${graph.rooms.length} Rooms, ${graph.walls.length} Walls, ${oCount} Openings.`;
  return graph;
}

// ═══════════════════════════════════════════════════════════════
// BUILD 3D SCENE
// ═══════════════════════════════════════════════════════════════
function build3D(d){
  if(grp)scene.remove(grp);while(interiorLightsGrp.children.length)interiorLightsGrp.remove(interiorLightsGrp.children[0]);clearMeasure();
  grp=new THREE.Group();
  const IW=d.image_width,IH=d.image_height,WLD=P.world;
  const px=x=>x*(WLD/IW)-WLD/2,pz=y=>y*(WLD/IH)-WLD/2;
  const wallH=gN('a-wh',2.8),doorH=gN('a-dh',2.1),doorW=gN('a-dw',.9),winSill=gN('a-ws',.9),winH=gN('a-wh2',1.2),stepH=gN('a-sr',.18);
  const wm=m=>V.wire?M.wire:m;
  function ac(m){if(clippingEnabled){m.clippingPlanes=clipPlanes;m.clipShadows=true}return m}
  function edge(g,m){m.add(new THREE.LineSegments(new THREE.EdgesGeometry(g),M.edge))}
  let wi=0;

  // P1/P2: Build openings from wall.openings[] instead of scanning doors/windows
  function getWallOpenings(seg, x1, z1, x2, z2) {
    const L=Math.hypot(x2-x1, z2-z1); if(L<.05) return [];
    const ops=[];
    // Read from wall's openings array (P1/P2 ownership model)
    if(seg.openings && seg.openings.length > 0){
      seg.openings.forEach(op=>{
        if(op.type==='door' && V.sD){
          const rW=Math.max(doorW*.75,Math.min(doorW*1.3,op.width_px*(WLD/IW)));
          ops.push({t:op.position_t, span:op.span, type:'door', obj:op.door_data||{}, wL:rW});
        }
        if(op.type==='window' && V.sW){
          const wL=Math.max(0.4, op.width_px*(WLD/IW));
          ops.push({t:op.position_t, span:op.span, type:'window', obj:op.window_data||{}, wL});
        }
      });
    }
    return ops.sort((a,b)=>a.t-b.t);
  }

  function wall(seg,mat,dt,type){
    if(userEdits.deletedIds.has(type+'_'+wi)){wi++;return}
    const x1=px(seg.x1),z1=pz(seg.y1),x2=px(seg.x2),z2=pz(seg.y2),dx=x2-x1,dz=z2-z1,L=Math.sqrt(dx*dx+dz*dz);
    if(L<.04){wi++;return}
    // P3: prefer original_thickness_px when available
    const thk_px = seg.original_thickness_px || seg.thickness_px || dt;
    const tk=Math.max(.08, thk_px*(WLD/IW)*P.thk);
    const ops=getWallOpenings(seg, x1, z1, x2, z2), a=-Math.atan2(dz,dx);
    let c=0;
    const addCh = (t1, t2, el, ht) => {
      const cL=(t2-t1)*L; if(cL<.02)return;
      let mMat = wm(mat).clone(); 
      if(userEdits.materials[type+'_'+wi]) { mMat.map = userEdits.materials[type+'_'+wi]; mMat.color.setHex(0xffffff); mMat.needsUpdate=true; }
      mMat.polygonOffset=true; mMat.polygonOffsetFactor=1; mMat.polygonOffsetUnits=1;
      const g=new THREE.BoxGeometry(cL, ht, tk), m=new THREE.Mesh(g, ac(mMat));
      m.position.set(x1+(t1+t2)/2*dx, el+ht/2, z1+(t1+t2)/2*dz); m.rotation.y=a;
      m.castShadow=m.receiveShadow=true; m.userData={type, index:wi, length:L.toFixed(2)}; edge(g,m); grp.add(m);
    };

    ops.forEach(op => {
      const hs = Math.max(c, op.t - op.span/2), he = Math.min(1, op.t + op.span/2);
      if(hs >= he) return;
      if(hs>c) addCh(c, hs, 0, wallH);
      if(op.type==='window'){ addCh(hs,he,0,winSill); addCh(hs,he,winSill+winH,wallH-(winSill+winH)); }
      else if(wallH>doorH) addCh(hs,he,doorH,wallH-doorH);
      c = Math.max(c, he);

      const mx=x1+op.t*dx, mz=z1+op.t*dz, cos=Math.cos(a), sin=Math.sin(a);
      if(op.type==='door'){
        const rW=op.wL, fT=tk*1.1;
        [[0,doorH,[rW+.14,.1,fT]],[-rW/2-.05,doorH/2,[.1,doorH,fT]],[rW/2+.05,doorH/2,[.1,doorH,fT]]].forEach(([fx,fy,ds])=>{
          const fm=new THREE.Mesh(new THREE.BoxGeometry(...ds),ac(M.dFrame.clone()));
          fm.position.set(mx+cos*fx,fy,mz-sin*fx); fm.rotation.y=a; fm.userData={type:'door frame'}; grp.add(fm);
        });
        const pan=new THREE.Mesh(new THREE.BoxGeometry(rW,doorH,tk/2),ac(M.dPanel.clone()));
        const pA = a-Math.PI/4;
        const hx = mx - (rW/2)*cos, hz = mz + (rW/2)*sin;
        pan.position.set(hx+(rW/2)*Math.cos(pA),doorH/2,hz-(rW/2)*Math.sin(pA)); pan.rotation.y=pA; pan.castShadow=true; pan.userData={type:'door'}; grp.add(pan);
        const kn=new THREE.Mesh(new THREE.SphereGeometry(.045,8,8),ac(M.fixChrome.clone()));
        kn.position.set(hx+(rW-0.1)*Math.cos(pA),doorH*.47,hz-(rW-0.1)*Math.sin(pA)); kn.userData={type:'handle'}; grp.add(kn);
      } else {
        const wL=op.wL, fT=.05;
        grp.add(mkM(new THREE.BoxGeometry(wL+.1,.06,tk*1.2),ac(M.lintel.clone()),mx,winSill,mz,0,a,0,{type:'sill'}));
        const glassMat = M.glass.clone(); glassMat.depthWrite = false;
        grp.add(mkM(new THREE.BoxGeometry(wL,winH,.02),ac(glassMat),mx,winSill+winH/2,mz,0,a,0,{type:'glass window'}));
        grp.add(mkM(new THREE.BoxGeometry(wL+.18,.14,tk*1.2),ac(M.lintel.clone()),mx,winSill+winH+.07,mz,0,a,0,{type:'lintel'}));
        [[-wL/2-fT/2,0,[fT,winH,tk*0.8]],[wL/2+fT/2,0,[fT,winH,tk*0.8]]].forEach(([lx,ly,ds])=>{
          const fm=new THREE.Mesh(new THREE.BoxGeometry(...ds),ac(M.wFrame.clone()));
          fm.position.set(mx+cos*lx,winSill+winH/2,mz-sin*lx); fm.rotation.y=a; fm.userData={type:'window frame'}; grp.add(fm);
        });
      }
    });

    if(1>c) addCh(c, 1, 0, wallH);
    wi++;
  }

  wi=0;if(V.sO)(d.outer_walls||[]).forEach(s=>wall(s,M.oWall,12,'outer'));
  wi=0;if(V.sI)(d.inner_walls||[]).forEach(s=>wall(s,M.iWall,8,'inner'));
  wi=0;if(V.sC)(d.closets||[]).forEach(s=>{
    if(userEdits.deletedIds.has('closet_'+wi)){wi++;return}
    const x1=px(s.x1),z1=pz(s.y1),x2=px(s.x2),z2=pz(s.y2),dx=x2-x1,dz=z2-z1,L=Math.sqrt(dx*dx+dz*dz);
    if(L<.04){wi++;return}
    const thk_px=s.original_thickness_px||s.thickness_px||6;
    const tk=Math.max(.06,thk_px*(WLD/IW)*P.thk),cH=wallH*.94;
    const mMat = wm(M.closet).clone(); mMat.polygonOffset=true; mMat.polygonOffsetFactor=1; mMat.polygonOffsetUnits=1;
    const g=new THREE.BoxGeometry(L,cH,tk);
    const m=new THREE.Mesh(g,ac(mMat));m.position.set((x1+x2)/2,cH/2,(z1+z2)/2);m.rotation.y=-Math.atan2(dz,dx);m.userData={type:'closet',index:wi};grp.add(m);wi++;
  });
  
  // Render floating windows/doors that have wallId=-1 (unassigned)
  if(V.sW)(d.windows||[]).filter(w=>w.wallId===-1||w.wallId===undefined).forEach(w=>{
    const x1=px(w.x1),z1=pz(w.y1),x2=px(w.x2),z2=pz(w.y2),a=-Math.atan2(z2-z1,x2-x1),mx=(x1+x2)/2,mz=(z1+z2)/2,wL=Math.hypot(x2-x1,z2-z1);
    grp.add(mkM(new THREE.BoxGeometry(wL,.06,.22),ac(M.lintel.clone()),mx,winSill,mz,0,a,0,{type:'sill'}));
    grp.add(mkM(new THREE.BoxGeometry(wL,winH,.05),ac(M.glass.clone()),mx,winSill+winH/2,mz,0,a,0,{type:'glass window'}));
  });
  if(V.sD)(d.doors||[]).filter(dr=>dr.wallId===-1||dr.wallId===undefined).forEach(dr=>{
    const mx=px(dr.cx),mz=pz(dr.cy),rW=dr.radius_px*(WLD/IW)*2;
    grp.add(mkM(new THREE.BoxGeometry(rW,doorH,.055),ac(M.dPanel.clone()),mx,doorH/2,mz,0,dr.arc_start||0,0,{type:'door'}));
  });
  // Stairs
  if(V.sS)(d.stairs||[]).forEach(st=>{
    const isH=st.orient==='h',sx1=px(st.x1),sz1=pz(st.y1),sx2=px(st.x2),sz2=pz(st.y2),sW=Math.abs(sx2-sx1),sD=Math.abs(sz2-sz1),steps=Math.max(3,st.steps||6);
    for(let i=0;i<steps;i++){const rise=stepH*(i+1),tread=isH?sD/steps:sW/steps,run=isH?sW:sD;
      const m=new THREE.Mesh(new THREE.BoxGeometry(isH?run:tread,rise,isH?tread:run),ac(M.stair.clone()));
      m.position.set(isH?sx1+sW/2:sx1+tread*i+tread/2,rise/2,isH?sz1+tread*i+tread/2:sz1+sD/2);m.castShadow=true;grp.add(m)}
  });
  // Floor
  if(V.sF){const fg=new THREE.PlaneGeometry(P.world+2,P.world+2),fl=new THREE.Mesh(fg,ac(M.floor.clone()));fl.rotation.x=-Math.PI/2;fl.receiveShadow=true;grp.add(fl)}
  // Room floors
  if(V.sRF&&d.rooms)d.rooms.forEach((r, idx)=>{
    if(!r.polygon||r.polygon.length<3)return;
    const sh=new THREE.Shape();sh.moveTo(px(r.polygon[0][0]),-pz(r.polygon[0][1]));
    for(let i=1;i<r.polygon.length;i++)sh.lineTo(px(r.polygon[i][0]),-pz(r.polygon[i][1]));
    sh.lineTo(px(r.polygon[0][0]),-pz(r.polygon[0][1]));
    const mt=new THREE.MeshStandardMaterial({color:new THREE.Color(r.color||'#607080'),transparent:true,opacity:.15,roughness:.9,side:THREE.DoubleSide,depthWrite:false});
    if(clippingEnabled){mt.clippingPlanes=clipPlanes}
    if(userEdits.materials['room_floor_'+idx]) { mt.map = userEdits.materials['room_floor_'+idx]; mt.color.setHex(0xffffff); mt.opacity=0.8; }
    const ms=new THREE.Mesh(new THREE.ShapeGeometry(sh),mt);ms.rotation.x=-Math.PI/2;ms.position.y=.01;ms.receiveShadow=true;
    ms.userData={type:'room_floor', index:idx, label:r.label||'Room', area:r.area_px?(r.area_px*(P.world/IW)*(P.world/IH)).toFixed(1):'?',rtype:r.room_type||'unknown'}; grp.add(ms);

    if(V.sRoof && r.boundary_closed) {
      const rmt=new THREE.MeshStandardMaterial({color:0xeeeeee,roughness:0.9,side:THREE.DoubleSide});
      if(clippingEnabled) rmt.clippingPlanes=clipPlanes;
      const rf=new THREE.Mesh(new THREE.ShapeGeometry(sh),rmt);rf.rotation.x=-Math.PI/2;rf.position.y=wallH;rf.castShadow=true;rf.receiveShadow=true;
      rf.userData={type:'roof'}; grp.add(rf);
    }
  });
  // Room labels
  if(V.sR&&d.rooms)d.rooms.forEach(r=>{
    const c=document.createElement('canvas');c.width=320;c.height=80;const ctx=c.getContext('2d');
    ctx.font='bold 20px Inter,sans-serif';ctx.fillStyle=r.color||'#b4bfe6';ctx.globalAlpha=.85;ctx.textAlign='center';ctx.fillText(r.label||'Room',160,28);
    ctx.font='13px JetBrains Mono,monospace';ctx.globalAlpha=.55;const a2=r.area_px?(r.area_px*(P.world/IW)*(P.world/IH)).toFixed(1):'?';
    ctx.fillText(`${r.room_type||''} · ${a2} m²`,160,50);
    const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),transparent:true,opacity:.8}));
    sp.position.set(px(r.cx),.08,pz(r.cy));sp.scale.set(4,.95,1);grp.add(sp);
  });
  // Fixtures
  if(V.sFX&&d.fixtures)d.fixtures.forEach(f=>{
    const fcx=px(f.cx),fcz=pz(f.cy);
    if(f.type==='toilet'){
      grp.add(mkM(new THREE.CylinderGeometry(.22,.18,.3,16),M.fixture.clone(),fcx,.15,fcz,0,0,0,{type:'fixture'}));
      grp.add(mkM(new THREE.BoxGeometry(.38,.35,.18),M.fixture.clone(),fcx,.25,fcz-.22,0,0,0,{type:'fixture'}));
      grp.add(mkM(new THREE.TorusGeometry(.19,.025,8,16),M.fixChrome.clone(),fcx,.31,fcz,Math.PI/2,0,0,{type:'chrome'}));
    }else if(f.type==='sink'){
      grp.add(mkM(new THREE.CylinderGeometry(.16,.12,.12,12),M.fixture.clone(),fcx,.82,fcz,0,0,0,{type:'fixture'}));
      grp.add(mkM(new THREE.BoxGeometry(.45,.04,.35),M.fixture.clone(),fcx,.88,fcz,0,0,0,{type:'fixture'}));
      grp.add(mkM(new THREE.CylinderGeometry(.015,.015,.15,6),M.fixChrome.clone(),fcx,.95,fcz-.12,0,0,0,{type:'chrome'}));
    }else if(f.type==='bathtub'){
      const bw=(f.width||60)*(P.world/IW),bh=(f.height||30)*(P.world/IH);
      grp.add(mkM(new THREE.BoxGeometry(Math.max(bw,.8),.45,Math.max(bh,.4)),M.fixture.clone(),fcx,.225,fcz,0,0,0,{type:'fixture'}));
      grp.add(mkM(new THREE.BoxGeometry(Math.max(bw-.1,.6),.1,Math.max(bh-.1,.25)),M.fixWater.clone(),fcx,.38,fcz,0,0,0,{type:'water'}));
    }
  });
  // Furniture (Design Elements)
  if(V.sFX&&d.furniture)d.furniture.forEach((f, i)=>{
    const fcx=px(f.cx),fcz=pz(f.cy);
    const scl = f.scale || 1.0;
    const fw=Math.max(.4, f.width*(WLD/IW))*scl, fh=Math.max(.4, f.height*(WLD/IH))*scl;
    const a = -f.angle * Math.PI / 180;
    
    if(f.type === 'bed') {
      const bh = 0.4;
      grp.add(mkM(new THREE.BoxGeometry(fw, bh, fh), ac(M.dPanel.clone()), fcx, bh/2, fcz, 0, a, 0, {type:'bed frame', index:i}));
      grp.add(mkM(new THREE.BoxGeometry(fw*0.8, bh+0.1, fh*0.9), ac(new THREE.MeshStandardMaterial({color: 0xffffff, roughness:0.9})), fcx, bh/2, fcz, 0, a, 0,{type:'bed linen'}));
    } else if (f.type === 'sofa') {
      const sh = 0.4;
      let mat = ac(new THREE.MeshStandardMaterial({color: 0x607588}));
      if(userEdits.materials['sofa_'+i]) { mat.map = userEdits.materials['sofa_'+i]; mat.color.setHex(0xffffff); mat.needsUpdate=true; }
      const b2 = new THREE.Mesh(new THREE.BoxGeometry(fw, sh, fh), mat);
      b2.position.set(fcx, sh/2, fcz); b2.rotation.y = a; b2.userData={type:'sofa', index:i}; grp.add(b2);
    } else if (f.type === 'table') {
      grp.add(mkM(new THREE.BoxGeometry(fw, 0.05, fh), ac(M.closet.clone()), fcx, 0.8, fcz, 0, a, 0, {type:'table', index:i}));
      grp.add(mkM(new THREE.CylinderGeometry(Math.min(fw,fh)*0.1, Math.min(fw,fh)*0.1, 0.8, 8), ac(M.dFrame.clone()), fcx, 0.4, fcz,0,0,0,{type:'table base'}));
    } else if (f.type === 'rug') {
      grp.add(mkM(new THREE.BoxGeometry(fw, 0.02, fh), ac(new THREE.MeshStandardMaterial({color: 0xa87060, roughness:1.0})), fcx, 0.01, fcz, 0, a, 0, {type:'rug', index:i}));
    }
  });
  // Interior lights
  if(V.iLights&&d.rooms){
    while(interiorLightsGrp.children.length)interiorLightsGrp.remove(interiorLightsGrp.children[0]);
    d.rooms.forEach(r=>{const l=new THREE.PointLight(0xfff0d0,.6,12);l.position.set(px(r.cx),wallH*.85,pz(r.cy));interiorLightsGrp.add(l);
    const lm=mkM(new THREE.SphereGeometry(.06,8,8),new THREE.MeshBasicMaterial({color:0xfff0d0}),l.position.x,l.position.y,l.position.z);interiorLightsGrp.add(lm)});
  }
  // User-added walls
  userEdits.addedWalls.forEach(aw=>{const g=new THREE.BoxGeometry(aw.len,wallH,aw.tk),m=new THREE.Mesh(g,ac(M.iWall.clone()));m.position.set(aw.mx,wallH/2,aw.mz);m.rotation.y=aw.angle;m.castShadow=m.receiveShadow=true;m.userData={type:'added',index:aw.id};edge(g,m);grp.add(m)});

  scene.add(grp);data=d;
  const s=d.summary||{};document.getElementById('vinfo').textContent=`o:${s.outer_walls||0} i:${s.inner_walls||0} c:${s.closets||0} w:${s.windows||0} d:${s.doors||0} s:${s.stairs||0} r:${s.rooms||0} f:${s.fixtures||0} fn:${d.furniture?d.furniture.length:0}`;
  updateMinimap();
}

// ═══════════════════════════════════════════════════════════════
