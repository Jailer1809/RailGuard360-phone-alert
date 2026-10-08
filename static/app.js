import { FallPushAnalyzer } from "./detector.js";
import { PoseLandmarker, FilesetResolver, DrawingUtils } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs";

const $ = id => document.getElementById(id);
const hav=(a,b,c,d)=>{const R=6371,r=x=>x*Math.PI/180,p=r(c-a),l=r(d-b),k=Math.sin(p/2)**2+Math.cos(r(a))*Math.cos(r(c))*Math.sin(l/2)**2;return 2*R*Math.asin(Math.sqrt(k));};
let CFG={speed_threshold_kmph:20,time_scale:30,cruise_speed_kmph:60,cooldown_seconds:10};
let ACTIVE_TRAIN=null, ROUTE_STOPS=[], trainSearchResults=[];

class Train {
  constructor() {
    this.stations = [];
    this.cum = [];
    this.startDistance = 0;
    this.total = 0;
    this.pos = 0;
    this.speed = 0;
    this.maxSpeed = 160;
    this.target = 0; // Starts at 0, only moves when started by user
    this.isStarted = false;
    this.emergency = false;
    this.stopped = false;
    this.currentStationIndex = 0;
    this.dwellTimer = 0; // In seconds
    this.stationDwellTime = 5; // Stop for 5 seconds at each station
    this.stationStatusText = "Depot (Ready to Start)";
    this.lastPassedStationIndex = 0;
  }

  configure(stops) {
    if (!Array.isArray(stops) || stops.length < 2) throw new Error("Selected train route has fewer than two mapped stops.");
    const values = stops.map(stop => Number(stop.distance_km));
    const useScheduleDistances = values.every(Number.isFinite) && values.every((value, i) => i === 0 || value >= values[i - 1]) && values.at(-1) > values[0];
    this.stations = stops;
    this.startDistance = useScheduleDistances ? values[0] : 0;
    if (useScheduleDistances) {
      this.cum = values.map(value => value - values[0]);
    } else {
      this.cum = [0];
      for (let i = 1; i < stops.length; i++) {
        this.cum.push(this.cum[i - 1] + hav(stops[i - 1].lat, stops[i - 1].lon, stops[i].lat, stops[i].lon));
      }
    }
    this.total = this.cum.at(-1);
    this.pos = 0;
    this.speed = 0;
    this.target = 0;
    this.isStarted = false;
    this.emergency = false;
    this.stopped = false;
    this.currentStationIndex = 0;
    this.dwellTimer = 0;
    this.stationStatusText = "Depot (Ready to Start)";
  }

  start() {
    this.isStarted = true;
    this.emergency = false;
    this.stopped = false;
    this.target = this.maxSpeed;
    this.stationStatusText = "En route";
  }

  pause() {
    this.isStarted = false;
    this.target = 0;
    this.stationStatusText = "Paused by user";
  }

  update(dt) {
    if (this.emergency) {
      const emergencyDecelRate = 8.5; // Controlled gradual deceleration upon fall/push
      this.speed = Math.max(0, this.speed - emergencyDecelRate * dt);
      if (this.speed === 0 && !this.stopped) {
        this.stopped = true;
        this.stationStatusText = "HALTED (FALL/PUSH DETECTED)";
        return "STOPPED";
      }
      this.stationStatusText = `Braking smoothly (${this.speed.toFixed(0)} km/h)...`;
      this.pos += (this.speed * dt * CFG.time_scale) / 3600;
      return null;
    }

    if (this.stations.length < 2) return null;

    if (this.dwellTimer > 0) {
      this.dwellTimer -= dt;
      this.speed = Math.max(0, this.speed - 25 * dt);
      const stnName = this.stations[this.currentStationIndex].name;
      this.stationStatusText = `Stopped at ${stnName} (${Math.ceil(this.dwellTimer)}s left)`;
      if (this.dwellTimer <= 0) {
        this.dwellTimer = 0;
        if (this.isStarted) {
          this.target = this.maxSpeed;
          this.stationStatusText = `Departing ${stnName}`;
        }
      }
      return null;
    }

    if (!this.isStarted) {
      this.target = 0;
    }

    const accelRate = 4.5;
    const decelRate = 8.0;
    if (this.speed < this.target) {
      this.speed = Math.min(this.target, this.speed + accelRate * dt);
    } else if (this.speed > this.target) {
      this.speed = Math.max(this.target, this.speed - decelRate * dt);
    }

    const prevPos = this.pos;
    this.pos += (this.speed * dt * CFG.time_scale) / 3600;

    for (let i = 1; i < this.stations.length; i++) {
      const stnDist = this.cum[i];
      if (prevPos < stnDist && this.pos >= stnDist) {
        this.pos = stnDist;
        this.currentStationIndex = i;
        this.dwellTimer = this.stationDwellTime;
        this.target = 0;
        const stnName = this.stations[i].name;
        log(`Train arrived and stopped at ${stnName} for ${this.stationDwellTime}s`, "o");
        break;
      }
    }

    if (this.pos >= this.total) {
      this.pos = 0;
      this.lastPassedStationIndex = 0;
      this.currentStationIndex = 0;
    }

    return null;
  }

