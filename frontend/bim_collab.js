// ==========================================
// IFC (BIM) SERIALIZER Phase 2
// ==========================================
function strip(num) { return (num * P.world / IW).toFixed(3); }

window.exportIFC = function() {
  if (!data) return alert("Run detection first!");
  
  let ifcStr = `ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\nFILE_NAME('floorplan.ifc','${new Date().toISOString()}',('Architect'),('Floor Plan AI'),'preprocessor','Floor Plan 3D Export','');\nFILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n#1= IFCPROJECT('1234567890',#2,'Project',$,$,$,$,$,#3);\n#2= IFCOWNERHISTORY(#4,#5,$,.ADDED.,$,$,$,1234567890);\n#3= IFCUNITASSIGNMENT((#6,#7));\n#6= IFCSIUNIT(*,.LENGTHUNIT.,$,.METER.);\n#7= IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.);\n`;

  let idx = 10;
  // Combine all walls
  const walls = [...(data.outer_walls||[]), ...(data.inner_walls||[]), ...(userEdits.addedWalls||[])].filter(w=>!userEdits.deletedIds.has(w.id));
  
  walls.forEach(w => {
    let x1 = strip(w.x1 || w.mx), y1 = strip(w.y1 || w.mz), x2 = strip(w.x2 || w.mx), y2 = strip(w.y2 || w.mz);
    let tk = strip(w.thickness_px || 10) * P.thk;
    let dist = Math.hypot(w.x2-w.x1, w.y2-w.y1);
    // Basic representation block (Dummy for geometry parsing in Revit)
    ifcStr += `#${idx}= IFCWALLSTANDARDCASE('${Math.random().toString(36).substr(2,9)}',#2,'Basic Wall',$,'Structural',#${idx+1},#${idx+2},'');\n`;
    idx += 5;
  });

  ifcStr += `ENDSEC;\nEND-ISO-10303-21;`;

  const blob = new Blob([ifcStr], {type:'application/x-step'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `model_export.ifc`;
  a.click();
}

// ==========================================
// REAL-TIME COLLABORATION (WebRTC via PeerJS)
// ==========================================
let p2p = null;
let conn = null;

window.initCollab = function() {
  const btn = document.getElementById('collabBtn');
  
  if (p2p) {
     prompt("You are sharing your session! Send this ID to a teammate:", p2p.id);
     return;
  }
  
  const joinId = prompt("Enter a Teammate's Session ID to join their room, or leave blank to HOST a new session.");
  
  btn.innerText = "⏳ Connecting...";
  p2p = new Peer();
  
  p2p.on('open', (id) => {
    if (joinId && joinId.trim() !== "") {
      conn = p2p.connect(joinId);
      setupConn();
    } else {
      btn.innerText = "📡 Host Active";
      alert("You are Hosting! Your Session ID is:\\n\\n" + id + "\\n\\nGive this to a teammate so they can join.");
    }
  });
  
  p2p.on('connection', (c) => {
    conn = c;
    setupConn();
    btn.innerText = "✅ Connected (Host)";
  });
}

function setupConn() {
  document.getElementById('collabBtn').innerText = "✅ Connected (Peer)";
  
  conn.on('open', () => {
    // Sync existing data on join
    if (data) conn.send({type: 'SYNC_STATE', added: userEdits.addedWalls});
  });
  
  conn.on('data', (payload) => {
    if(payload.type === 'SYNC_STATE') {
       if(payload.added) {
          payload.added.forEach(w => userEdits.addedWalls.push(w));
          rebuild();
       }
    }
    if (payload.type === 'COLOR') {
       if(!grp) return;
       grp.children.forEach(c => {
          if(c.userData.type === payload.mType && c.userData.index === payload.index && c.material && c.material.color) {
             c.material.color.set(payload.color);
             c.material.needsUpdate = true;
          }
       });
    }
  });
}

// Hook into UI color changes
setTimeout(() => {
    const oldChangeObjColor = window.changeObjColor;
    window.changeObjColor = function(hex) {
        if(oldChangeObjColor) oldChangeObjColor(hex);
        if(conn && selectedObject && selectedObject.userData) {
            conn.send({type: 'COLOR', mType: selectedObject.userData.type, index: selectedObject.userData.index, color: hex});
        }
    }
}, 500);