  loc() {
    if (this.stations.length < 2) return null;
    const d = this.pos;
    for (let i = 0; i < this.stations.length - 1; i++) {
      if (d <= this.cum[i+1]) {
        const f = (d - this.cum[i]) / (this.cum[i+1] - this.cum[i]);
        const a = this.stations[i], b = this.stations[i+1];
        return {
          lat: a.lat + (b.lat - a.lat) * f,
          lon: a.lon + (b.lon - a.lon) * f,
          km: d + this.startDistance,
          segment: `${a.name} -> ${b.name}`
        };
      }
    }
    const s = this.stations.at(-1);
    return { lat: s.lat, lon: s.lon, km: d + this.startDistance, segment: s.name };
  }

  nearest(l) {
    if (!this.stations.length) return [];
    const out = this.stations.map((station, i) => ({
      tag: this.cum[i] <= this.pos ? "behind" : "ahead",
      name: station.name,
      dist_km: Math.abs(this.cum[i] - this.pos)
    }));
    return out.sort((x, y) => x.dist_km - y.dist_km);
  }

  brake() {
    this.emergency = true;
    this.target = 0;
    this.stationStatusText = "Emergency Brake Active";
  }

  release() {
    this.emergency = false;
    this.stopped = false;
    this.dwellTimer = 0;
    if (this.isStarted) {
      this.target = this.maxSpeed;
      this.stationStatusText = "En route";
    } else {
      this.target = 0;
      this.stationStatusText = "Ready to Start";
    }
  }
}
const train=new Train();let detectors=[],pose,lastEvent=null,running=false,cameraStream=null;
let phoneLocation=null,phoneSpeed=null,gpsWatchId=null;
let mapView=null,routeLine=null,trainMarker=null,phoneMarker=null,alertMarker=null;
let stationMarkers=[];

function log(msg,cls=""){const d=document.createElement("div");d.className=cls;d.textContent=new Date().toLocaleTimeString()+"  "+msg;$("log").prepend(d);}
function banner(msg,color){const b=$("banner");b.textContent=msg;b.style.background=color;b.style.display="block";clearTimeout(banner.t);banner.t=setTimeout(()=>b.style.display="none",8000);}

async function sendAlert(event, speed, loc, stage) {
  try {
    const r = await fetch("api/alert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, speed, loc, stage, persons: event.persons || 1, train_number: ACTIVE_TRAIN?.number })
    });
    const j = await r.json();
    log(`${stage} alert request: ${j.message}`, j.ok ? "o" : "w");
    if (j.ok) {
      alertMarker = { lat: loc.lat, lon: loc.lon, label: `${stage}: ${event.type || "FALL/PUSH"} — ${ACTIVE_TRAIN?.number || ""} ${ACTIVE_TRAIN?.name || ""}` };
      drawMap();
    }
    
    // Trigger Real-time Popup Alert
    showRealtimeAlertModal(event, speed, loc, stage, j.results || []);
    
    // Browser Native Push Notification (if permitted)
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(`🚨 RAILGUARD 360: ${stage} - ${event.type || "FALL/PUSH"}`, {
        body: `Speed: ${speed.toFixed(0)} km/h; GPS ${loc.lat.toFixed(6)}, ${loc.lon.toFixed(6)}. ${j.message}`,
        icon: "/railguard-icon.svg"
      });
    }
  } catch (e) {
    log("Could not reach server /api/alert - " + e, "e");
  }
}

function showRealtimeAlertModal(event, speed, loc, stage, results) {
  const modal = $("phoneModal");
  const container = $("modalAlertCards");
  if (!modal || !container) return;

  container.innerHTML = "";
  
  if (results && results.length > 0) {
    results.forEach(([role, to, status, body]) => {
      const card = document.createElement("div");
      card.style.background = "#101a24";
      card.style.border = "1px solid #3aa0ff";
      card.style.borderRadius = "8px";
      card.style.padding = "10px";
      card.style.fontSize = "12px";

      const isRealPhone = to && !to.includes("X");
      const smsLink = isRealPhone ? `sms:${to}?body=${encodeURIComponent(body)}` : "#";

      card.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <b style="color:#3aa0ff;text-transform:uppercase;">📞 ${role} (${to || "Not Configured"})</b>
          <span style="background:${status === 'SENT' ? '#2ecc71' : '#f39c12'};color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;">${status}</span>
        </div>
        <div style="color:#e8eef4;margin-bottom:8px;line-height:1.4;word-break:break-word;">${body}</div>
        ${isRealPhone ? `<a href="${smsLink}" target="_blank" style="display:inline-block;background:#3aa0ff;color:#fff;text-decoration:none;padding:4px 8px;border-radius:4px;font-weight:bold;font-size:11px;">📲 Open on Phone SMS</a>` : `<small style="color:var(--mut)">(Placeholder number)</small>`}
      `;
      container.appendChild(card);
    });
  } else {
    container.innerHTML = `<div style="padding:10px;background:#101a24;border-radius:8px;font-size:13px;color:#f39c12;">${stage}: Fall/Push detected @ ${speed.toFixed(0)} km/h. Coordinates: ${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}.</div>`;
  }

  modal.style.display = "flex";
}
function fire(event){
  const phoneMode=$("modeSelect").value==="phone";
  const spd=phoneMode?phoneSpeed:train.speed;
  const loc=phoneMode?phoneLocation:train.loc();
  if(!phoneMode&&!loc){const m="Select a timetable train with mapped stops before testing demo alerts.";
    log(m,"w");banner(m,"#b9770e");return;}
  if(!loc){const m="Incident detected, but phone GPS has no location fix. Start GPS; no alert sent.";
    log(m,"w");banner(m,"#b9770e");return;}
  if(spd===null||!Number.isFinite(spd)){const m="Incident detected, but phone GPS speed is unavailable. No alert sent.";
    log(m,"w");banner(m,"#b9770e");return;}
  if(spd<=CFG.speed_threshold_kmph){const m=`${event.type} detected but speed ${spd.toFixed(0)} <= ${CFG.speed_threshold_kmph} km/h -> NO ALERT`;
    log(m,"w");banner(m,"#b9770e");return;}
  if(!phoneMode){train.brake();lastEvent=event;}
  const persons=event.persons||1;
  const m=phoneMode
    ?`${event.type} (${persons} detected) @ ${spd.toFixed(0)} km/h - sending alert at ${loc.lat.toFixed(6)}, ${loc.lon.toFixed(6)}`
    :`${event.type} @ ${spd.toFixed(0)} km/h - alert requested, demo train braking`;
  log(m,"e");banner(m,"#c0392b");
  sendAlert(event,spd,loc,"ALERT");
}

function startPhoneGps(){
  if(!navigator.geolocation){log("This browser does not support phone GPS.","e");return;}
  if(gpsWatchId!==null){navigator.geolocation.clearWatch(gpsWatchId);gpsWatchId=null;
    phoneLocation=null;phoneSpeed=null;$("bGps").textContent="Start phone GPS";
    $("stnStatus").textContent="GPS stopped";$("gps").textContent="Waiting for GPS";
    return;}
  $("bGps").textContent="Stop phone GPS";$("stnStatus").textContent="Waiting for GPS fix...";
  gpsWatchId=navigator.geolocation.watchPosition(position=>{
    const c=position.coords;
    phoneLocation={lat:c.latitude,lon:c.longitude,accuracy:c.accuracy};
    phoneSpeed=Number.isFinite(c.speed)&&c.speed>=0?c.speed*3.6:null;
    $("gps").textContent=`${c.latitude.toFixed(6)}, ${c.longitude.toFixed(6)} (±${Math.round(c.accuracy)} m)`;
    $("stnStatus").textContent=phoneSpeed===null?"GPS speed unavailable":"GPS fix updated";
  },error=>{
    const messages={1:"Location permission denied",2:"Phone GPS location unavailable",3:"Phone GPS request timed out"};
    $("stnStatus").textContent=messages[error.code]||"GPS error";
    log(`${$("stnStatus").textContent}: ${error.message}`,"e");
    if(error.code===1&&gpsWatchId!==null){navigator.geolocation.clearWatch(gpsWatchId);gpsWatchId=null;
      $("bGps").textContent="Start phone GPS";}
  },{enableHighAccuracy:true,maximumAge:0,timeout:15000});
}

function updateModeControls(){
  const phoneMode=$("modeSelect").value==="phone";
  $("bStartTrain").hidden=phoneMode;
  $("bUp").disabled=phoneMode||ROUTE_STOPS.length<2;$("bDn").disabled=phoneMode||ROUTE_STOPS.length<2;
  $("bRel").disabled=phoneMode||ROUTE_STOPS.length<2;$("bStartTrain").disabled=ROUTE_STOPS.length<2;
  $("mapTitle").textContent=ACTIVE_TRAIN?`${ACTIVE_TRAIN.number} · ${ACTIVE_TRAIN.name}`:"Train route map";
  $("mapNote").textContent=phoneMode
    ?"Blue marker is this phone's GPS, not live train GPS. Yellow line uses supplied 2015 timetable stops; it is an approximate corridor, not exact track geometry."
    :"Green marker is the simulated train position. Yellow line uses supplied 2015 timetable stops; it is an approximate corridor, not exact track geometry.";
  $("speedLabel").textContent=phoneMode?"Phone GPS speed km/h":"Simulated train speed km/h";
  $("modeHelp").innerHTML=phoneMode
    ?`Live phone mode uses this phone's GPS coordinates and reported GPS speed. Start GPS and camera, and keep the camera aimed at the area to monitor. Alerts require GPS speed above <b id="lim">${CFG.speed_threshold_kmph}</b> km/h. The app cannot stop a train.`
    :`Demo mode follows scheduled stops and route distances from the timetable. Map position is simulated between mapped stations, not live train GPS. Alerts activate above <b id="lim">${CFG.speed_threshold_kmph}</b> km/h.`;
}

async function searchTrains(query){
  const response=await fetch(`/api/trains?q=${encodeURIComponent(query)}`);
  const data=await response.json();
  if(!response.ok)throw new Error(data.message||"Train search failed");
  trainSearchResults=data.trains;
  $("trainOptions").replaceChildren(...trainSearchResults.map(item=>{
    const option=document.createElement("option");
    option.value=`${item.number} | ${item.name}`;
    option.label=`${item.source} to ${item.destination}`;
    return option;
  }));
}

async function loadTrainRoute(number){
  $("routeStatus").textContent=`Loading train ${number} route and map locations…`;
  try{
    const response=await fetch(`/api/trains/${encodeURIComponent(number)}/route`);
    const data=await response.json();
    if(!response.ok)throw new Error(data.message||"Train route could not be loaded");
    ACTIVE_TRAIN=data.train;
    ROUTE_STOPS=data.stops;
    train.configure(ROUTE_STOPS);
    train.maxSpeed=CFG.cruise_speed_kmph||160;
    if(alertMarker?.layer)alertMarker.layer.remove();
    alertMarker=null;
    $("trainSearch").value=`${ACTIVE_TRAIN.number} | ${ACTIVE_TRAIN.name}`;
    $("routeStatus").textContent=`${ACTIVE_TRAIN.source} → ${ACTIVE_TRAIN.destination} · ${ROUTE_STOPS.length} mapped stops`;
    $("mapTitle").textContent=`${ACTIVE_TRAIN.number} · ${ACTIVE_TRAIN.name}`;
    configureMapRoute();
    updateModeControls();
    drawMap();
    log(`Loaded timetable route for ${ACTIVE_TRAIN.number} ${ACTIVE_TRAIN.name}`,"o");
  }catch(error){
    $("routeStatus").textContent=error.message;
    log(`Train route error: ${error.message}`,"e");
  }
}

function setupTrainPicker(){
  const picker=$("trainSearch");
  let searchTimer;
  picker.addEventListener("input",()=>{
    clearTimeout(searchTimer);
    const query=picker.value.trim();
    if(!query)return;
    searchTimer=setTimeout(()=>searchTrains(query).catch(error=>{
      $("routeStatus").textContent=error.message;
    }),250);
  });
  picker.addEventListener("change",()=>{
    const number=picker.value.trim().split("|",1)[0].trim();
    if(/^\d{1,6}$/.test(number)&&number!==ACTIVE_TRAIN?.number)loadTrainRoute(number);
  });
  picker.addEventListener("focus",()=>searchTrains("").catch(error=>{
    $("routeStatus").textContent=error.message;
  }));
}

// ---- map ----
function initMap(){
  if(!window.L){$("routeStatus").textContent="Map library unavailable; check internet connection.";return;}
  mapView=L.map("map").setView([11.7,78.5],7);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{
    maxZoom:19,
    attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(mapView);
}

function configureMapRoute(fit=true){
  if(!mapView||ROUTE_STOPS.length<2)return;
  if(routeLine)routeLine.remove();
  stationMarkers.forEach(marker=>marker.remove());
  stationMarkers=[];
  routeLine=L.polyline(ROUTE_STOPS.map(stop=>[stop.lat,stop.lon]),{color:"#f2b84b",weight:5,opacity:.85}).addTo(mapView);
  ROUTE_STOPS.forEach(stop=>{
    const marker=L.circleMarker([stop.lat,stop.lon],{radius:4,color:"#d5e0e8",fillColor:"#273847",fillOpacity:1,weight:2}).addTo(mapView);
    marker.bindTooltip(`${stop.code} · ${stop.name}`);
    stationMarkers.push(marker);
  });
  if(fit)mapView.fitBounds(routeLine.getBounds(),{padding:[20,20]});
  $("mapNote").textContent="OpenStreetMap base map. Stops use the supplied 2015 timetable; connecting line is an approximate corridor, not exact rail-track geometry.";
}

function drawMap(){
  if(!mapView)return;
  const phoneMode=$("modeSelect").value==="phone";
  const loc=phoneMode?phoneLocation:train.loc();
  if(loc){
    if(phoneMode){
      if(trainMarker){trainMarker.remove();trainMarker=null;}
      if(!phoneMarker){
        phoneMarker=L.circleMarker([loc.lat,loc.lon],{radius:8,color:"#fff",weight:2,fillColor:"#3aa0ff",fillOpacity:1}).addTo(mapView);
        phoneMarker.bindTooltip("Phone GPS position — not train GPS");
      }else phoneMarker.setLatLng([loc.lat,loc.lon]);
    }else{
      if(phoneMarker){phoneMarker.remove();phoneMarker=null;}
      if(!trainMarker){
        trainMarker=L.circleMarker([loc.lat,loc.lon],{radius:9,color:"#fff",weight:2,fillColor:"#2ecc71",fillOpacity:1}).addTo(mapView);
        trainMarker.bindTooltip(`${ACTIVE_TRAIN?.number || "Train"} · ${ACTIVE_TRAIN?.name || ""} · simulated`);
      }else trainMarker.setLatLng([loc.lat,loc.lon]);
      trainMarker.setStyle({fillColor:train.emergency?"#e74c3c":"#2ecc71"});
    }
  }
  if(alertMarker){
    if(!alertMarker.layer){
      alertMarker.layer=L.circleMarker([alertMarker.lat,alertMarker.lon],{radius:10,color:"#fff",weight:2,fillColor:"#e74c3c",fillOpacity:1}).addTo(mapView);
      alertMarker.layer.bindTooltip(alertMarker.label);
    }else alertMarker.layer.setLatLng([alertMarker.lat,alertMarker.lon]);
  }
}

// ---- camera + pose ----
async function startCamera(requestedDeviceId = null) {
  $("bCam").disabled = true;
  $("bCam").textContent = "Loading model...";
  try {
    let videoConstraint = { width: { ideal: 640 }, height: { ideal: 480 } };
    if (requestedDeviceId) {
      videoConstraint.deviceId = { exact: requestedDeviceId };
    } else {
      videoConstraint.facingMode = { ideal: "environment" };
    }

    if (cameraStream) {
      cameraStream.getTracks().forEach(track => track.stop());
    }

    cameraStream = await navigator.mediaDevices.getUserMedia({ audio: false, video: videoConstraint });
    const v = $("v");
    v.srcObject = cameraStream;
    await v.play();

    if (!pose) {
      const vision = await FilesetResolver.forVisionTasks("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm");
      pose = await PoseLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
          delegate: "GPU"
        },
        runningMode: "VIDEO",
        numPoses: 4
      });
    }

    $("c").width = v.videoWidth;
    $("c").height = v.videoHeight;
    running = true;
    if ("Notification" in window && Notification.permission === "default") {
      await Notification.requestPermission();
    }
    $("bCam").textContent = "Camera running";
    await refreshCameraList();
    const currentTrackName = cameraStream.getVideoTracks()[0]?.label || "Camera";
    log(`Camera running: ${currentTrackName}`, "o");
    requestAnimationFrame(loop);
  } catch (e) {
    cameraStream?.getTracks().forEach(track => track.stop());
    cameraStream = null;
    running = false;
    $("v").srcObject = null;
    log("Camera/model error: " + e.message + " (camera needs HTTPS or localhost and permission)", "e");
    $("bCam").disabled = false;
    $("bCam").textContent = "Start camera";
  }
}

async function refreshCameraList() {
  const select = $("cameraSelect");
  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameras = devices.filter(d => d.kind === "videoinput");

  select.replaceChildren(...cameras.map((d, i) => {
    const option = document.createElement("option");
    option.value = d.deviceId;
    let label = d.label || `Camera ${i + 1}`;
    if (/integrated|built.?in|internal|facetime|hd user/i.test(label)) {
      label = `💻 Laptop Camera: ${label}`;
    } else if (/phone|iriun|droidcam|epoccam|back|rear|external/i.test(label)) {
      label = `📱 Phone/Ext Camera: ${label}`;
    } else {
      label = `📷 Camera: ${label}`;
    }
    option.textContent = label;
    return option;
  }));

  const activeId = cameraStream?.getVideoTracks()[0]?.getSettings().deviceId;
  if (activeId) select.value = activeId;
  select.hidden = false;
  select.onchange = () => switchCamera(select.value);
}

async function switchCamera(deviceId) {
  try {
    log("Switching camera feed...", "w");
    await startCamera(deviceId);
  } catch (e) {
    log("Could not switch camera: " + e.message, "e");
    await refreshCameraList();
  }
}
let prev=performance.now(),lastVideoT=-1,lastDetectT=-1;const t0=performance.now();
function loop(now){
  const dt=(now-prev)/1000;prev=now;
  const phoneMode=$("modeSelect").value==="phone";
  if(!phoneMode&&train.update(dt)==="STOPPED"&&lastEvent){const l=train.loc();log("Demo train halted at "+l.lat.toFixed(6)+","+l.lon.toFixed(6),"e");sendAlert(lastEvent,0,l,"HALTED");}
  const v=$("v"),c=$("c"),g=c.getContext("2d");g.clearRect(0,0,c.width,c.height);
  if(running&&v.currentTime!==lastVideoT){lastVideoT=v.currentTime;
    lastDetectT=Math.max(Math.round(now),lastDetectT+1);
    const res=pose.detectForVideo(v,lastDetectT);
    const frameEvents=[];
    (res.landmarks||[]).forEach((lm,index)=>{if(!detectors[index])detectors[index]=new FallPushAnalyzer({cooldown:CFG.cooldown_seconds});
      new DrawingUtils(g).drawLandmarks(lm,{radius:3,color:"#3aa0ff"});new DrawingUtils(g).drawConnectors(lm,PoseLandmarker.POSE_CONNECTIONS,{color:"#2ecc71",lineWidth:2});
      if([11,12,23,24].every(i=>(lm[i].visibility??1)>0.5)){const ar=v.videoWidth/v.videoHeight;
        const sh=[(lm[11].x+lm[12].x)/2*ar,(lm[11].y+lm[12].y)/2],hp=[(lm[23].x+lm[24].x)/2*ar,(lm[23].y+lm[24].y)/2];
        const detector=detectors[index],ev=detector.update((now-t0)/1000,sh,hp);$("tilt").textContent=detector.tilt.toFixed(0);if(ev)frameEvents.push(ev);}
    });
    if(frameEvents.length){const event=frameEvents.find(item=>item.type==="PUSH")||frameEvents[0];
      fire({...event,persons:frameEvents.length});}
    if(!res.landmarks?.length)$("tilt").textContent="-";}
  const l=phoneMode?phoneLocation:train.loc(),speed=phoneMode?phoneSpeed:train.speed;
  const armed=!!l&&speed!==null&&speed>CFG.speed_threshold_kmph;
  $("spd").textContent = speed===null||!Number.isFinite(speed)?"--":speed.toFixed(0);
  if(!phoneLocation&&phoneMode)$("gps").textContent="Waiting for GPS";
  if(!phoneMode)$("gps").textContent = l ? `${l.lat.toFixed(6)}, ${l.lon.toFixed(6)} (simulated)` : "Route not loaded";
  if (!phoneMode) $("stnStatus").textContent = train.stationStatusText;
  const a = $("armed");
  a.textContent = !l&&phoneMode?"GPS REQUIRED":speed===null&&phoneMode?"GPS SPEED UNAVAILABLE":!phoneMode&&train.emergency?"DEMO BRAKING":armed?"ARMED (>"+CFG.speed_threshold_kmph+" km/h)":"ALERTS OFF (<= "+CFG.speed_threshold_kmph+" km/h)";
  a.style.background = !l&&phoneMode||speed===null&&phoneMode?"#3a4856":!phoneMode&&train.emergency?"#e74c3c":armed?"#2ecc71":"#f39c12";
  drawMap();
  requestAnimationFrame(loop);
}

// ---- boot ----
(async()=>{
  initMap();
  setupTrainPicker();
  try{
    const j=await (await fetch("api/config")).json();
    CFG={...CFG,...j};
    $("lim").textContent=CFG.speed_threshold_kmph;
    $("nums").textContent=j.numbers.join("  |  ");
    $("sms").innerHTML=j.sms_provider?`<span class="o">SMS provider: ${j.sms_provider}</span>`:`<span class="w">No SMS provider set on server - alerts run in dry-run (see server log)</span>`;
    if(j.train){
      ACTIVE_TRAIN=j.train;
      $("trainSearch").value=`${j.train.number} | ${j.train.name}`;
      await loadTrainRoute(j.train.number);
    }
  }catch(e){$("nums").textContent="(server not reachable)";}
  train.maxSpeed = CFG.cruise_speed_kmph || 160;

  try {
    await refreshCameraList();
  } catch(e) {}

  $("bCam").onclick=()=>startCamera($("cameraSelect")?.value || null);
  $("bGps").onclick=startPhoneGps;
  $("modeSelect").onchange=updateModeControls;
  updateModeControls();
  
  const bStart = $("bStartTrain");
  if (bStart) {
    bStart.onclick = () => {
      if (!train.isStarted) {
        train.start();
        bStart.textContent = "Pause Train";
        bStart.style.background = "#f39c12";
        log(`Train ${ACTIVE_TRAIN?.number || ""} departure initiated -> accelerating gradually`, "o");
      } else {
        train.pause();
        bStart.textContent = "Start Train";
        bStart.style.background = "#2ecc71";
        log("Train stopped by operator", "w");
      }
    };
  }

  $("bUp").onclick=()=>{
    if (!train.emergency && train.isStarted) {
      train.target = Math.min(160, train.target + 10);
      log(`Target speed adjusted: ${train.target} km/h`, "o");
    }
  };
  $("bDn").onclick=()=>{
    if (!train.emergency && train.isStarted) {
      train.target = Math.max(0, train.target - 10);
      log(`Target speed adjusted: ${train.target} km/h`, "o");
    }
  };
  $("bFake").onclick=()=>fire({type:"PUSH / FALL",confidence:0.95});
  $("bRel").onclick=()=>{
    train.release();
    if (bStart) {
      bStart.textContent = train.isStarted ? "Pause Train" : "Start Train";
      bStart.style.background = train.isStarted ? "#f39c12" : "#2ecc71";
    }
    log("Train reset / released", "o");
  };
  // Real-time Phone Modal Dismiss Listeners
  const closeModal = () => { if ($("phoneModal")) $("phoneModal").style.display = "none"; };
  if ($("closeModal")) $("closeModal").onclick = closeModal;
  if ($("btnAcknowledge")) $("btnAcknowledge").onclick = closeModal;

  if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(e=>log("Could not register app service worker: "+e.message,"w"));
  requestAnimationFrame(loop);
})();
