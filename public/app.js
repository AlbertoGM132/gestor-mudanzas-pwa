// ═══════════════════════════════════════════════════════
//  MudanzaPro — Lógica principal
//  Firebase + Calendar + Jobs + Finanzas + Presupuestos
// ═══════════════════════════════════════════════════════

import { initializeApp }    from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import { getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged }
                            from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";
import { getFirestore, collection, addDoc, doc, setDoc, deleteDoc,
         query, where, onSnapshot, orderBy, serverTimestamp, getDoc }
                            from "https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js";
import { getStorage, ref as sRef, uploadBytesResumable, getDownloadURL, deleteObject }
                            from "https://www.gstatic.com/firebasejs/11.6.0/firebase-storage.js";
import { getMessaging, getToken, onMessage }
                            from "https://www.gstatic.com/firebasejs/11.6.0/firebase-messaging.js";

// ✏️ REEMPLAZA CON TU CONFIG
const firebaseConfig = {
  apiKey: "AIzaSyBW-DXKRKumti5YDyFCqOHgWHAKYK-6AtQ",
  authDomain: "smartsonubalogictis.firebaseapp.com",
  projectId: "smartsonubalogictis",
  storageBucket: "smartsonubalogictis.firebasestorage.app",
  messagingSenderId: "692783709731",
  appId: "1:692783709731:web:f2cb16afd96e45abed7b96",
  measurementId: "G-1L12MM9M7N"
};

const VAPID_KEY = "BKMbUxUubGqwf9FXT25Qk0GHcIuZEPss75x7-AlH1QPqXMnouPmEMolSu9FrZWConcj58WHIweTi99PaGEtzpP8";

// ── CATÁLOGOS ──
// Vehículos de alquiler por día. kind → tarifa en config/tarifas (rent_<kind>_<plan>)
const VEHICLE_TYPES = [
  {id:'crafter', label:'Furgoneta VW Crafter', kind:'furgoneta'},
  {id:'iveco',   label:'Camión Iveco Daily 20 m³', kind:'camion'},
];
const KM_PLANS = [200,400];
const MATERIALS = ["Cajas pequeñas","Cajas grandes","Papel burbuja","Papel de embalaje","Cinta adhesiva",
                   "Mantas de protección","Fajas de carga","Traspaleta","Escalera","Carretilla","Plástico film","Esquineros"];
// Material que se reutiliza: no cuenta como gasto en el cierre
const REUSABLE = ["Mantas de protección","Fajas de carga","Traspaleta","Escalera","Carretilla"];
const PARTNERS = ["Alberto","Cristian"];               // socios: cobran del margen, no por horas
const WORKERS  = ["Javi","Cheko","Miguel","Dani"];     // trabajadores habituales (€/h)
const SERVICES = ["Mudanza completa","Porte","Desmontaje y montaje","Embalaje","Vajilla / frágil","Otro"];
const ELEV_LABEL = v => v===true?'Sí':v===false?'No':'¿?';
// Embudo: los trabajos sin fecha son solicitudes; al ponerles fecha pasan a "programado"
const PIPELINE = [
  {id:'solicitud',     label:'Solicitudes',          short:'Solicitud',     icon:'📥', hint:'Recogiendo información'},
  {id:'presupuestado', label:'Presupuesto enviado',  short:'Presupuestado', icon:'📨', hint:'Esperando respuesta'},
  {id:'aceptado',      label:'Aceptados sin fecha',  short:'Aceptado',      icon:'🤝', hint:'Falta cerrar la fecha'},
];
const STAGE_LABEL={solicitud:'Solicitud',presupuestado:'Presupuestado',aceptado:'Aceptado',perdido:'Perdido',programado:'Programado',completado:'Completado'};
function jobStage(j){return j.status==='completado'?'completado':j.date?'programado':(j.stage||'solicitud')}
const PARKING=[['puerta','En la puerta'],['30','A menos de 30 m'],['100','De 30 a 100 m'],['mas','A más de 100 m']];
function accessLabel(a){
  if(!a)return'';
  const out=[];
  const pk=PARKING.find(x=>x[0]===a.parking);if(pk)out.push(`Camión: ${pk[1].toLowerCase()}`);
  if(a.steps!=null&&a.steps!=='')out.push(Number(a.steps)?`${a.steps} tramo${a.steps>1?'s':''} de escalera hasta el portal`:'sin escalones hasta el portal');
  if(a.smallElevator)out.push('ascensor pequeño');
  if(a.narrowStreet)out.push('calle estrecha');
  if(a.permit)out.push('necesita permiso de carga');
  return out.join(' · ');
}
function daysAgo(ts){if(!ts)return null;const d=new Date(ts.seconds?ts.seconds*1000:ts);return Math.floor((Date.now()-d)/86400000)}
// En los trabajos antiguos (sin campo "days") el ascensor venía desmarcado por defecto: no se sabe
const elev = (job,key) => (job.days===undefined&&job[key]===false)?null:(job[key]??null);
const MONTHS_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
const DAYS_ES   = ["Dom","Lun","Mar","Mié","Jue","Vie","Sáb"];

const fireApp  = initializeApp(firebaseConfig);
const auth     = getAuth(fireApp);
const db       = getFirestore(fireApp);
const storage  = getStorage(fireApp);
let messaging  = null;
try { messaging = getMessaging(fireApp); } catch(e) {}

// ── HELPERS ──
const $ = id => document.getElementById(id);
const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const fmt = n => Number(n||0).toFixed(2);
let toastT;
function toast(msg,type=''){clearTimeout(toastT);const t=$('toast');t.textContent=msg;t.className='show '+type;toastT=setTimeout(()=>t.className='',3200)}
function statusColor(s){return s==='completado'?'#22c55e':s==='en_curso'?'#f59e0b':'#6366f1'}
function statusLabel(s){return s==='completado'?'Completado':s==='en_curso'?'En curso':'Pendiente'}
function pad(n){return String(n).padStart(2,'0')}
function dateKey(d){return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`}
function todayStr(){return dateKey(new Date())}
function addDays(ds,n){const[y,m,d]=ds.split('-').map(Number);return dateKey(new Date(y,m-1,d+n))}
function jobDays(job){return Math.min(31,Math.max(1,parseInt(job.days)||1))}
function fmtDateEs(ds){if(!ds)return'—';const[y,m,d]=ds.split('-').map(Number);const dt=new Date(y,m-1,d);return `${DAYS_ES[dt.getDay()]} ${d} ${MONTHS_ES[m-1].slice(0,3).toLowerCase()}`}
// Personal: lista de nombres; los trabajos antiguos solo tienen "team" ("Equipo C (3 personas)")
function jobCrew(job){return Array.isArray(job.crew)?job.crew:[]}
function crewLabel(job){const c=jobCrew(job);return c.length?c.join(', '):(job.team||'')}
// Vehículos: lista [{type,plan}]; los antiguos solo tienen "vehicle" (texto)
function jobVehicles(job){return Array.isArray(job.vehicles)?job.vehicles:[]}
function vehicleLabel(v){const t=VEHICLE_TYPES.find(x=>x.id===v.type);return `${t?t.label:v.type} · ${v.plan} km/día`}
function vehiclesLabel(job){const v=jobVehicles(job);return v.length?v.map(vehicleLabel).join(' + '):(job.vehicle||'')}
// Teléfono español → formato internacional para WhatsApp
function waPhone(p){let d=String(p||'').replace(/\D/g,'');if(d.startsWith('00'))d=d.slice(2);if(d.length===9)d='34'+d;return d.length>=11?d:''}
function waLink(phone,text){const n=waPhone(phone);return n?`https://wa.me/${n}?text=${encodeURIComponent(text)}`:''}

// ── AUTH ──
$('btn-login').addEventListener('click',async()=>{
  $('auth-err').textContent='';
  $('btn-login').innerHTML='<span class="spin"></span>';
  try{await signInWithEmailAndPassword(auth,$('inp-email').value.trim(),$('inp-pass').value)}
  catch(e){
    const m={'auth/invalid-email':'Correo no válido.','auth/user-not-found':'Usuario no encontrado.',
      'auth/wrong-password':'Contraseña incorrecta.','auth/invalid-credential':'Credenciales inválidas.',
      'auth/too-many-requests':'Demasiados intentos.'};
    $('auth-err').textContent=m[e.code]||'Error: '+e.code;
    $('btn-login').textContent='Entrar';
  }
});
$('btn-logout').addEventListener('click',()=>signOut(auth));

let jobsUnsub, finUnsub;
onAuthStateChanged(auth,user=>{
  if(user){
    $('auth-screen').style.display='none';
    $('app-screen').style.display='flex';
    $('user-label').textContent=user.email;
    $('btn-login').textContent='Entrar';
    boot();
  }else{
    $('auth-screen').style.display='flex';
    $('app-screen').style.display='none';
    if(jobsUnsub)jobsUnsub();
    if(finUnsub)finUnsub();
    if(presUnsub)presUnsub();
    if(pipeUnsub)pipeUnsub();
  }
});

// ── STATE ──
let calYear,calMonth,selDate,jobsCache={};
let curView='cal',curJob=null,isEditing=false,activeTab='info',formState={},formPhotos=[];
// Valores por defecto (oct. 2026); se sobrescriben con config/tarifas
let tarifas={workerHour:10,partnerHour:22,businessPct:10,roundTo:5,extraKm:0.22,
  rent_furgoneta_200:73,rent_furgoneta_400:88,rent_camion_200:133,rent_camion_400:150,
  fuelPrice:2,consumo_crafter:10,consumo_iveco:14,   // €/L y L/100 km
  reviewUrl:'',quoteMsg:'',
  ...Object.fromEntries(MATERIALS.map(m=>[m,0]))};
let finEntries=[]; // loaded from Firestore

// ════════════════════════════════════════
//  VIEW ROUTER + BOTTOM NAV
// ════════════════════════════════════════
function showView(name){
  curView=name;
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  $('view-'+name).classList.add('active');
  const hasGlobalHeader=['cal','tarifas','finanzas','solicitudes'].includes(name);
  $('g-header').style.display=hasGlobalHeader?'flex':'none';
  $('bottom-nav').style.display=hasGlobalHeader?'flex':'none';
  // sync nav
  document.querySelectorAll('.nav-btn').forEach(b=>{
    b.classList.toggle('active',b.dataset.view===name);
  });
  if(name==='tarifas') renderTarifas();
  if(name==='solicitudes') renderSolicitudes();
  if(name==='finanzas') renderFinanzas();
  if(name==='presupuestos') renderPresupuestos();
}

document.querySelectorAll('.nav-btn').forEach(btn=>{
  btn.addEventListener('click',()=>showView(btn.dataset.view));
});

// ════════════════════════════════════════
//  SOLICITUDES (embudo: trabajos sin fecha)
// ════════════════════════════════════════
const STAGE_AT={presupuestado:'quotedAt',aceptado:'acceptedAt',programado:'scheduledAt',perdido:'lostAt'};
let pipeline=[],pipeUnsub;
function subscribePipeline(){
  if(pipeUnsub)pipeUnsub();
  const q=query(collection(db,'trabajos'),where('stage','in',PIPELINE.map(p=>p.id)));
  pipeUnsub=onSnapshot(q,snap=>{
    pipeline=[];snap.forEach(d=>{const j={id:d.id,...d.data()};if(!j.date)pipeline.push(j);});
    updatePipeBadge();
    if(curView==='solicitudes')renderSolicitudes();
    if(curJob&&curView==='detail'&&!curJob.date){const f=pipeline.find(j=>j.id===curJob.id);if(f){curJob=f;renderDetailView();}}
  });
}
function stageSince(j){const st=jobStage(j);return daysAgo(j[STAGE_AT[st]]||j.updatedAt||j.createdAt)}
// Avisos de seguimiento: presupuesto sin respuesta >3 días, aceptado sin fecha >7 días
function needsFollowUp(j){const st=jobStage(j),d=stageSince(j)??0;return (st==='solicitud'&&d>=2)||(st==='presupuestado'&&d>=3)||(st==='aceptado'&&d>=7)}
function updatePipeBadge(){
  const b=$('pipe-badge');if(!b)return;
  const n=pipeline.filter(j=>jobStage(j)==='solicitud'||needsFollowUp(j)).length;   // por presupuestar + seguimientos
  b.textContent=n||'';b.style.display=n?'inline-flex':'none';
}
// Formulario público para clientes (public/presupuesto.html)
const FORM_URL='https://presupuesto.mudanzasdelsur.es';   // dominio propio (Hostinger → Firebase); la portada lleva al formulario
const FORM_MSG='Hola!👋 para poder darte presupuesto necesitaría que rellenases este formulario, son solo 2 minutos y es muy sencillo. Hay que adjuntar fotos pero si lo prefieres me las puedes enviar por aquí 😁';
function renderSolicitudes(){
  const cont=$('solicitudes-content');if(!cont)return;
  const card=j=>{
    const d=stageSince(j),miss=missingInfo(j),fu=needsFollowUp(j);
    return `<div class="job-card" data-pid="${esc(j.id)}">
      <div class="job-card-bar" style="background:${fu?'var(--amber)':'var(--indigo)'}"></div>
      <div class="job-card-body">
        <div class="job-card-top">
          <div class="job-client-name">${esc(j.clientName||'Sin nombre')}${j.source==='web'?' <span class="web-tag">🌐 Web</span>':''}</div>
          ${j.price?`<div class="status-badge" style="background:var(--accentSoft);color:var(--accent)">${fmt(j.price)} €</div>`:''}
        </div>
        ${j.location||(j.services||[]).length?`<div class="job-detail-row">🏷 ${esc([j.location,(j.services||[]).join(', ')].filter(Boolean).join(' · '))}</div>`:''}
        <div class="job-time-row">${d==null?'':d===0?'Hoy':`Hace ${d} día${d>1?'s':''}`}${(j.photos||[]).length?` · 📷 ${j.photos.length}`:''}${fu?' · <strong style="color:var(--amber)">toca seguimiento</strong>':''}</div>
        ${miss.length?`<div class="job-missing">⚠️ Falta: ${miss.join(', ')}</div>`:''}
      </div>
      <div class="job-card-arrow">›</div>
    </div>`;
  };
  cont.innerHTML=`
    <div class="form-link-card">
      <div class="form-link-title">🌐 Formulario «Pide tu presupuesto»</div>
      <div class="form-link-url">${esc(FORM_URL)}</div>
      <div class="form-link-btns">
        <button class="btn btn-ghost btn-sm" id="btn-form-share">📤 Enviar a un cliente</button>
        <button class="btn btn-ghost btn-sm" id="btn-form-copy">Copiar enlace</button>
        <a class="btn btn-ghost btn-sm" href="${esc(FORM_URL)}" target="_blank" rel="noopener">Ver</a>
      </div>
    </div>
    <button class="btn btn-accent" id="btn-new-request" style="width:100%;padding:12px;font-size:.9rem">+ Nueva solicitud</button>
    ${PIPELINE.map(st=>{
      const list=pipeline.filter(j=>jobStage(j)===st.id).sort((a,b)=>(stageSince(b)??0)-(stageSince(a)??0));
      return `<div class="pipe-section">
        <div class="pipe-title">${st.icon} ${st.label} <span class="pipe-count">${list.length}</span></div>
        <div class="pipe-hint">${st.hint}</div>
        ${list.length?list.map(card).join(''):'<div class="empty-state" style="padding:10px">Nada por aquí.</div>'}
      </div>`;}).join('')}`;
  $('btn-new-request').onclick=()=>openNewJob(true);
  $('btn-form-copy').onclick=async()=>{try{await navigator.clipboard.writeText(FORM_URL);toast('Enlace copiado ✓','ok');}catch(e){toast(FORM_URL);}};
  $('btn-form-share').onclick=async()=>{
    if(navigator.share){try{await navigator.share({title:'Pide tu presupuesto · Mudanzas del Sur',text:FORM_MSG,url:FORM_URL});return;}catch(e){if(e&&e.name==='AbortError')return;}}
    window.open(`https://wa.me/?text=${encodeURIComponent(FORM_MSG+'\n\n'+FORM_URL)}`,'_blank');
  };
  cont.querySelectorAll('[data-pid]').forEach(el=>el.onclick=()=>{const j=pipeline.find(x=>x.id===el.dataset.pid);if(j)openJobDetail(j);});
}
async function setStage(job,stage,extra={}){
  const data={stage,...extra,updatedBy:auth.currentUser.email,updatedAt:serverTimestamp()};
  if(STAGE_AT[stage])data[STAGE_AT[stage]]=serverTimestamp();
  await setDoc(doc(db,'trabajos',job.id),data,{merge:true});
  curJob={...curJob,...data,[STAGE_AT[stage]||'_']:new Date().toISOString()};
}

// ════════════════════════════════════════
//  CALENDAR
// ════════════════════════════════════════
function initCal(){
  const now=new Date();calYear=now.getFullYear();calMonth=now.getMonth();selDate=null;
  renderCal();subscribeJobs();
  $('cal-prev').onclick=()=>{calMonth--;if(calMonth<0){calMonth=11;calYear--;}renderCal();subscribeJobs();};
  $('cal-next').onclick=()=>{calMonth++;if(calMonth>11){calMonth=0;calYear++;}renderCal();subscribeJobs();};
}

function renderCal(){
  $('cal-month').textContent=`${MONTHS_ES[calMonth]} ${calYear}`;
  const wr=$('week-row');wr.innerHTML='';
  DAYS_ES.forEach(d=>{const el=document.createElement('div');el.className='week-day';el.textContent=d;wr.appendChild(el);});
  const grid=$('cal-grid');grid.innerHTML='';
  const firstDow=new Date(calYear,calMonth,1).getDay();
  const daysInM=new Date(calYear,calMonth+1,0).getDate();
  const ts=todayStr();
  for(let i=0;i<firstDow;i++){const el=document.createElement('div');el.className='cal-empty';grid.appendChild(el);}
  for(let d=1;d<=daysInM;d++){
    const ds=`${calYear}-${pad(calMonth+1)}-${pad(d)}`;
    const dayJobs=jobsCache[ds]||[];
    const cell=document.createElement('div');
    cell.className='cal-cell'+(ds===ts?' today':'');
    let html=`<div class="day-num">${d}</div>`;
    dayJobs.slice(0,2).forEach(j=>{
      const tag=j._ofDays>1?`${j._day}/${j._ofDays}`:(j.startTime||'');
      html+=`<div class="job-pill" style="background:${statusColor(j.status)}"><span class="pill-time">${tag}</span><span class="pill-name">${esc(j.clientName||'Trabajo')}</span></div>`;
    });
    if(dayJobs.length>2)html+=`<div class="pill-more">+${dayJobs.length-2} más</div>`;
    cell.innerHTML=html;
    cell.onclick=()=>openDay(ds);
    grid.appendChild(cell);
  }
}

function subscribeJobs(){
  if(jobsUnsub)jobsUnsub();
  const start=`${calYear}-${pad(calMonth+1)}-01`,end=`${calYear}-${pad(calMonth+1)}-31`;
  // Se pide desde 30 días antes para incluir trabajos de varios días que empiezan el mes anterior
  const q=query(collection(db,'trabajos'),where('date','>=',addDays(start,-30)),where('date','<=',end));
  jobsUnsub=onSnapshot(q,snap=>{
    jobsCache={};
    snap.forEach(d=>{
      const data={id:d.id,...d.data()};
      const n=jobDays(data);
      for(let i=0;i<n;i++){
        const ds=addDays(data.date,i);
        if(ds<start||ds>end)continue;
        (jobsCache[ds]=jobsCache[ds]||[]).push({...data,_day:i+1,_ofDays:n});
      }
    });
    // Si el trabajo abierto ha cambiado, refrescar su detalle
    if(curJob&&curView==='detail'){
      const fresh=Object.values(jobsCache).flat().find(j=>j.id===curJob.id);
      if(fresh){curJob=stripDay(fresh);renderDetailView();}
    }
    renderCal();
    if(curView==='day'&&selDate)renderDayView();
  });
}

// ════════════════════════════════════════
//  DAY VIEW
// ════════════════════════════════════════
function openDay(ds){selDate=ds;renderDayView();showView('day');}

function renderDayView(){
  if(!selDate)return;
  const[y,m,d]=selDate.split('-').map(Number);
  const dt=new Date(y,m-1,d);
  $('day-title').textContent=`${DAYS_ES[dt.getDay()]}, ${d} ${MONTHS_ES[m-1]}`;
  const jobs=(jobsCache[selDate]||[]).sort((a,b)=>(a.startTime||'').localeCompare(b.startTime||''));
  const cont=$('day-content');
  if(!jobs.length){
    cont.innerHTML=`<div class="day-empty"><div class="day-empty-icon">📦</div><div class="day-empty-text">Sin trabajos este día</div><button class="btn btn-accent" id="btn-day-add" style="padding:12px 28px;font-size:.9rem">Añadir trabajo</button></div>`;
    $('btn-day-add').onclick=()=>openNewJob(false);return;
  }
  cont.innerHTML='';
  jobs.forEach(job=>{
    const card=document.createElement('div');card.className='job-card';
    const sc=statusColor(job.status);
    card.innerHTML=`
      <div class="job-card-bar" style="background:${sc}"></div>
      <div class="job-card-body">
        <div class="job-card-top">
          <div class="job-client-name">${esc(job.clientName||'Sin nombre')}</div>
          <div class="status-badge" style="background:${sc}22;color:${sc}">${statusLabel(job.status)}</div>
        </div>
        <div class="job-time-row">⏰ ${job.startTime||'--:--'}${job.endTime?` – ${job.endTime}`:''}${job._ofDays>1?` · <strong>Día ${job._day} de ${job._ofDays}</strong>`:''}</div>
        ${job.location||(job.services||[]).length?`<div class="job-detail-row">🏷 ${esc([job.location,(job.services||[]).join(', ')].filter(Boolean).join(' · '))}</div>`:''}
        ${vehiclesLabel(job)?`<div class="job-detail-row">🚛 ${esc(vehiclesLabel(job))}</div>`:''}
        ${crewLabel(job)?`<div class="job-detail-row">👷 ${esc(crewLabel(job))}</div>`:''}
        ${job.originAddress?`<div class="job-detail-row">📍 ${esc(job.originAddress)} → ${esc(job.destinAddress||'')}</div>`:''}
        ${(job.photos||[]).length?`<div class="job-detail-row">📷 ${job.photos.length} foto${job.photos.length!==1?'s':''}</div>`:''}
        ${missingInfo(job).length?`<div class="job-missing">⚠️ Falta: ${missingInfo(job).join(', ')}</div>`:''}
      </div>
      <div class="job-card-arrow">›</div>`;
    card.onclick=()=>openJobDetail(job);
    cont.appendChild(card);
  });
  const pend=pendingJobsOn(selDate);
  if(pend.length){
    const btn=document.createElement('button');
    btn.className='btn-complete';btn.style.marginTop='4px';
    btn.textContent=pend.length>1?`✅ Cerrar el día (${pend.length} trabajos)`:'✅ Cerrar el día';
    btn.onclick=()=>openCloseModal(selDate);
    cont.appendChild(btn);
  }
}

$('btn-back-cal').onclick=()=>showView('cal');
$('btn-new-job').onclick=()=>openNewJob(false);

// ════════════════════════════════════════
//  JOB DETAIL
// ════════════════════════════════════════
function stripDay(job){const{_day,_ofDays,...rest}=job;return rest}
function openJobDetail(job){curJob=stripDay(job);formState={...curJob};formPhotos=[...(curJob.photos||[])];renderDetailView();showView('detail');}

// Datos importantes que faltan (para avisar antes del día del trabajo)
function missingInfo(job){
  if(job.status==='completado')return[];
  const m=[];
  if(!waPhone(job.phone))m.push('teléfono');
  if(!job.originAddress&&!job.location)m.push('origen');
  if(!job.destinAddress&&(job.services||[]).some(s=>s==='Mudanza completa'||s==='Porte'))m.push('destino');
  if(!job.price&&(job.date||jobStage(job)!=='solicitud'))m.push('precio');
  if(!job.date){   // solicitud: vehículo y equipo se deciden al programar
    if(!(job.photos||[]).length)m.push('fotos');
    return m;
  }
  // Si otro trabajo del mismo día ya tiene vehículo/equipo, se comparte: no avisar
  const mates=dayMates(job);
  if(!jobVehicles(job).length&&!job.vehicle&&!mates.some(j=>jobVehicles(j).length||j.vehicle))m.push('vehículo');
  if(!jobCrew(job).length&&!job.team&&!mates.some(j=>jobCrew(j).length||j.team))m.push('equipo');
  return m;
}
// Otros trabajos que coinciden en alguno de los días de este trabajo (según lo cargado en el calendario)
function dayMates(job){
  if(!job.date)return[];
  const out=new Map();
  for(let i=0;i<jobDays(job);i++)(jobsCache[addDays(job.date,i)]||[]).forEach(j=>{if(j.id!==job.id)out.set(j.id,stripDay(j));});
  return [...out.values()];
}
// Trabajos pendientes de un día (sin repetir los de varios días)
function pendingJobsOn(ds){
  const out=new Map();
  (jobsCache[ds]||[]).forEach(j=>{if(j.status!=='completado')out.set(j.id,stripDay(j));});
  return [...out.values()].sort((a,b)=>(a.startTime||'').localeCompare(b.startTime||''));
}

function renderDetailView(){
  const job=curJob;
  const sc=statusColor(job.status);
  const cont=$('detail-content');
  const initial=(job.clientName||'?')[0].toUpperCase();
  const isCompleted=job.status==='completado';
  const n=jobDays(job);
  const cd=job.closingData||{};

  let profitSection='';
  if(isCompleted&&job.profit!=null){
    const pColor=job.profit>=0?'var(--green)':'var(--danger)';
    const row=(l,v)=>v?`<div class="detail-row"><span>${l}</span><strong>-${fmt(v)} €</strong></div>`:'';
    const g=cd.group||cd;                       // cierres antiguos guardaban los totales sin "group"
    const shared=(cd.jobIds||[job.id]).length>1;
    profitSection=`<div class="detail-section">
      <div class="detail-section-title">💰 Resultado económico (sin IVA)</div>
      ${shared?`<div class="notes-text" style="color:var(--muted);margin-bottom:6px">Cerrado junto con ${cd.jobIds.length-1} trabajo${cd.jobIds.length>2?'s':''} más del ${fmtDateEs(cd.closeDate||job.date)}. Los gastos comunes se reparten según el precio de cada trabajo (${Math.round((cd.share||0)*100)} % para este).</div>`:''}
      <div class="detail-row"><span>Precio cobrado</span><strong>${fmt(job.price)} €</strong></div>
      ${shared?row('Su parte de los costes',cd.allocCost):`
      ${row('Alquiler vehículos',g.totalVehicles)}
      ${row('Km extra',g.totalExtraKm)}
      ${row('Personal',g.totalLabor)}
      ${row('Material gastado',g.totalMaterials)}
      ${row('Gasoil',g.fuel)}
      ${row('Otros gastos',g.extras)}`}
      ${cd.allocMargin!=null||g.margin!=null?`<div class="detail-row" style="padding-top:6px;border-top:1px solid var(--border)"><span>Margen del trabajo</span><strong>${fmt(shared?cd.allocMargin:g.margin)} €</strong></div>`:''}
      ${shared?row('Su parte del pago a socios',cd.allocPartners):Object.entries(g.partnerPay||{}).map(([n,v])=>row(`Cobra ${esc(n)}`,v)).join('')}
      <div class="detail-row" style="margin-top:4px;padding-top:8px;border-top:1px solid var(--border)">
        <span style="font-weight:800">Beneficio para el negocio</span>
        <strong style="color:${pColor};font-size:1.05rem">${job.profit>=0?'+':''}${fmt(job.profit)} €</strong>
      </div>
      ${shared?`<div class="notes-text" style="color:var(--muted);margin-top:8px">Jornada completa: cobrado ${fmt(g.revenue)} € · costes ${fmt(g.totalCost)} € · socios ${fmt(g.totalPartners)} € · negocio ${fmt(g.profit)} €</div>`:''}
    </div>`;
  }

  const missing=missingInfo(job);
  const hasPhone=!!waPhone(job.phone);
  const waBtns=hasPhone?WA_TEMPLATES.filter(t=>!t.when||t.when(job)).map(t=>
    `<a class="wa-btn" href="${esc(waLink(job.phone,t.text(job)))}" target="_blank" rel="noopener">${t.label}</a>`).join(''):'';

  const st=jobStage(job);
  const pipeSection=job.date?'':`
    <div class="detail-section pipe-actions">
      <div class="detail-section-title">📥 ${STAGE_LABEL[st]}${stageSince(job)!=null?` · hace ${stageSince(job)} día${stageSince(job)===1?'':'s'}`:''}</div>
      <div class="pipe-btns">
        ${st==='solicitud'?`<button class="btn btn-ghost btn-sm" data-stage="presupuestado">📨 Presupuesto enviado</button>`:''}
        ${st!=='aceptado'&&st!=='perdido'?`<button class="btn btn-ghost btn-sm" data-stage="aceptado">🤝 Aceptado</button>`:''}
        ${st!=='perdido'?`<button class="btn btn-ghost btn-sm" data-stage="perdido">✖ Perdido</button>`:`<button class="btn btn-ghost btn-sm" data-stage="solicitud">↺ Recuperar</button>`}
      </div>
      ${st!=='perdido'?`<div class="time-row" style="margin-top:8px">
        <div class="fi"><label>Fecha</label><input type="date" id="pipe-date" /></div>
        <div class="fi"><label>Días</label><input type="number" id="pipe-days" min="1" max="31" value="${jobDays(job)}" /></div>
      </div>
      <button class="btn-complete" id="btn-schedule">📅 Programar en el calendario</button>`:''}
    </div>`;

  cont.innerHTML=`
    ${quoteSection(job)}
    ${pipeSection}
    <div class="detail-card">
      <div class="detail-client-row">
        <div class="detail-avatar">${initial}</div>
        <div>
          <div class="detail-client-name">${esc(job.clientName||'Sin nombre')}</div>
          <div class="detail-phone">${esc([job.location,job.phone].filter(Boolean).join(' · '))}</div>
        </div>
        <div class="status-badge" style="margin-left:auto;background:${sc}22;color:${sc}">${statusLabel(job.status)}</div>
      </div>
      ${(job.services||[]).length?`<div class="mat-tags-row" style="margin-top:10px">${job.services.map(s=>`<span class="mat-tag active">${esc(s)}</span>`).join('')}</div>`:''}
    </div>
    ${missing.length?`<div class="missing-card">⚠️ Falta por apuntar: <strong>${missing.join(', ')}</strong>. <button class="link-btn" id="btn-fill-missing">Completar</button></div>`:''}
    <div class="detail-section">
      <div class="detail-section-title">💬 WhatsApp</div>
      ${hasPhone?`<div class="wa-row">${waBtns}</div>`
        :`<div class="notes-text" style="color:var(--muted)">Añade el teléfono del cliente para escribirle por WhatsApp desde aquí.</div>`}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">📅 Fecha y horario</div>
      <div class="detail-row"><span>${n>1?'Días':'Día'}</span><strong>${n>1?`${fmtDateEs(job.date)} → ${fmtDateEs(addDays(job.date,n-1))} (${n} días)`:fmtDateEs(job.date)}</strong></div>
      <div class="detail-row"><span>Inicio</span><strong>${esc(job.startTime||'—')}</strong></div>
      ${job.endTime?`<div class="detail-row"><span>Fin aprox.</span><strong>${esc(job.endTime)}</strong></div>`:''}
      ${job.price?`<div class="detail-row"><span>Precio (sin IVA)</span><strong>${fmt(job.price)} €</strong></div>`:''}
      ${job.payment?`<div class="detail-row"><span>Pago</span><strong>${esc(job.payment)}</strong></div>`:''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">🚛 Vehículos y equipo</div>
      <div class="detail-row"><span>Vehículos</span><strong>${esc(vehiclesLabel(job)||'—')}</strong></div>
      <div class="detail-row"><span>Equipo</span><strong>${esc(crewLabel(job)||'—')}</strong></div>
      ${job.plate?`<div class="detail-row"><span>Matrícula</span><strong>${esc(job.plate)}</strong></div>`:''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">📍 Origen</div>
      <div class="detail-row"><span>Dirección</span><strong>${esc(job.originAddress||'—')}</strong></div>
      <div class="detail-row"><span>Piso / Puerta</span><strong>${esc(job.originFloor||'—')}</strong></div>
      <div class="detail-row"><span>Ascensor</span><strong>${ELEV_LABEL(elev(job,'originElevator'))}</strong></div>
      ${accessLabel(job.originAccess)?`<div class="notes-text" style="margin-top:4px">🚚 ${esc(accessLabel(job.originAccess))}</div>`:''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">🏠 Destino</div>
      <div class="detail-row"><span>Dirección</span><strong>${esc(job.destinAddress||'—')}</strong></div>
      <div class="detail-row"><span>Piso / Puerta</span><strong>${esc(job.destinFloor||'—')}</strong></div>
      <div class="detail-row"><span>Ascensor</span><strong>${ELEV_LABEL(elev(job,'destinElevator'))}</strong></div>
      ${accessLabel(job.destinAccess)?`<div class="notes-text" style="margin-top:4px">🚚 ${esc(accessLabel(job.destinAccess))}</div>`:''}
    </div>
    ${(job.materials||[]).length?`<div class="detail-section"><div class="detail-section-title">📦 Material planificado</div><div class="mat-tags-row">${job.materials.map(m=>`<span class="mat-tag active">${esc(m)}</span>`).join('')}</div></div>`:''}
    ${job.notes?`<div class="detail-section"><div class="detail-section-title">📝 Notas</div><div class="notes-text">${esc(job.notes)}</div></div>`:''}
    ${(job.photos||[]).length?`<div class="detail-section"><div class="detail-section-title">📷 Fotos (${job.photos.length})</div><div class="photo-grid">${job.photos.map(p=>`<img class="photo-thumb" src="${p.url||p.localSrc}" loading="lazy" onclick="openLb('${p.url||p.localSrc}')" />`).join('')}</div></div>`:''}
    ${profitSection}
    ${isCompleted
      ? `<div class="completed-badge">✅ Trabajo completado y cerrado</div>`
      : job.date?`<button class="btn-complete" id="btn-complete-job">✅ Marcar como completado</button>`:''}
    <button class="btn-danger-outline" id="btn-del-job">🗑 Eliminar trabajo</button>`;

  if(!isCompleted&&job.date){
    $('btn-complete-job').onclick=()=>openCloseModal(curJob.date,curJob.id);
  }
  cont.querySelectorAll('[data-stage]').forEach(b=>b.onclick=async()=>{
    try{await setStage(curJob,b.dataset.stage);toast(`✅ ${STAGE_LABEL[b.dataset.stage]}`,'ok');renderDetailView();}
    catch(e){toast('Error: '+e.message,'err');}
  });
  if($('btn-schedule'))$('btn-schedule').onclick=async()=>{
    const d=$('pipe-date').value,n=Math.min(31,Math.max(1,parseInt($('pipe-days').value)||1));
    if(!d){toast('Elige la fecha','err');return;}
    try{
      await setStage(curJob,'programado',{date:d,days:n});
      toast('📅 Programado','ok');selDate=d;renderDetailView();
    }catch(e){toast('Error: '+e.message,'err');}
  };
  if($('btn-fill-missing'))$('btn-fill-missing').onclick=()=>editCurJob();
  cont.querySelectorAll('[data-quote-open]').forEach(b=>b.onclick=()=>openQuote());
  if($('btn-quote-wa'))$('btn-quote-wa').addEventListener('click',()=>{
    // El enlace abre WhatsApp; a la vez la solicitud pasa a «Presupuesto enviado»
    if(jobStage(curJob)==='solicitud')setStage(curJob,'presupuestado').then(()=>{toast('📨 Marcado como presupuesto enviado','ok');renderDetailView();}).catch(()=>{});
  });
  $('btn-del-job').onclick=async()=>{
    if(!confirm('¿Eliminar este trabajo?'))return;
    try{await deleteDoc(doc(db,'trabajos',curJob.id));toast('Trabajo eliminado');showView('day');}
    catch(e){toast('Error eliminando','err');}
  };
}

// ── Presupuesto desde la solicitud ──
const PISO_ASC=(f,e)=>[f,e===true?'con ascensor':e===false?'sin ascensor':''].filter(Boolean).join(', ');
// Lo que el cliente nos ha contado, en una línea por bloque (sirve para calcular el precio)
function clientSummary(j){
  const lado=(icon,addr,floor,el,acc)=>{const t=[addr,PISO_ASC(floor,el),accessLabel(acc)].filter(Boolean).join(' · ');return t?`${icon} ${t}`:'';};
  const fecha=j.date?`📅 ${fmtDateEs(j.date)}`:j.desiredDate?`📅 Le viene bien: ${fmtDateEs(j.desiredDate)}`:'';
  return [
    (j.services||[]).length?`📦 ${j.services.join(', ')}`:'',
    lado('📍',j.originAddress,j.originFloor,elev(j,'originElevator'),j.originAccess),
    lado('🏠',j.destinAddress,j.destinFloor,elev(j,'destinElevator'),j.destinAccess),
    fecha,
    (j.photos||[]).length?`📷 ${j.photos.length} foto${j.photos.length>1?'s':''} (abajo)`:'📷 Sin fotos todavía',
  ].filter(Boolean);
}
function quoteSection(job){
  if(job.status==='completado')return '';
  const r=job.estimate&&job.estimate.result,price=Number(job.price||0);
  if(job.date)return '';                    // trabajos ya programados: el precio va en Editar
  const hasPhone=!!waPhone(job.phone);
  const lines=clientSummary(job).map(l=>`<div class="quote-line">${esc(l)}</div>`).join('');
  if(!price) return `
    <div class="detail-section quote-box">
      <div class="detail-section-title">💶 Presupuesto</div>
      <div class="quote-summary">${lines}</div>
      <button class="btn-complete" data-quote-open>🧮 Calcular presupuesto</button>
    </div>`;
  const msg=quoteMessage(job);
  return `
    <div class="detail-section quote-box">
      <div class="detail-section-title">💶 Presupuesto</div>
      <div class="quote-price"><span>Precio cerrado</span><strong>${fmt(price).replace('.00','')} €</strong></div>
      ${r?`<div class="notes-text" style="color:var(--muted)">Coste ${fmt(r.cost)} € + ${fmt(r.business)} € para el negocio${r.fuel?` · gasoil ${fmt(r.fuel)} €`:''}</div>`:''}
      <div class="quote-msg">${esc(msg)}</div>
      ${hasPhone?`<a class="btn-wa-big" id="btn-quote-wa" href="${esc(waLink(job.phone,msg))}" target="_blank" rel="noopener">📤 Enviar presupuesto por WhatsApp</a>`
        :`<div class="notes-text" style="color:var(--danger)">Falta el teléfono del cliente para enviarlo por WhatsApp.</div>`}
      <button class="btn btn-ghost btn-sm" data-quote-open style="margin-top:8px">✏️ Recalcular</button>
    </div>`;
}
function openQuote(){
  formState={...curJob};formPhotos=[...(curJob.photos||[])];
  openJobForm(true);activeTab='quote';renderTabBar();renderFormTab();
}
// Mensaje breve del presupuesto (formato de Alberto). Se edita en Tarifas → «Mensaje del presupuesto».
// Las líneas cuyo dato falta (p. ej. sin m³) se quitan solas.
const DEFAULT_QUOTE_MSG=`Hola {nombre}, {saludo} 👋

Soy Alberto, de *Mudanzas del Sur*. Te paso el presupuesto de tu {servicio}:

📍 {origen} → {destino}
📅 {fecha}
📦 {m3} m³ aprox.

💶 *{precio} €*

Incluye {incluye}. Precio cerrado.

Si te encaja, confírmamelo por aquí y te bloqueo la fecha. Y si quieres que te lo detalle más, me dices 🙂

Un saludo,
*Alberto — Mudanzas del Sur*
📞 659 71 52 71`;
const DIAS_L=['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
const MESES_L=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
function fmtDateLong(ds){const d=new Date(ds+'T12:00:00');return isNaN(d)?'':`${DIAS_L[d.getDay()]} ${d.getDate()} de ${MESES_L[d.getMonth()]}`;}
const numEs=n=>Number(n).toLocaleString('es-ES',{maximumFractionDigits:2});
function listaEs(a){a=a.filter(Boolean);return a.length<2?(a[0]||''):a.slice(0,-1).join(', ')+', y '+a[a.length-1];}
function saludoHora(h=new Date().getHours()){return h<14?'buenos días':h<21?'buenas tardes':'buenas noches';}
// "camión de 20 m³ y furgoneta", "2 furgonetas"…
function vehiculosTexto(vs){
  const n={iveco:0,crafter:0};(vs||[]).forEach(v=>{if(v.type in n)n[v.type]++;});
  const t=[];
  if(n.iveco)t.push(n.iveco>1?`${n.iveco} camiones de 20 m³`:'camión de 20 m³');
  if(n.crafter)t.push(n.crafter>1?`${n.crafter} furgonetas`:'furgoneta');
  return t.join(' y ');
}
const INCLUYE_SERV={'Desmontaje y montaje':'desmontaje y montaje de muebles','Embalaje':'embalaje','Vajilla / frágil':'embalaje de piezas frágiles'};
function quoteMessage(j){
  const e=j.estimate||{};
  const town=a=>String(a||'').split(',').map(x=>x.trim()).filter(Boolean).pop()||'';
  const veh=vehiculosTexto((e.vehicles&&e.vehicles.length)?e.vehicles:jobVehicles(j));
  const personas=(Number(e.workers)||0)+(Number(e.partners)||0)||jobCrew(j).length;
  const serv=j.services||[];
  const incluye=listaEs([veh,personas?`equipo de ${personas} persona${personas>1?'s':''}`:'',
    ...serv.map(s=>INCLUYE_SERV[s]).filter(Boolean),'carga y descarga']);
  const vals={
    nombre:firstName(j), saludo:saludoHora(),
    servicio:serv.includes('Mudanza completa')||!serv.length?'mudanza':serv[0].toLowerCase(),
    servicios:serv.join(', ')||'Mudanza',
    origen:town(j.originAddress)||j.location||'', destino:town(j.destinAddress)||'',
    fecha:j.date?fmtDateLong(j.date):j.desiredDate?fmtDateLong(j.desiredDate):'',
    m3:Number(e.m3)?numEs(e.m3):'',
    precio:numEs(Number(j.price||0)),
    vehiculos:veh, personas:personas?String(personas):'', incluye,
  };
  const tpl=String(tarifas.quoteMsg||DEFAULT_QUOTE_MSG);
  return tpl.split('\n').map(line=>{
    const keys=[...line.matchAll(/\{(\w+)\}/g)].map(m=>m[1]).filter(k=>k in vals);
    if(keys.includes('origen')&&keys.includes('destino')&&(vals.origen||vals.destino)&&!(vals.origen&&vals.destino))
      return line.replace(/\{origen\}\s*→\s*\{destino\}/,vals.origen||vals.destino);   // solo uno conocido
    if(keys.some(k=>k!=='nombre'&&!vals[k]))return null;                              // falta el dato → fuera la línea
    return line;
  }).filter(l=>l!==null).join('\n')
    .replace(/\{(\w+)\}/g,(m,k)=>k in vals?vals[k]:m)
    .replace(/Hola , /,'Hola, ').replace(/\n{3,}/g,'\n\n').trim();
}

// ── Mensajes de WhatsApp preparados ──
function firstName(job){return (job.clientName||'').trim().split(/\s+/)[0]||''}
const WA_TEMPLATES=[
  {label:'📅 Confirmar',when:j=>j.status!=='completado'&&!!j.date,text:j=>{
    const n=jobDays(j);
    return `Hola ${firstName(j)}, te escribo de Mudanzas del Sur para confirmar tu ${((j.services||[])[0]||'mudanza').toLowerCase()} el ${fmtDateEs(j.date)}${n>1?` (${n} días)`:''}${j.startTime?` a las ${j.startTime}`:''}.\n\nPara que todo vaya rápido:\n• Ten a mano las llaves y, si hace falta, el permiso para aparcar el camión.\n• Si puedes, deja vacíos los armarios y cajones.\n• Avísanos de cualquier cambio de última hora.\n\n¡Nos vemos!`}},
  {label:'📷 Pedir fotos',when:j=>j.status!=='completado',text:j=>
    `Hola ${firstName(j)}, para darte un precio cerrado, ¿me mandas por aquí unas fotos o un vídeo rápido de los muebles y de cada habitación? Y dime también el piso y si hay ascensor en origen y destino. ¡Gracias!`},
  {label:'⭐ Pedir reseña',when:j=>j.status==='completado',text:j=>
    `Hola ${firstName(j)}, ¡gracias por confiar en Mudanzas del Sur! Si quedaste contento, nos ayudaría muchísimo una reseña en Google${tarifas.reviewUrl?`: ${tarifas.reviewUrl}`:''}. Solo te lleva un minuto 🙏`},
  {label:'🔁 ¿Viste el presupuesto?',when:j=>jobStage(j)==='presupuestado',text:j=>
    `Hola ${firstName(j)}, ¿pudiste ver el presupuesto${j.price?` de ${fmt(j.price).replace('.00','')} €`:''}? Si tienes cualquier duda o quieres ajustar algo, dímelo y lo vemos. ¡Un saludo!`},
  {label:'📅 Pedir fecha',when:j=>jobStage(j)==='aceptado',text:j=>
    `Hola ${firstName(j)}, ¿ya sabes qué día te vendría bien para la ${((j.services||[])[0]||'mudanza').toLowerCase()}? Así te lo reservamos, que se nos va llenando la agenda.`},
  {label:'💬 Abrir chat',text:j=>`Hola ${firstName(j)}, `},
];

$('btn-back-day').onclick=()=>{
  if(curJob&&!curJob.date){showView('solicitudes');return;}
  if(!selDate&&curJob)selDate=curJob.date;
  showView('day');renderDayView();
};
function editCurJob(){formState={...curJob};formPhotos=[...(curJob.photos||[])];openJobForm(true);}
$('btn-edit-job').onclick=editCurJob;

// ════════════════════════════════════════
//  CLOSE MODAL — CIERRE ECONÓMICO
// ════════════════════════════════════════
// ── PRESUPUESTO: coste real + % para el negocio ──
// ── Gasoil: km de cada vehículo × su consumo (L/100 km) × precio del litro ──
function fuelAuto(vehicles,t=tarifas){
  let liters=0;
  (vehicles||[]).forEach(v=>{liters+=Number(v.km||0)*Number(t[`consumo_${v.type}`]||0)/100;});
  return {liters:Math.round(liters*10)/10,cost:Math.round(liters*Number(t.fuelPrice||0)*100)/100};
}
// Si se escribe un importe a mano manda ese; si el campo está vacío se usa el automático
function pickFuel(manual,auto){
  return manual!==''&&manual!=null&&!isNaN(Number(manual))?Number(manual):auto;
}
function fuelHint(vehicles,manual,t=tarifas){
  const a=fuelAuto(vehicles,t);
  const km=(vehicles||[]).reduce((s,v)=>s+Number(v.km||0),0);
  if(!km)return `Pon los km de cada vehículo y se calcula solo (${fmt(t.fuelPrice)} €/L).`;
  const auto=`${fmt(km)} km → ${fmt(a.liters)} L × ${fmt(t.fuelPrice)} €/L = ${fmt(a.cost)} €`;
  return pickFuel(manual,null)==null?`Automático: ${auto}`:`Puesto a mano (el automático sería ${fmt(a.cost)} €). Borra la cifra para volver al automático.`;
}

// est = {vehicles:[{type,plan,days,km}], hours, workers, partners, matQty:{}, fuel, extras}
function computeEstimate(est,t=tarifas){
  const r2=x=>Math.round(x*100)/100;
  let rent=0,extraKm=0;
  (est.vehicles||[]).forEach(v=>{
    const kind=(VEHICLE_TYPES.find(x=>x.id===v.type)||{}).kind||'furgoneta';
    const days=Math.max(1,parseInt(v.days)||1);
    rent+=Number(t[`rent_${kind}_${v.plan}`]||0)*days;
    extraKm+=Math.max(0,Number(v.km||0)-Number(v.plan||0)*days)*Number(t.extraKm||0);
  });
  const hours=Number(est.hours||0);
  const labor=hours*Number(est.workers||0)*Number(t.workerHour||0);
  const partners=hours*Number(est.partners||0)*Number(t.partnerHour||0);
  let materials=0;
  Object.entries(est.matQty||{}).forEach(([m,q])=>{if(!REUSABLE.includes(m))materials+=Number(q||0)*Number(t[m]||0);});
  const auto=fuelAuto(est.vehicles,t);
  const fuel=r2(pickFuel(est.fuel,auto.cost)),extras=Number(est.extras||0);
  const cost=r2(rent+extraKm+labor+partners+materials+fuel+extras);
  const business=r2(cost*Number(t.businessPct||0)/100);
  const step=Number(t.roundTo||0);
  const raw=cost+business;
  const price=step>0?Math.ceil(Math.round(raw/step*1e6)/1e6)*step:r2(raw);   // mismo redondeo que el conector
  return {rent:r2(rent),extraKm:r2(extraKm),labor:r2(labor),partners:r2(partners),materials:r2(materials),
    fuel,fuelAuto:auto.cost,fuelLiters:auto.liters,extras,cost,business,price,businessReal:r2(price-cost)};
}

let closeData = {};

// Cálculo puro de un cierre (sin IVA). Un cierre puede incluir varios trabajos que comparten
// vehículos, personal y gastos (p. ej. todos los de un día). Los gastos y el pago a socios se
// reparten entre los trabajos en proporción a su precio.
function computeClosing(jobs,inp,t=tarifas){
  const r2=x=>Math.round(x*100)/100;
  const revenue=r2(jobs.reduce((a,j)=>a+Number(j.price||0),0));
  const defDays=Math.max(1,...jobs.map(jobDays));
  let totalVehicles=0,totalExtraKm=0;
  const vehicles=(inp.vehicles||[]).map(v=>{
    const kind=(VEHICLE_TYPES.find(x=>x.id===v.type)||{}).kind||'furgoneta';
    const days=Math.max(1,parseInt(v.days)||defDays);
    const rent=Number(t[`rent_${kind}_${v.plan}`]||0)*days;
    const included=Number(v.plan||0)*days;
    const km=Number(v.km||0);
    const extraKm=Math.max(0,km-included);
    const extraCost=extraKm*Number(t.extraKm||0);
    totalVehicles+=rent;totalExtraKm+=extraCost;
    return {type:v.type,plan:v.plan,days,km,rent,included,extraKm,extraCost};
  });
  let totalLabor=0;const hours={};
  Object.entries(inp.hours||{}).forEach(([name,h])=>{
    h=Number(h||0);if(!h||PARTNERS.includes(name))return;
    hours[name]=h;totalLabor+=h*Number(t.workerHour||0);
  });
  let totalMaterials=0;const matQty={};
  Object.entries(inp.matQty||{}).forEach(([m,q])=>{
    q=Number(q||0);if(!q||REUSABLE.includes(m))return;
    matQty[m]=q;totalMaterials+=q*Number(t[m]||0);
  });
  const auto=fuelAuto(inp.vehicles,t);
  const fuel=r2(pickFuel(inp.fuel,auto.cost)),extras=Number(inp.extras||0);
  const totalCost=r2(totalVehicles+totalExtraKm+totalLabor+totalMaterials+fuel+extras);
  const partnerPay={};let totalPartners=0;
  Object.entries(inp.partnerPay||{}).forEach(([name,v])=>{v=Number(v||0);if(!v)return;partnerPay[name]=v;totalPartners+=v;});
  totalPartners=r2(totalPartners);
  const margin=r2(revenue-totalCost);
  // Reparto por trabajo según su precio (a partes iguales si no hay precios).
  // El trabajo de mayor peso se queda los céntimos de redondeo, para que todo sume exacto.
  const shares=jobs.map(j=>revenue>0?Number(j.price||0)/revenue:1/jobs.length);
  const big=shares.indexOf(Math.max(...shares,0));
  const split=total=>{const a=shares.map(sh=>r2(total*sh));if(big>=0)a[big]=r2(total-a.reduce((x,y,i)=>i===big?x:x+y,0));return a;};
  const costs=split(totalCost),parts=split(totalPartners);
  const perJob=jobs.map((j,i)=>{
    const allocMargin=r2(Number(j.price||0)-costs[i]);
    return {id:j.id,share:shares[i],allocCost:costs[i],allocPartners:parts[i],allocMargin,profit:r2(allocMargin-parts[i])};
  });
  return {vehicles,hours,matQty,fuel,fuelAuto:auto.cost,fuelLiters:auto.liters,extras,partnerPay,revenue,
    totalVehicles:r2(totalVehicles),totalExtraKm:r2(totalExtraKm),totalLabor:r2(totalLabor),
    totalMaterials:r2(totalMaterials),totalCost,margin,totalPartners,
    profit:r2(margin-totalPartners),perJob};     // profit = beneficio que queda para el negocio
}

// Abre el cierre de un día. Por defecto incluye todos los trabajos pendientes de ese día.
function openCloseModal(ds,onlyId){
  const candidates=pendingJobsOn(ds);
  if(onlyId&&!candidates.some(j=>j.id===onlyId)&&curJob)candidates.unshift(curJob);
  const selected=new Set(candidates.map(j=>j.id));
  const sel=candidates.filter(j=>selected.has(j.id));
  // Vehículos: los apuntados en los trabajos, sin repetir (el mismo vehículo sirve para todo el día)
  const seen=new Set(),vehicles=[];
  sel.forEach(j=>jobVehicles(j).forEach(v=>{const k=v.type+'|'+v.plan;if(!seen.has(k)){seen.add(k);vehicles.push({...v,days:Math.max(1,...sel.map(jobDays)),km:''});}}));
  const crews=[...new Set(sel.flatMap(jobCrew))];
  const people=[...new Set([...WORKERS,...crews.filter(c=>!PARTNERS.includes(c))])];
  closeData={ds,candidates,selected,vehicles,crew:crews,people,
    hours:Object.fromEntries(people.map(p=>[p,''])),
    matQty:{},fuel:'',extras:'',partnerPay:Object.fromEntries(PARTNERS.map(p=>[p,''])),
    partnerHours:Object.fromEntries(PARTNERS.map(p=>[p,'']))};
  renderCloseModal();
  $('close-overlay').classList.add('open');
  document.body.style.overflow='hidden';
}
function closeSelectedJobs(){return closeData.candidates.filter(j=>closeData.selected.has(j.id))}

function renderCloseModal(){
  const c=closeData,sel=closeSelectedJobs();
  const defDays=Math.max(1,...(sel.length?sel:c.candidates).map(jobDays));
  const body=$('close-modal-body');
  const consumables=MATERIALS.filter(m=>!REUSABLE.includes(m));
  const title=$('close-modal-title')||document.querySelector('#close-box .modal-title');   // tolera un index.html antiguo en caché
  if(title)title.textContent=c.candidates.length>1?`✅ Cerrar el ${fmtDateEs(c.ds)}`:'✅ Cerrar trabajo';
  body.innerHTML=`
    ${c.candidates.length>1?`<div class="form-section">
      <div class="form-section-title">📋 Trabajos de este cierre</div>
      <div class="notes-text" style="color:var(--muted);margin-bottom:4px">Los gastos del día se apuntan una sola vez y se reparten según el precio de cada trabajo.</div>
      ${c.candidates.map(j=>`
        <label class="close-job-row">
          <input type="checkbox" data-sel="${esc(j.id)}" ${c.selected.has(j.id)?'checked':''} />
          <span class="close-job-name">${esc(j.clientName||'Sin nombre')}${jobDays(j)>1?` <small>(${jobDays(j)} días)</small>`:''}</span>
          <span class="close-job-price">${j.price?fmt(j.price)+' €':'<span style="color:var(--danger)">sin precio</span>'}</span>
        </label>`).join('')}
    </div>`:''}
    <div class="form-section">
      <div class="form-section-title">🚛 Vehículos alquilados</div>
      ${c.vehicles.length?c.vehicles.map((v,i)=>`
        <div class="veh-close">
          <div class="veh-close-top"><span>${esc(vehicleLabel(v))}</span><button class="photo-remove" style="position:static" data-vdel="${i}">✕</button></div>
          <div class="veh-close-inputs">
            <label>Días <input type="number" min="1" max="31" step="1" data-vdays="${i}" value="${esc(String(v.days||defDays))}" /></label>
            <label>Km totales <input type="number" min="0" step="1" placeholder="0" data-vkm="${i}" value="${esc(String(v.km))}" /></label>
          </div>
        </div>`).join(''):'<div class="notes-text" style="color:var(--muted)">Añade los vehículos que habéis usado:</div>'}
      <div class="mat-tags-row" style="margin-top:6px">
        ${VEHICLE_TYPES.flatMap(t=>KM_PLANS.map(pl=>`<button class="mat-tag" data-vadd="${t.id}|${pl}">+ ${t.id==='crafter'?'Crafter':'Iveco'} ${pl} km</button>`)).join('')}
      </div>
    </div>
    <div class="form-section">
      <div class="form-section-title">⏱ Horas de cada trabajador (incluido el viaje)</div>
      <div class="worker-hours-grid">
        ${c.people.map(p=>`
          <div class="worker-row">
            <span class="worker-label">${esc(p)}${c.crew.includes(p)?' ✓':''}</span>
            <input class="worker-input" type="number" min="0" step="0.5" placeholder="0" data-worker="${esc(p)}" value="${esc(String(c.hours[p]??''))}" />
            <span style="font-size:.75rem;color:var(--muted)">h</span>
          </div>`).join('')}
      </div>
      <div class="add-person-row">
        <input id="close-new-person" placeholder="Otra persona (nombre)" />
        <button class="btn btn-ghost btn-sm" id="close-add-person">Añadir</button>
      </div>
    </div>
    <div class="form-section">
      <div class="form-section-title">📦 Material gastado (las mantas, fajas, etc. no cuentan)</div>
      <div class="mat-qty-grid">
        ${consumables.map(m=>`
          <div class="mat-qty-row">
            <span class="mat-qty-label">${esc(m)}</span>
            <input class="mat-qty-input" type="number" min="0" step="1" placeholder="0" data-mat="${esc(m)}" value="${esc(String(c.matQty[m]??''))}" />
            <span style="font-size:.75rem;color:var(--muted)">ud</span>
          </div>`).join('')}
      </div>
    </div>
    <div class="form-section">
      <div class="form-section-title">⛽ Otros gastos</div>
      <div class="fi"><label>Gasoil (€) · se calcula con los km de los vehículos</label><input type="number" id="chk-fuel" min="0" step="0.5" placeholder="auto" value="${esc(String(c.fuel))}" />
        <div class="fuel-hint" id="chk-fuel-hint"></div></div>
      <div class="fi"><label>Otros: peajes, parking, comida… (€)</label><input type="number" id="chk-extras" min="0" step="0.5" placeholder="0.00" value="${esc(String(c.extras))}" /></div>
    </div>
    <div class="form-section">
      <div class="form-section-title">💼 Socios (${fmt(tarifas.partnerHour)} €/h)</div>
      <div class="notes-text" style="color:var(--muted);margin-bottom:4px" id="close-margin-hint"></div>
      <div class="worker-hours-grid">
        ${PARTNERS.map(p=>`
          <div class="worker-row">
            <span class="worker-label">${esc(p)}</span>
            <input class="worker-input" type="number" min="0" step="0.5" placeholder="h" data-phours="${esc(p)}" value="${esc(String(c.partnerHours[p]??''))}" />
            <span style="font-size:.75rem;color:var(--muted)">h</span>
            <input class="worker-input" type="number" min="0" step="1" placeholder="0" data-partner="${esc(p)}" value="${esc(String(c.partnerPay[p]??''))}" />
            <span style="font-size:.75rem;color:var(--muted)">€</span>
          </div>`).join('')}
      </div>
    </div>
    <div class="calc-preview" id="close-calc"></div>`;

  body.querySelectorAll('[data-sel]').forEach(cb=>cb.onchange=()=>{cb.checked?c.selected.add(cb.dataset.sel):c.selected.delete(cb.dataset.sel);updateCloseCalc();});
  body.querySelectorAll('[data-vkm]').forEach(inp=>inp.oninput=()=>{c.vehicles[+inp.dataset.vkm].km=inp.value;updateCloseCalc();});
  body.querySelectorAll('[data-vdays]').forEach(inp=>inp.oninput=()=>{c.vehicles[+inp.dataset.vdays].days=inp.value;updateCloseCalc();});
  body.querySelectorAll('[data-vdel]').forEach(b=>b.onclick=()=>{c.vehicles.splice(+b.dataset.vdel,1);renderCloseModal();});
  body.querySelectorAll('[data-vadd]').forEach(b=>b.onclick=()=>{const[type,plan]=b.dataset.vadd.split('|');c.vehicles.push({type,plan:+plan,days:defDays,km:''});renderCloseModal();});
  body.querySelectorAll('[data-worker]').forEach(inp=>inp.oninput=()=>{c.hours[inp.dataset.worker]=inp.value;updateCloseCalc();});
  body.querySelectorAll('[data-mat]').forEach(inp=>inp.oninput=()=>{c.matQty[inp.dataset.mat]=inp.value;updateCloseCalc();});
  body.querySelectorAll('[data-partner]').forEach(inp=>inp.oninput=()=>{c.partnerPay[inp.dataset.partner]=inp.value;updateCloseCalc();});
  // Horas de socio → importe automático (se puede retocar a mano)
  body.querySelectorAll('[data-phours]').forEach(inp=>inp.oninput=()=>{
    const p=inp.dataset.phours;c.partnerHours[p]=inp.value;
    const v=Number(inp.value||0)*Number(tarifas.partnerHour||0);
    c.partnerPay[p]=v?String(Math.round(v*100)/100):'';
    const out=body.querySelector(`[data-partner="${CSS.escape(p)}"]`);if(out)out.value=c.partnerPay[p];
    updateCloseCalc();});
  $('chk-fuel').oninput=e=>{c.fuel=e.target.value;updateCloseCalc();};
  $('chk-extras').oninput=e=>{c.extras=e.target.value;updateCloseCalc();};
  $('close-add-person').onclick=()=>{
    const n=$('close-new-person').value.trim();
    if(!n||c.people.includes(n))return;
    c.people.push(n);c.hours[n]='';renderCloseModal();
  };
  updateCloseCalc();
}

function updateCloseCalc(){
  const sel=closeSelectedJobs();
  const r=computeClosing(sel,closeData);
  const pClass=r.profit>=0?'profit-pos':'profit-neg';
  const fh=$('chk-fuel-hint');if(fh)fh.textContent=fuelHint(closeData.vehicles,closeData.fuel);
  const fi=$('chk-fuel');if(fi)fi.placeholder=r.fuelAuto?String(r.fuelAuto):'auto';
  const hint=$('close-margin-hint');
  if(hint)hint.textContent=`Pon vuestras horas y se calcula lo que cobra cada uno. Margen después de gastos: ${fmt(r.margin)} €; lo que no os repartáis queda para el negocio.`;
  const line=(l,v)=>`<div class="calc-row" style="color:var(--muted)"><span>${l}</span><span>-${fmt(v)} €</span></div>`;
  const kmNote=r.vehicles.filter(v=>v.extraKm>0).map(v=>`${v.extraKm} km extra`).join(', ');
  const noPrice=sel.filter(j=>!Number(j.price));
  $('close-calc').innerHTML=`
    <div class="calc-row"><span>Cobrado (sin IVA)${sel.length>1?` · ${sel.length} trabajos`:''}</span><span>${fmt(r.revenue)} €</span></div>
    ${line('Alquiler vehículos',r.totalVehicles)}
    ${line(`Km extra${kmNote?` (${kmNote})`:''}`,r.totalExtraKm)}
    ${line(`Personal (${fmt(tarifas.workerHour)} €/h)`,r.totalLabor)}
    ${line('Material gastado',r.totalMaterials)}
    ${line(`Gasoil${r.fuelLiters&&r.fuel===r.fuelAuto?` (${fmt(r.fuelLiters)} L)`:''}`,r.fuel)}
    ${line('Otros gastos',r.extras)}
    <div class="calc-row total"><span>Total costes</span><span>${fmt(r.totalCost)} €</span></div>
    <div class="calc-row"><span>Margen</span><span>${fmt(r.margin)} €</span></div>
    ${Object.entries(r.partnerPay).map(([n,v])=>line(`Cobra ${esc(n)}`,v)).join('')}
    <div class="calc-row ${pClass}"><span>🏢 Beneficio para el negocio</span><span>${r.profit>=0?'+':''}${fmt(r.profit)} €</span></div>
    ${sel.length>1?`<div class="calc-split">${r.perJob.map(p=>{const j=sel.find(x=>x.id===p.id);return `<div class="calc-row"><span>${esc(j.clientName||'')}</span><span>${p.profit>=0?'+':''}${fmt(p.profit)} €</span></div>`;}).join('')}</div>`:''}
    ${noPrice.length?`<div class="calc-row" style="color:var(--danger)"><span>⚠️ Sin precio: ${noPrice.map(j=>esc(j.clientName||'')).join(', ')}</span></div>`:''}
    ${!sel.length?'<div class="calc-row" style="color:var(--danger)"><span>Marca al menos un trabajo</span></div>':''}`;
  $('close-modal-save').disabled=!sel.length;
}

function closeCloseModal(){
  $('close-overlay').classList.remove('open');
  document.body.style.overflow='';
}

$('close-modal-x').onclick=closeCloseModal;
$('close-modal-cancel').onclick=closeCloseModal;
$('close-overlay').onclick=e=>{if(e.target===$('close-overlay'))closeCloseModal();};

$('close-modal-save').addEventListener('click',async()=>{
  const jobs=closeSelectedJobs();
  if(!jobs.length)return;
  const r=computeClosing(jobs,closeData);
  const {perJob,profit,...group}=r;
  const groupId=`c${Date.now()}`;
  const jobIds=jobs.map(j=>j.id);
  const names=jobs.map(j=>(j.clientName||'Sin nombre').trim()).join(', ');
  const closeDate=closeData.ds;
  const btn=$('close-modal-save');
  btn.innerHTML='<span class="spin"></span>';btn.disabled=true;
  try{
    const who=auth.currentUser.email;
    for(const j of jobs){
      const pj=perJob.find(p=>p.id===j.id);
      await setDoc(doc(db,'trabajos',j.id),{
        status:'completado',profit:pj.profit,
        closingData:{groupId,jobIds,closeDate,share:pj.share,allocCost:pj.allocCost,
          allocPartners:pj.allocPartners,allocMargin:pj.allocMargin,group:{...group,profit,partnerHours:closeData.partnerHours}},
        completedBy:who,completedAt:serverTimestamp()
      },{merge:true});
    }
    // Finanzas: un ingreso por trabajo; los costes y el pago a socios, una vez por cierre
    const base={date:closeDate,groupId,jobIds,createdBy:who,createdAt:serverTimestamp()};
    for(const j of jobs)if(Number(j.price))
      await addDoc(collection(db,'finanzas'),{...base,jobId:j.id,type:'income',amount:Number(j.price),description:`Cobro: ${(j.clientName||'Sin nombre').trim()}`});
    if(r.totalCost)await addDoc(collection(db,'finanzas'),{...base,type:'expense',amount:r.totalCost,
      description:jobs.length>1?`Costes ${fmtDateEs(closeDate)}: ${names}`:`Costes trabajo: ${names}`});
    for(const [name,amount] of Object.entries(r.partnerPay))
      await addDoc(collection(db,'finanzas'),{...base,type:'expense',amount,partner:name,
        description:`Pago socio ${name} · ${jobs.length>1?fmtDateEs(closeDate):names}`});
    toast(jobs.length>1?`✅ ${jobs.length} trabajos cerrados`:'✅ Trabajo cerrado','ok');
    closeCloseModal();
    if(curView==='detail'&&curJob&&jobIds.includes(curJob.id)){
      const pj=perJob.find(p=>p.id===curJob.id);
      curJob={...curJob,status:'completado',profit:pj.profit,closingData:{groupId,jobIds,closeDate,share:pj.share,allocCost:pj.allocCost,allocPartners:pj.allocPartners,allocMargin:pj.allocMargin,group:{...group,profit}}};
      renderDetailView();
    }
  }catch(e){toast('Error: '+e.message,'err');}
  finally{btn.textContent='Confirmar y cerrar';btn.disabled=false;}
});

// ════════════════════════════════════════
//  JOB FORM
// ════════════════════════════════════════
const FORM_TABS=[
  {id:'info',label:'📋 Info'},
  {id:'addresses',label:'📍 Direcciones'},
  {id:'resources',label:'🚛 Equipo'},
  {id:'materials',label:'📦 Material'},
  {id:'quote',label:'💶 Presupuesto'},
  {id:'photos',label:'📷 Fotos'},
];

// asRequest=true → nueva solicitud sin fecha (desde la pestaña Solicitudes)
function openNewJob(asRequest){
  curJob=null;isEditing=false;
  formState={clientName:'',phone:'',email:'',location:'',services:[],
    date:asRequest===true?'':(selDate||todayStr()),stage:asRequest===true?'solicitud':'programado',
    originAccess:{},destinAccess:{},estimate:null,
    days:1,startTime:'08:00',endTime:'',
    vehicles:[],crew:[],plate:'',price:'',payment:'',
    originAddress:'',originFloor:'',originElevator:null,
    destinAddress:'',destinFloor:'',destinElevator:null,
    materials:[],notes:'',status:'pendiente'};
  formPhotos=[];activeTab='info';
  $('form-title').textContent='Nuevo trabajo';
  renderTabBar();renderFormTab();showView('form');
}
function openJobForm(editing){
  isEditing=editing;activeTab='info';
  // Normaliza trabajos antiguos para el formulario nuevo
  formState={...formState,
    services:formState.services||[],crew:jobCrew(formState),vehicles:jobVehicles(formState),
    originElevator:elev(formState,'originElevator'),destinElevator:elev(formState,'destinElevator'),
    originAccess:formState.originAccess||{},destinAccess:formState.destinAccess||{},
    days:jobDays(formState),date:formState.date||''};
  $('form-title').textContent=editing?(formState.date?'Editar trabajo':'Editar solicitud'):'Nuevo trabajo';
  renderTabBar();renderFormTab();showView('form');
}
function renderTabBar(){
  const bar=$('tab-bar');bar.innerHTML='';
  FORM_TABS.forEach(t=>{
    const btn=document.createElement('button');
    btn.className='tab-btn'+(t.id===activeTab?' active':'');
    btn.textContent=t.label;
    btn.onclick=()=>{activeTab=t.id;renderTabBar();renderFormTab();};
    bar.appendChild(btn);
  });
}
function elevButtons(id,val){
  return `<div class="tri-row" id="${id}">
    ${[[true,'Sí'],[false,'No'],[null,'No sé']].map(([v,l])=>`<button class="tri-opt${val===v?' active':''}" data-tri="${v}">${l}</button>`).join('')}
  </div>`;
}
function bindElev(id,key){
  $(id).querySelectorAll('[data-tri]').forEach(b=>b.onclick=()=>{
    formState[key]=b.dataset.tri==='true'?true:b.dataset.tri==='false'?false:null;renderFormTab();});
}
function accessFields(k,a){
  return `
    <div class="fi"><label>¿Dónde aparca el camión?</label>
      <div class="tri-row tri-wrap">${PARKING.map(([v,l])=>`<button class="tri-opt${a.parking===v?' active':''}" data-acc="${k}" data-park="${v}">${l}</button>`).join('')}</div></div>
    <div class="fi"><label>Tramos de escalera hasta el portal</label>
      <div class="tri-row">${[0,1,2,3].map(n=>`<button class="tri-opt${a.steps!==undefined&&a.steps!==null&&Number(a.steps)===n?' active':''}" data-acc="${k}" data-steps="${n}">${n===3?'3 o más':n===0?'Ninguno':n}</button>`).join('')}</div></div>
    <div class="mat-grid">
      ${[['smallElevator','Ascensor pequeño'],['narrowStreet','Calle estrecha'],['permit','Hace falta permiso de carga']].map(([key,l])=>`<button class="mat-tag${a[key]?' active':''}" data-acc="${k}" data-flag="${key}">${l}</button>`).join('')}
    </div>`;
}
function bindAccess(k,key){
  const scroll=$('form-scroll');
  const upd=fn=>{formState[key]={...(formState[key]||{})};fn(formState[key]);renderFormTab();};
  scroll.querySelectorAll(`[data-acc="${k}"][data-park]`).forEach(b=>b.onclick=()=>upd(a=>{a.parking=a.parking===b.dataset.park?null:b.dataset.park;}));
  scroll.querySelectorAll(`[data-acc="${k}"][data-steps]`).forEach(b=>b.onclick=()=>upd(a=>{const n=+b.dataset.steps;a.steps=a.steps===n?null:n;}));
  scroll.querySelectorAll(`[data-acc="${k}"][data-flag]`).forEach(b=>b.onclick=()=>upd(a=>{a[b.dataset.flag]=!a[b.dataset.flag];}));
}
// Valores iniciales de la calculadora a partir de lo apuntado en el trabajo
function defaultEstimate(f){
  const crew=jobCrew(f);
  return {
    vehicles:jobVehicles(f).length?jobVehicles(f).map(v=>({type:v.type,plan:v.plan,days:jobDays(f),km:''}))
      :[{type:(f.services||[]).includes('Mudanza completa')?'iveco':'crafter',plan:200,days:jobDays(f),km:''}],
    hours:'',workers:crew.length?crew.filter(c=>!PARTNERS.includes(c)).length:1,
    partners:crew.length?crew.filter(c=>PARTNERS.includes(c)).length:2,
    matQty:{},fuel:'',extras:''};
}
function renderQuoteTab(scroll){
  const f=formState;
  if(!f.estimate)f.estimate=defaultEstimate(f);
  const e=f.estimate;
  const consumables=MATERIALS.filter(m=>!REUSABLE.includes(m));
  scroll.innerHTML=`
    <div class="form-section">
      <div class="form-section-title">🚛 Vehículos</div>
      ${e.vehicles.map((v,i)=>`
        <div class="veh-close">
          <div class="veh-close-top"><span>${esc(vehicleLabel(v))}</span><button class="photo-remove" style="position:static" data-qvdel="${i}">✕</button></div>
          <div class="veh-close-inputs">
            <label>Días <input type="number" min="1" max="31" step="1" data-qvdays="${i}" value="${esc(String(v.days||1))}" /></label>
            <label>Km totales (aprox.) <input type="number" min="0" step="1" placeholder="0" data-qvkm="${i}" value="${esc(String(v.km||''))}" /></label>
          </div>
        </div>`).join('')}
      <div class="mat-tags-row">
        ${VEHICLE_TYPES.flatMap(t=>KM_PLANS.map(pl=>`<button class="mat-tag" data-qvadd="${t.id}|${pl}">+ ${t.id==='crafter'?'Crafter':'Iveco'} ${pl} km</button>`)).join('')}
      </div>
    </div>
    <div class="form-section">
      <div class="form-section-title">📦 Volumen</div>
      <div class="fi"><label>Volumen aprox. (m³) · sale en el mensaje al cliente</label><input id="q-m3" type="number" min="0" step="0.5" inputmode="decimal" placeholder="Ej.: 28" value="${esc(String(e.m3||''))}" /></div>
    </div>
    <div class="form-section">
      <div class="form-section-title">⏱ Personal y horas</div>
      <div class="time-row">
        <div class="fi"><label>Horas (incluido viaje)</label><input id="q-hours" type="number" min="0" step="0.5" inputmode="decimal" placeholder="0" value="${esc(String(e.hours||''))}" /></div>
        <div class="fi"><label>Trabajadores</label><input id="q-workers" type="number" min="0" step="1" value="${esc(String(e.workers??0))}" /></div>
        <div class="fi"><label>Socios</label><input id="q-partners" type="number" min="0" max="2" step="1" value="${esc(String(e.partners??0))}" /></div>
      </div>
      <div class="notes-text" style="color:var(--muted)">Trabajadores a ${fmt(tarifas.workerHour)} €/h · socios a ${fmt(tarifas.partnerHour)} €/h.${accessLabel(f.originAccess)||accessLabel(f.destinAccess)?` Accesos: ${esc([accessLabel(f.originAccess),accessLabel(f.destinAccess)].filter(Boolean).join(' / '))}.`:''}</div>
    </div>
    <div class="form-section">
      <div class="form-section-title">📦 Material que se gastará</div>
      <div class="mat-qty-grid">
        ${consumables.map(m=>`
          <div class="mat-qty-row">
            <span class="mat-qty-label">${esc(m)}</span>
            <input class="mat-qty-input" type="number" min="0" step="1" placeholder="0" data-qmat="${esc(m)}" value="${esc(String(e.matQty[m]??''))}" />
            <span style="font-size:.75rem;color:var(--muted)">ud</span>
          </div>`).join('')}
      </div>
    </div>
    <div class="form-section">
      <div class="form-section-title">⛽ Otros</div>
      <div class="time-row">
        <div class="fi"><label>Gasoil (€)</label><input id="q-fuel" type="number" min="0" step="1" placeholder="auto" value="${esc(String(e.fuel??''))}" /></div>
        <div class="fi"><label>Otros (€)</label><input id="q-extras" type="number" min="0" step="1" placeholder="0" value="${esc(String(e.extras||''))}" /></div>
      </div>
      <div class="fuel-hint" id="q-fuel-hint"></div>
    </div>
    <div class="calc-preview" id="quote-calc"></div>
    <button class="btn-complete" id="q-apply">${isEditing&&curJob?'Guardar este precio':'Usar este precio'}</button>`;
  const upd=()=>updateQuoteCalc();
  scroll.querySelectorAll('[data-qvdays]').forEach(i=>i.oninput=()=>{e.vehicles[+i.dataset.qvdays].days=i.value;upd();});
  scroll.querySelectorAll('[data-qvkm]').forEach(i=>i.oninput=()=>{e.vehicles[+i.dataset.qvkm].km=i.value;upd();});
  scroll.querySelectorAll('[data-qvdel]').forEach(b=>b.onclick=()=>{e.vehicles.splice(+b.dataset.qvdel,1);renderFormTab();});
  scroll.querySelectorAll('[data-qvadd]').forEach(b=>b.onclick=()=>{const[type,plan]=b.dataset.qvadd.split('|');e.vehicles.push({type,plan:+plan,days:jobDays(f),km:''});renderFormTab();});
  scroll.querySelectorAll('[data-qmat]').forEach(i=>i.oninput=()=>{e.matQty[i.dataset.qmat]=i.value;upd();});
  [['q-hours','hours'],['q-workers','workers'],['q-partners','partners'],['q-fuel','fuel'],['q-extras','extras'],['q-m3','m3']].forEach(([id,k])=>{$(id).oninput=ev=>{e[k]=ev.target.value;upd();};});
  $('q-apply').onclick=()=>{
    const r=computeEstimate(e);
    if(!r.price){toast('Pon al menos las horas o un vehículo','err');return;}
    formState.price=String(r.price);
    formState.estimate={...e,result:r,at:new Date().toISOString()};
    // Desde una solicitud abierta: se guarda y se vuelve al detalle (pasa a «enviado» al mandarlo por WhatsApp)
    if(isEditing&&curJob){toast(`Precio: ${fmt(r.price)} € ✓`,'ok');$('btn-save-job').click();return;}
    if(!formState.date&&(formState.stage||'solicitud')==='solicitud')formState.stage='presupuestado';
    toast(`Precio: ${fmt(r.price)} € ✓ (guarda para conservarlo)`,'ok');
    updateQuoteCalc();
  };
  updateQuoteCalc();
}
function updateQuoteCalc(){
  const r=computeEstimate(formState.estimate);
  const fh=$('q-fuel-hint');if(fh)fh.textContent=fuelHint(formState.estimate.vehicles,formState.estimate.fuel);
  const fi=$('q-fuel');if(fi)fi.placeholder=r.fuelAuto?String(r.fuelAuto):'auto';
  const line=(l,v)=>v?`<div class="calc-row" style="color:var(--muted)"><span>${l}</span><span>${fmt(v)} €</span></div>`:'';
  $('quote-calc').innerHTML=`
    ${line('Alquiler vehículos',r.rent)}
    ${line('Km extra',r.extraKm)}
    ${line('Trabajadores',r.labor)}
    ${line('Socios',r.partners)}
    ${line('Material',r.materials)}
    ${line(`Gasoil${r.fuelLiters&&r.fuel===r.fuelAuto?` (${fmt(r.fuelLiters)} L)`:''}`,r.fuel)}
    ${line('Otros',r.extras)}
    <div class="calc-row total"><span>Coste del trabajo</span><span>${fmt(r.cost)} €</span></div>
    <div class="calc-row"><span>+ ${fmt(tarifas.businessPct)} % para el negocio</span><span>${fmt(r.business)} €</span></div>
    <div class="calc-row profit-pos"><span>💶 Precio (sin IVA${Number(tarifas.roundTo)?`, redondeado a ${fmt(tarifas.roundTo)} €`:''})</span><span>${fmt(r.price)} €</span></div>
    ${formState.price&&Number(formState.price)!==r.price?`<div class="calc-row" style="color:var(--muted)"><span>Precio apuntado ahora</span><span>${fmt(formState.price)} €</span></div>`:''}`;
}

function renderFormTab(){
  const scroll=$('form-scroll'),f=formState;
  const bind=(id,key)=>{const el=$(id);if(el)el.oninput=()=>formState[key]=el.value;};
  if(activeTab==='info'){
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">Cliente</div>
        <div class="fi"><label>Nombre del cliente</label><input id="f-client" placeholder="Nombre" value="${esc(f.clientName)}" /></div>
        <div class="fi"><label>Teléfono (WhatsApp)</label><input id="f-phone" type="tel" inputmode="tel" placeholder="600 000 000" value="${esc(f.phone)}" /></div>
        <div class="fi"><label>Población</label><input id="f-location" placeholder="Isla Cristina, Huelva…" value="${esc(f.location||'')}" /></div>
      </div>
      <div class="form-section">
        <div class="form-section-title">Servicio</div>
        <div class="mat-grid">
          ${SERVICES.map(sv=>`<button class="mat-tag${(f.services||[]).includes(sv)?' active':''}" data-sv="${esc(sv)}">${esc(sv)}</button>`).join('')}
        </div>
      </div>
      <div class="form-section">
        <div class="form-section-title">Fecha y horario</div>
        ${!f.date?`<div class="notes-text" style="color:var(--muted)">Sin fecha todavía: se guarda en <strong>Solicitudes</strong> (${STAGE_LABEL[f.stage||'solicitud']}). Pon la fecha cuando el cliente la confirme.</div>`:''}
        <div class="time-row">
          <div class="fi"><label>Primer día</label><input id="f-date" type="date" value="${esc(f.date||'')}" /></div>
          <div class="fi"><label>Nº de días</label><input id="f-days" type="number" min="1" max="31" step="1" value="${esc(String(f.days||1))}" /></div>
        </div>
        <div class="time-row">
          <div class="fi"><label>Hora inicio</label><input id="f-start" type="time" value="${esc(f.startTime)}" /></div>
          <div class="fi"><label>Hora fin (opcional)</label><input id="f-end" type="time" value="${esc(f.endTime||'')}" /></div>
        </div>
      </div>
      <div class="form-section">
        <div class="form-section-title">Precio</div>
        <div class="fi"><label>Precio acordado (€, sin IVA)</label><input id="f-price" type="number" inputmode="decimal" placeholder="0.00" step="0.01" value="${esc(String(f.price))}" /></div>
        <div class="fi"><label>Método de pago</label>
          <select id="f-payment">
            <option value="">— —</option>
            ${['Efectivo','Transferencia','Tarjeta','Bizum'].map(p=>`<option${f.payment===p?' selected':''}>${p}</option>`).join('')}
          </select>
        </div>
        <div class="fi"><label>Email (opcional)</label><input id="f-email" type="email" placeholder="Email" value="${esc(f.email||'')}" /></div>
      </div>
      <div class="form-section">
        <div class="form-section-title">Estado</div>
        <div class="status-row">
          ${['pendiente','en_curso','completado'].map(s=>`
            <button class="status-opt" data-s="${s}" style="${f.status===s?`background:${statusColor(s)};color:#fff;border-color:${statusColor(s)}`:''}">
              ${statusLabel(s)}
            </button>`).join('')}
        </div>
      </div>`;
    bind('f-client','clientName');bind('f-phone','phone');bind('f-email','email');bind('f-location','location');
    bind('f-price','price');bind('f-start','startTime');bind('f-end','endTime');bind('f-date','date');
    $('f-days').oninput=e=>formState.days=Math.min(31,Math.max(1,parseInt(e.target.value)||1));
    $('f-payment').onchange=e=>formState.payment=e.target.value;
    scroll.querySelectorAll('[data-sv]').forEach(btn=>btn.onclick=()=>{
      const sv=btn.dataset.sv,cur=formState.services||[];
      formState.services=cur.includes(sv)?cur.filter(x=>x!==sv):[...cur,sv];renderFormTab();});
    scroll.querySelectorAll('.status-opt').forEach(btn=>{btn.onclick=()=>{formState.status=btn.dataset.s;renderFormTab();};});
  }
  if(activeTab==='addresses'){
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">📍 Origen</div>
        <div class="fi"><label>Dirección</label><input id="f-oa" placeholder="Calle, número, población…" value="${esc(f.originAddress)}" /></div>
        <div class="fi"><label>Piso / Puerta</label><input id="f-of" placeholder="3º B, bajo, chalet…" value="${esc(f.originFloor)}" /></div>
        <div class="fi"><label>¿Tiene ascensor?</label>${elevButtons('f-oe',f.originElevator)}</div>
        ${accessFields('o',f.originAccess||{})}
      </div>
      <div class="form-section">
        <div class="form-section-title">🏠 Destino</div>
        <div class="fi"><label>Dirección</label><input id="f-da" placeholder="Calle, número, población…" value="${esc(f.destinAddress)}" /></div>
        <div class="fi"><label>Piso / Puerta</label><input id="f-df" placeholder="2º A, bajo, nave…" value="${esc(f.destinFloor)}" /></div>
        <div class="fi"><label>¿Tiene ascensor?</label>${elevButtons('f-de',f.destinElevator)}</div>
        ${accessFields('d',f.destinAccess||{})}
      </div>
      <div class="form-section">
        <div class="form-section-title">📝 Notas</div>
        <div class="fi"><textarea id="f-notes" rows="4" placeholder="Muebles a desmontar, acceso difícil, calle estrecha…">${esc(f.notes)}</textarea></div>
      </div>`;
    bind('f-oa','originAddress');bind('f-of','originFloor');
    bind('f-da','destinAddress');bind('f-df','destinFloor');bind('f-notes','notes');
    bindElev('f-oe','originElevator');bindElev('f-de','destinElevator');
    bindAccess('o','originAccess');bindAccess('d','destinAccess');
  }
  if(activeTab==='resources'){
    const crew=f.crew||[],veh=f.vehicles||[];
    const extras=crew.filter(c=>!PARTNERS.includes(c)&&!WORKERS.includes(c));
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">🚛 Vehículos de alquiler</div>
        ${veh.length?veh.map((v,i)=>`<div class="veh-row"><span>${esc(vehicleLabel(v))}</span><button class="photo-remove" style="position:static" data-vdel="${i}">✕</button></div>`).join(''):'<div class="notes-text" style="color:var(--muted)">Sin vehículos todavía.</div>'}
        <div class="mat-grid" style="margin-top:6px">
          ${VEHICLE_TYPES.flatMap(t=>KM_PLANS.map(pl=>`<button class="mat-tag" data-vadd="${t.id}|${pl}">+ ${t.id==='crafter'?'Crafter':'Iveco 20 m³'} · ${pl} km</button>`)).join('')}
        </div>
        ${f.vehicle&&!veh.length?`<div class="notes-text" style="color:var(--muted);margin-top:6px">Antes: ${esc(f.vehicle)}</div>`:''}
      </div>
      <div class="form-section">
        <div class="form-section-title">👷 Quién va</div>
        <div class="mat-grid">
          ${[...PARTNERS,...WORKERS,...extras].map(p=>`<button class="mat-tag${crew.includes(p)?' active':''}" data-crew="${esc(p)}">${esc(p)}${PARTNERS.includes(p)?' (socio)':''}</button>`).join('')}
        </div>
        <div class="add-person-row">
          <input id="f-new-person" placeholder="Otra persona (nombre)" />
          <button class="btn btn-ghost btn-sm" id="f-add-person">Añadir</button>
        </div>
        ${f.team&&!crew.length?`<div class="notes-text" style="color:var(--muted);margin-top:6px">Antes: ${esc(f.team)}</div>`:''}
      </div>
      <div class="form-section">
        <div class="form-section-title">🔑 Matrícula (opcional)</div>
        <div class="fi"><input id="f-plate" placeholder="1234 ABC" value="${esc(f.plate||'')}" /></div>
      </div>`;
    scroll.querySelectorAll('[data-vadd]').forEach(b=>b.onclick=()=>{const[type,plan]=b.dataset.vadd.split('|');formState.vehicles=[...veh,{type,plan:+plan}];renderFormTab();});
    scroll.querySelectorAll('[data-vdel]').forEach(b=>b.onclick=()=>{formState.vehicles=veh.filter((_,i)=>i!==+b.dataset.vdel);renderFormTab();});
    scroll.querySelectorAll('[data-crew]').forEach(b=>b.onclick=()=>{const p=b.dataset.crew;formState.crew=crew.includes(p)?crew.filter(x=>x!==p):[...crew,p];renderFormTab();});
    $('f-add-person').onclick=()=>{const n=$('f-new-person').value.trim();if(n&&!crew.includes(n)){formState.crew=[...crew,n];renderFormTab();}};
    bind('f-plate','plate');
  }
  if(activeTab==='materials'){
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">📦 Selecciona material necesario</div>
        <div class="mat-grid">
          ${MATERIALS.map(m=>`<button class="mat-tag${(f.materials||[]).includes(m)?' active':''}" data-m="${esc(m)}">${esc(m)}</button>`).join('')}
        </div>
      </div>`;
    scroll.querySelectorAll('[data-m]').forEach(btn=>{
      btn.onclick=()=>{
        const m=btn.dataset.m;
        if(formState.materials.includes(m))formState.materials=formState.materials.filter(x=>x!==m);
        else formState.materials.push(m);
        renderFormTab();
      };
    });
  }
  if(activeTab==='quote'){renderQuoteTab(scroll);return;}
  if(activeTab==='photos'){
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">📷 Fotos del trabajo</div>
        <button class="upload-btn" id="upload-btn-trigger"><span style="font-size:1.4rem">📸</span><span>Añadir fotos</span></button>
        <input type="file" id="photo-file-inp" accept="image/*" multiple style="display:none" />
        ${formPhotos.length===0?'<div class="no-photos">Aún no hay fotos añadidas</div>':''}
        <div style="display:none;flex-direction:column;gap:4px" id="photo-prog">
          <div class="prog-bar"><div class="prog-fill" id="photo-pfill"></div></div>
          <div class="prog-label" id="photo-plabel">Subiendo…</div>
        </div>
        <div class="photo-grid" id="photo-grid">
          ${formPhotos.map((p,i)=>`<div class="photo-wrap"><img class="photo-thumb" src="${p.url||p.localSrc}" onclick="openLb('${p.url||p.localSrc}')" loading="lazy" /><button class="photo-remove" data-i="${i}">✕</button></div>`).join('')}
        </div>
      </div>`;
    $('upload-btn-trigger').onclick=()=>$('photo-file-inp').click();
    $('photo-file-inp').onchange=e=>{Array.from(e.target.files).forEach(uploadFormPhoto);e.target.value='';};
    scroll.querySelectorAll('[data-i]').forEach(btn=>{
      btn.onclick=async()=>{
        const i=Number(btn.dataset.i),p=formPhotos[i];formPhotos.splice(i,1);
        if(p.storagePath){try{await deleteObject(sRef(storage,p.storagePath));}catch(e){}}
        renderFormTab();
      };
    });
  }
}

async function uploadFormPhoto(file){
  if(!file.type.startsWith('image/'))return;
  if(file.size>50*1024*1024){toast('Foto > 50 MB','err');return;}
  const prog=$('photo-prog');if(prog)prog.style.display='flex';
  const path=`trabajos/${auth.currentUser.uid}/${Date.now()}_${file.name}`;
  const task=uploadBytesResumable(sRef(storage,path),file);
  try{
    const url=await new Promise((res,rej)=>task.on('state_changed',
      s=>{const p=Math.round(s.bytesTransferred/s.totalBytes*100);
          const pf=$('photo-pfill');if(pf)pf.style.width=p+'%';
          const pl=$('photo-plabel');if(pl)pl.textContent=`Subiendo… ${p}%`;},
      rej,async()=>res(await getDownloadURL(task.snapshot.ref))
    ));
    formPhotos.push({url,storagePath:path});renderFormTab();toast('Foto añadida ✓','ok');
  }catch(e){toast('Error subiendo foto','err');}
  finally{const prog=$('photo-prog');if(prog)prog.style.display='none';}
}

function collectFormState(){
  const get=(id,key)=>{const el=$(id);if(el)formState[key]=el.value;};
  get('f-client','clientName');get('f-phone','phone');get('f-email','email');get('f-location','location');
  get('f-price','price');get('f-start','startTime');get('f-end','endTime');get('f-date','date');
  get('f-oa','originAddress');get('f-of','originFloor');
  get('f-da','destinAddress');get('f-df','destinFloor');
  get('f-notes','notes');get('f-plate','plate');
  const fd=$('f-days');if(fd)formState.days=Math.min(31,Math.max(1,parseInt(fd.value)||1));
  const fp=$('f-payment');if(fp)formState.payment=fp.value;
}

$('btn-form-cancel').onclick=()=>isEditing?showView('detail'):showView(formState.date?'day':'solicitudes');
$('btn-save-job').addEventListener('click',async()=>{
  collectFormState();
  if(!formState.clientName){toast('Añade el nombre del cliente','err');return;}
  if(formState.date&&!/^\d{4}-\d{2}-\d{2}$/.test(formState.date)){toast('La fecha no es válida','err');return;}
  // Con fecha → programado (calendario). Sin fecha → se queda en Solicitudes.
  if(formState.date)formState.stage='programado';
  else if(!formState.stage||formState.stage==='programado')formState.stage='solicitud';
  $('btn-save-job').innerHTML='<span class="spin"></span>';
  $('btn-save-job').disabled=true;
  const {id,_day,_ofDays,...clean}=formState;
  const data={...clean,days:jobDays(clean),photos:formPhotos,updatedBy:auth.currentUser.email,updatedAt:serverTimestamp()};
  // Los campos antiguos se sustituyen por los nuevos cuando se rellenan
  if(data.crew.length)data.team='';
  if(data.vehicles.length)data.vehicle='';
  try{
    if(isEditing&&curJob){
      if(data.stage!==jobStage(curJob)&&STAGE_AT[data.stage])data[STAGE_AT[data.stage]]=serverTimestamp();
      await setDoc(doc(db,'trabajos',curJob.id),data,{merge:true});
      curJob={...curJob,...data};toast('✅ Trabajo actualizado','ok');
      renderDetailView();showView('detail');
    }else{
      data.createdBy=auth.currentUser.email;data.createdAt=serverTimestamp();
      if(data.stage==='presupuestado')data.quotedAt=serverTimestamp();
      await addDoc(collection(db,'trabajos'),data);
      if(data.date){toast('✅ Trabajo creado','ok');selDate=data.date;renderDayView();showView('day');}
      else{toast('✅ Solicitud guardada','ok');showView('solicitudes');}
    }
  }catch(e){toast('Error: '+e.message,'err');}
  finally{$('btn-save-job').textContent='Guardar';$('btn-save-job').disabled=false;}
});

// ════════════════════════════════════════
//  TARIFAS
// ════════════════════════════════════════
async function loadTarifas(){
  try{
    const snap=await getDoc(doc(db,'config','tarifas'));
    if(snap.exists())tarifas={...tarifas,...snap.data()};
  }catch(e){}
}

function renderTarifas(){
  const cont=$('tarifas-content');
  const row=(label,id,val,unit,step='0.5')=>`
      <div class="tarifa-row">
        <span class="tarifa-label">${label}</span>
        <div class="tarifa-input-wrap">
          <input class="tarifa-input" type="number" min="0" step="${step}" data-key="${id}" value="${fmt(val)}" />
          <span class="tarifa-unit">${unit}</span>
        </div>
      </div>`;
  cont.innerHTML=`
    <div class="tarifa-section">
      <div class="tarifa-section-title">👷 Personal</div>
      ${row('Trabajador por hora (incluye viaje)','workerHour',tarifas.workerHour,'€/h')}
      ${row(`Socio por hora (${PARTNERS.join(' y ')})`,'partnerHour',tarifas.partnerHour,'€/h')}
    </div>
    <div class="tarifa-section">
      <div class="tarifa-section-title">💶 Cómo se calcula el precio</div>
      ${row('Beneficio para el negocio','businessPct',tarifas.businessPct,'%','1')}
      ${row('Redondear el precio hacia arriba a','roundTo',tarifas.roundTo,'€','1')}
      <div class="notes-text" style="color:var(--muted)">Precio = coste (vehículos + km + trabajadores + socios + material + gasoil + otros) + ${fmt(tarifas.businessPct)} %.</div>
    </div>
    <div class="tarifa-section">
      <div class="tarifa-section-title">🚛 Alquiler de vehículos (por día, sin IVA)</div>
      ${row('Furgoneta · 200 km','rent_furgoneta_200',tarifas.rent_furgoneta_200,'€/día')}
      ${row('Furgoneta · 400 km','rent_furgoneta_400',tarifas.rent_furgoneta_400,'€/día')}
      ${row('Camión · 200 km','rent_camion_200',tarifas.rent_camion_200,'€/día')}
      ${row('Camión · 400 km','rent_camion_400',tarifas.rent_camion_400,'€/día')}
      ${row('Km extra','extraKm',tarifas.extraKm,'€/km','0.01')}
    </div>
    <div class="tarifa-section">
      <div class="tarifa-section-title">⛽ Gasoil</div>
      ${row('Precio del gasoil','fuelPrice',tarifas.fuelPrice,'€/L','0.01')}
      ${row('Consumo Crafter (furgoneta)','consumo_crafter',tarifas.consumo_crafter,'L/100 km','0.1')}
      ${row('Consumo Iveco (camión)','consumo_iveco',tarifas.consumo_iveco,'L/100 km','0.1')}
      <div class="notes-text" style="color:var(--muted)">Con los km de cada vehículo se calcula el gasoil del presupuesto y del cierre (p. ej. 150 km en el Iveco = ${fmt(Math.round(150*Number(tarifas.consumo_iveco||0)/100*Number(tarifas.fuelPrice||0)*100)/100)} €). Si pones un importe a mano, manda ese.</div>
    </div>
    <div class="tarifa-section">
      <div class="tarifa-section-title">📦 Material que se gasta (precio por unidad)</div>
      ${MATERIALS.filter(m=>!REUSABLE.includes(m)).map(m=>row(esc(m),m,tarifas[m]||0,'€/ud','0.1')).join('')}
      <div class="notes-text" style="color:var(--muted)">Mantas, fajas, traspaleta, escalera y carretilla se reutilizan y no cuentan como gasto.</div>
    </div>
    <div class="tarifa-section">
      <div class="tarifa-section-title">💬 Mensaje del presupuesto (WhatsApp)</div>
      <div class="fi"><textarea id="t-quote-msg" rows="10" style="width:100%;font-family:inherit">${esc(tarifas.quoteMsg||DEFAULT_QUOTE_MSG)}</textarea></div>
      <div class="notes-text" style="color:var(--muted)">Se rellena solo con: <code>{nombre}</code> <code>{saludo}</code> <code>{servicio}</code> <code>{origen}</code> <code>{destino}</code> <code>{fecha}</code> <code>{m3}</code> <code>{precio}</code> <code>{incluye}</code> <code>{vehiculos}</code> <code>{personas}</code>. Si falta un dato, su línea no sale. <button class="link-btn" id="t-quote-reset">Volver al de por defecto</button></div>
    </div>
    <div class="tarifa-section">
      <div class="tarifa-section-title">⭐ Reseñas</div>
      <div class="fi"><label>Enlace para dejar reseña en Google</label><input id="t-review" type="url" placeholder="https://g.page/r/…/review" value="${esc(tarifas.reviewUrl||'')}" /></div>
      <div class="notes-text" style="color:var(--muted)">Se añade al mensaje de WhatsApp «Pedir reseña».</div>
    </div>
    <button class="save-tarifas-btn" id="btn-save-tarifas">Guardar tarifas</button>`;

  $('t-quote-reset').onclick=()=>{$('t-quote-msg').value=DEFAULT_QUOTE_MSG;};
  $('btn-save-tarifas').addEventListener('click',async()=>{
    cont.querySelectorAll('[data-key]').forEach(inp=>{tarifas[inp.dataset.key]=Number(inp.value||0);});
    tarifas.reviewUrl=$('t-review').value.trim();
    const qm=$('t-quote-msg').value.trim();tarifas.quoteMsg=qm===DEFAULT_QUOTE_MSG.trim()?'':qm;
    $('btn-save-tarifas').innerHTML='<span class="spin"></span>';
    $('btn-save-tarifas').disabled=true;
    try{
      await setDoc(doc(db,'config','tarifas'),{...tarifas,updatedAt:serverTimestamp()});
      toast('✅ Tarifas guardadas','ok');
    }catch(e){toast('Error guardando','err');}
    finally{$('btn-save-tarifas').textContent='Guardar tarifas';$('btn-save-tarifas').disabled=false;}
  });
}

// ════════════════════════════════════════
//  FINANZAS
// ════════════════════════════════════════
let finExpenseType='expense';
let finSelYear=new Date().getFullYear();
let finSelMonth=new Date().getMonth(); // 0-based

function subscribeFinanzas(){
  if(finUnsub)finUnsub();
  const q=query(collection(db,'finanzas'),orderBy('createdAt','desc'));
  finUnsub=onSnapshot(q,snap=>{
    finEntries=[];
    snap.forEach(d=>finEntries.push({id:d.id,...d.data()}));
    if(curView==='finanzas')renderFinanzas();
  });
}

function renderFinanzas(){
  const cont=$('finanzas-content');

  // Filter entries for selected month
  const monthKey=`${finSelYear}-${pad(finSelMonth+1)}`;
  const monthEntries=finEntries.filter(e=>(e.date||'').startsWith(monthKey));

  const totalIncome=monthEntries.filter(e=>e.type==='income').reduce((s,e)=>s+Number(e.amount||0),0);
  const totalExpense=monthEntries.filter(e=>e.type==='expense').reduce((s,e)=>s+Number(e.amount||0),0);
  const balance=totalIncome-totalExpense;
  const balClass=balance>=0?'balance-pos':'balance-neg';

  const globalIncome=finEntries.filter(e=>e.type==='income').reduce((s,e)=>s+Number(e.amount||0),0);
  const globalExpense=finEntries.filter(e=>e.type==='expense').reduce((s,e)=>s+Number(e.amount||0),0);
  const globalBalance=globalIncome-globalExpense;
  const globalBalClass=globalBalance>=0?'balance-pos':'balance-neg';

  const now=new Date();
  const isCurrentMonth=finSelYear===now.getFullYear()&&finSelMonth===now.getMonth();

  cont.innerHTML=`
    <div class="balance-card">
      <div class="balance-label">Balance total empresa</div>
      <div class="balance-amount ${globalBalClass}">${globalBalance>=0?'+':''}${fmt(globalBalance)} €</div>
      <div class="balance-sub">Acumulado desde el inicio</div>
    </div>
    <div class="fin-month-nav">
      <button class="cal-nav-btn" id="fin-prev">‹</button>
      <div class="cal-month-title">${MONTHS_ES[finSelMonth]} ${finSelYear}</div>
      <button class="cal-nav-btn" id="fin-next" ${isCurrentMonth?'disabled style="opacity:.3;pointer-events:none"':''}>›</button>
    </div>
    <div class="balance-card">
      <div class="balance-label">Balance mensual</div>
      <div class="balance-amount ${balClass}">${balance>=0?'+':''}${fmt(balance)} €</div>
      <div class="balance-sub">Ingresos y gastos de ${MONTHS_ES[finSelMonth]}</div>
    </div>
    <div class="fin-stats">
      <div class="fin-stat">
        <div class="fin-stat-label">Ingresos</div>
        <div class="fin-stat-val" style="color:var(--green)">+${fmt(totalIncome)} €</div>
      </div>
      <div class="fin-stat">
        <div class="fin-stat-label">Gastos</div>
        <div class="fin-stat-val" style="color:var(--danger)">-${fmt(totalExpense)} €</div>
      </div>
    </div>

    <div class="fin-section-title">➕ Registrar entrada/gasto</div>
    <div class="add-expense-form">
      <div class="expense-type-row">
        <button class="expense-type-btn${finExpenseType==='income'?' active-income':''}" data-t="income">📈 Ingreso</button>
        <button class="expense-type-btn${finExpenseType==='expense'?' active-expense':''}" data-t="expense">📉 Gasto</button>
      </div>
      <div class="fi"><label>Descripción</label><input type="text" id="fin-desc" placeholder="Ej: Compra taladro, Trabajo extra…" /></div>
      <div class="fi"><label>Importe (€)</label><input type="number" id="fin-amount" min="0" step="0.01" placeholder="0.00" /></div>
      <div class="fi"><label>Fecha</label><input type="date" id="fin-date" value="${todayStr()}" /></div>
      <button class="btn btn-accent" id="btn-add-fin-entry" style="width:100%;padding:12px;font-size:.9rem">Añadir</button>
    </div>

    <div class="fin-section-title">📋 Movimientos</div>
    <div class="fin-entries" id="fin-entries-list">
      ${monthEntries.length===0?'<div class="empty-state">Sin movimientos en este mes.</div>':''}
      ${monthEntries.map(e=>{
        const isInc=e.type==='income';
        const color=isInc?'var(--green)':'var(--danger)';
        const sign=isInc?'+':'-';
        const icon=isInc?'📈':'📉';
        const dateStr=e.date||'—';
        return `<div class="fin-entry">
          <span class="fin-entry-icon">${icon}</span>
          <div class="fin-entry-body">
            <div class="fin-entry-desc">${esc(e.description||'Sin descripción')}</div>
            <div class="fin-entry-date">${dateStr}</div>
          </div>
          <div class="fin-entry-amount" style="color:${color}">${sign}${fmt(e.amount)} €</div>
          <button class="fin-entry-del" data-fid="${e.id}">🗑</button>
        </div>`;
      }).join('')}
    </div>`;

  // month navigation
  $('fin-prev').onclick=()=>{
    finSelMonth--;
    if(finSelMonth<0){finSelMonth=11;finSelYear--;}
    renderFinanzas();
  };
  if($('fin-next'))$('fin-next').onclick=()=>{
    finSelMonth++;
    if(finSelMonth>11){finSelMonth=0;finSelYear++;}
    renderFinanzas();
  };

  // type toggle
  cont.querySelectorAll('[data-t]').forEach(btn=>{
    btn.onclick=()=>{finExpenseType=btn.dataset.t;renderFinanzas();};
  });

  // add entry
  $('btn-add-fin-entry').addEventListener('click',async()=>{
    const desc=$('fin-desc').value.trim();
    const amount=Number($('fin-amount').value||0);
    const date=$('fin-date').value;
    if(!desc){toast('Añade una descripción','err');return;}
    if(!amount){toast('Añade un importe','err');return;}
    $('btn-add-fin-entry').innerHTML='<span class="spin"></span>';
    $('btn-add-fin-entry').disabled=true;
    try{
      await addDoc(collection(db,'finanzas'),{
        type:finExpenseType,amount,description:desc,date,
        createdBy:auth.currentUser.email,createdAt:serverTimestamp()
      });
      toast('✅ Entrada registrada','ok');
    }catch(e){toast('Error: '+e.message,'err');}
    finally{$('btn-add-fin-entry').textContent='Añadir';$('btn-add-fin-entry').disabled=false;}
  });

  // delete entries
  cont.querySelectorAll('[data-fid]').forEach(btn=>{
    btn.onclick=async()=>{
      if(!confirm('¿Eliminar este movimiento?'))return;
      try{await deleteDoc(doc(db,'finanzas',btn.dataset.fid));toast('Eliminado');}
      catch(e){toast('Error','err');}
    };
  });
}

// ════════════════════════════════════════
//  LIGHTBOX
// ════════════════════════════════════════
window.openLb=url=>{$('lb-img').src=url;$('lb').classList.add('open');};
$('lb-x').onclick=()=>$('lb').classList.remove('open');
$('lb').onclick=e=>{if(e.target===$('lb'))$('lb').classList.remove('open');};

// ════════════════════════════════════════
//  NOTIFICATIONS
// ════════════════════════════════════════
async function initNotifs(){
  if(!messaging||!('serviceWorker' in navigator))return;
  if(Notification.permission==='default')$('notif-banner').style.display='flex';
  if(Notification.permission==='granted')await subFCM();
  $('btn-notif').onclick=async()=>{
    const r=await Notification.requestPermission();
    if(r==='granted'){$('notif-banner').style.display='none';await subFCM();toast('✅ Notificaciones activadas','ok');}
    else toast('Permiso denegado','err');
  };
  onMessage(messaging,p=>{const{title,body}=p.notification||p.data||{};toast(`🔔 ${title}: ${body}`);});
}
async function subFCM(){
  try{
    const sw=await navigator.serviceWorker.ready;
    const token=await getToken(messaging,{vapidKey:VAPID_KEY,serviceWorkerRegistration:sw});
    if(token)await addDoc(collection(db,'fcm_tokens'),{uid:auth.currentUser.uid,token,updatedAt:serverTimestamp()});
  }catch(e){console.warn('FCM:',e);}
}


// ════════════════════════════════════════
//  PRESUPUESTOS
// ════════════════════════════════════════

// ✏️ PON AQUÍ LA URL DE TU CLOUD FUNCTION después del deploy
const CLOUD_FUNCTION_URL = "https://generar-presupuesto-4te7g5uzqa-ew.a.run.app";

// Empresa fija (igual que en el PDF)
const EMPRESA_DATA = {
  nombre:    "Mudanzas del Sur",
  direccion: "Poligono Romeralejo, 5",
  ciudad:    "Huelva",
  telefono:  "659715271",
  email:     "contactomudanzasdelsur@gmail.com"
};

let presLineas = [
  {descripcion:'', total:''},
  {descripcion:'', total:''},
  {descripcion:'', total:''},
];
let presUsaIva = true;
let presIvaPct = 21;
let presUnsub;

function renderPresupuestos(){
  const cont = $('pres-content');

  // Warning si URL no configurada
  const urlWarning = CLOUD_FUNCTION_URL.includes('TU_PROJECT_ID')
    ? `<div class="url-warning">⚠️ Configura <strong>CLOUD_FUNCTION_URL</strong> en el código con la URL de tu Cloud Function tras el deploy. Ver DESPLIEGUE.md</div>`
    : '';

  cont.innerHTML = urlWarning + `
    <div class="pres-section">
      <div class="pres-section-title">👤 Datos del cliente</div>
      <div class="fi"><label>Nombre completo cliente 1</label><input id="p-cli1-nombre" placeholder="NOMBRE COMPLETO" /></div>
      <div class="fi"><label>NIF / DNI cliente 1</label><input id="p-cli1-nif" placeholder="00000000X" /></div>
      <div class="fi"><label>Nombre completo cliente 2 (opcional)</label><input id="p-cli2-nombre" placeholder="NOMBRE COMPLETO (opcional)" /></div>
      <div class="fi"><label>NIF / DNI cliente 2</label><input id="p-cli2-nif" placeholder="00000000X" /></div>
    </div>

    <div class="pres-section">
      <div class="pres-section-title">📍 Origen y destino</div>
      <div class="fi"><label>Dirección de origen</label><input id="p-origen" placeholder="C/ Nombre, Nº, Piso, Ciudad" /></div>
      <div class="fi"><label>Dirección de destino</label><input id="p-destino" placeholder="C/ Nombre, Nº, Piso, Ciudad" /></div>
    </div>

    <div class="pres-section">
      <div class="pres-section-title">📋 Líneas del presupuesto</div>
      <div style="display:flex;justify-content:space-between;padding:0 2px">
        <span style="font-size:.68rem;color:var(--muted);font-weight:700">DESCRIPCIÓN</span>
        <span style="font-size:.68rem;color:var(--muted);font-weight:700">TOTAL (€)</span>
      </div>
      <div class="pres-lineas" id="pres-lineas"></div>
      <button class="btn-add-linea" id="btn-add-linea">+ Añadir línea</button>
    </div>

    <div class="pres-section">
      <div class="pres-section-title">🧾 IVA</div>
      <div class="pres-iva-row">
        <span style="font-size:.85rem">Aplicar IVA al presupuesto</span>
        <div class="pres-iva-toggle">
          <button class="iva-btn${presUsaIva ? ' active-si':''}" id="iva-si">Sí (21%)</button>
          <button class="iva-btn${!presUsaIva ? ' active-no':''}" id="iva-no">No</button>
        </div>
      </div>
    </div>

    <div class="pres-section">
      <div class="pres-section-title">📝 Observaciones</div>
      <div class="fi">
        <textarea id="p-obs" rows="4" placeholder="Condiciones, notas adicionales…">El precio puede variar si el volumen final excede lo estimado.
Los embalajes especiales (piano, obras de arte, electrodomésticos de gran tamaño) se presupuestan aparte.
El cliente debe indicar restricciones de acceso (calles estrechas, permisos de estacionamiento).</textarea>
      </div>
    </div>

    <div class="pres-preview" id="pres-preview">
      <div class="pres-preview-row"><span style="color:var(--muted)">Subtotal</span><span>0,00 €</span></div>
    </div>

    <button class="btn-gen-pdf" id="btn-gen-pdf">
      <span style="font-size:1.2rem">📄</span> Generar PDF
    </button>

    <div class="fin-section-title" style="margin-top:4px">📋 Presupuestos generados</div>
    <div id="pres-historial"><div class="empty-state">Aún no hay presupuestos.</div></div>
  `;

  // Render lines
  renderPresLineas();

  // IVA toggle
  $('iva-si').onclick = () => { presUsaIva=true;  renderPresupuestos(); };
  $('iva-no').onclick = () => { presUsaIva=false; renderPresupuestos(); };

  // Add line
  $('btn-add-linea').onclick = () => {
    presLineas.push({descripcion:'', total:''});
    renderPresLineas();
    updatePresPreview();
  };

  // Generate PDF
  $('btn-gen-pdf').addEventListener('click', generarPresupuestoPDF);

  // Subscribe historial
  subscribePresupuestos();
  updatePresPreview();
}

function renderPresLineas(){
  const cont = $('pres-lineas');
  if(!cont) return;
  cont.innerHTML = presLineas.map((l,i) => `
    <div class="pres-linea-row">
      <input class="pres-linea-desc" type="text" placeholder="Descripción del concepto…"
             value="${esc(l.descripcion)}" data-li="${i}" data-field="descripcion" />
      <input class="pres-linea-total" type="text" placeholder="0,00"
             value="${esc(l.total)}" data-li="${i}" data-field="total" />
      <button class="pres-linea-del" data-li="${i}">🗑</button>
    </div>`).join('');

  cont.querySelectorAll('.pres-linea-desc,.pres-linea-total').forEach(inp => {
    inp.oninput = () => {
      presLineas[Number(inp.dataset.li)][inp.dataset.field] = inp.value;
      updatePresPreview();
    };
  });
  cont.querySelectorAll('.pres-linea-del').forEach(btn => {
    btn.onclick = () => {
      presLineas.splice(Number(btn.dataset.li), 1);
      renderPresLineas();
      updatePresPreview();
    };
  });
}

function updatePresPreview(){
  const preview = $('pres-preview');
  if(!preview) return;
  let subtotal = 0;
  presLineas.forEach(l => {
    const n = parseFloat((l.total||'0').replace(',','.'));
    if(!isNaN(n)) subtotal += n;
  });
  const iva    = presUsaIva ? Math.round(subtotal * presIvaPct) / 100 : 0;
  const total  = subtotal + iva;
  const fmtE   = n => n.toFixed(2).replace('.',',') + ' €';
  preview.innerHTML = `
    <div class="pres-preview-row"><span style="color:var(--muted)">Subtotal</span><span>${fmtE(subtotal)}</span></div>
    ${presUsaIva ? `<div class="pres-preview-row"><span style="color:var(--muted)">IVA (${presIvaPct}%)</span><span>${fmtE(iva)}</span></div>` : ''}
    <div class="pres-preview-row total-row"><span>Cotización total</span><span style="color:var(--accent)">${fmtE(total)}</span></div>`;
}

async function generarPresupuestoPDF(){
  if(CLOUD_FUNCTION_URL.includes('TU_PROJECT_ID')){
    toast('Configura CLOUD_FUNCTION_URL primero','err'); return;
  }

  // Collect data
  const cli1nombre = $('p-cli1-nombre')?.value.trim() || '';
  const cli1nif    = $('p-cli1-nif')?.value.trim() || '';
  const cli2nombre = $('p-cli2-nombre')?.value.trim() || '';
  const cli2nif    = $('p-cli2-nif')?.value.trim() || '';
  const origen     = $('p-origen')?.value.trim() || '';
  const destino    = $('p-destino')?.value.trim() || '';
  const obsRaw     = $('p-obs')?.value.trim() || '';

  if(!cli1nombre){ toast('Añade el nombre del cliente','err'); return; }
  if(!origen || !destino){ toast('Añade origen y destino','err'); return; }

  let subtotal = 0;
  const lineasFinal = presLineas.filter(l => l.descripcion.trim());
  lineasFinal.forEach(l => {
    const n = parseFloat((l.total||'0').replace(',','.'));
    if(!isNaN(n)) subtotal += n;
  });

  const clientes = [{ nombre: cli1nombre, nif: cli1nif }];
  if(cli2nombre) clientes.push({ nombre: cli2nombre, nif: cli2nif });

  const today = new Date();
  const fecha = `${String(today.getDate()).padStart(2,'0')}/${String(today.getMonth()+1).padStart(2,'0')}/${today.getFullYear()}`;

  const data = {
    empresa:  EMPRESA_DATA,
    fecha,
    clientes,
    origen,
    destino,
    lineas:   lineasFinal,
    subtotal: Math.round(subtotal * 100) / 100,
    usar_iva: presUsaIva,
    iva_pct:  presIvaPct,
    observaciones: obsRaw.split('\n').filter(l => l.trim())
  };

  const btn = $('btn-gen-pdf');
  btn.innerHTML = '<span class="spin"></span> Generando…';
  btn.disabled = true;

  try {
    const idToken = await auth.currentUser.getIdToken();
    const res = await fetch(CLOUD_FUNCTION_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
      body: JSON.stringify({
        data,
        uid: auth.currentUser.uid,
        guardar: true
      })
    });

    const result = await res.json();
    if(result.error) throw new Error(result.error);

    // Open PDF in new tab
    window.open(result.url, '_blank');
    toast('✅ PDF generado correctamente','ok');

  } catch(e) {
    toast('Error: ' + e.message, 'err');
  } finally {
    btn.innerHTML = '<span style="font-size:1.2rem">📄</span> Generar PDF';
    btn.disabled = false;
  }
}

function subscribePresupuestos(){
  if(presUnsub) presUnsub();
  const q = query(collection(db,'presupuestos'), orderBy('creadoEn','desc'));
  presUnsub = onSnapshot(q, snap => {
    const hist = $('pres-historial');
    if(!hist) return;
    if(snap.empty){ hist.innerHTML='<div class="empty-state">Aún no hay presupuestos generados.</div>'; return; }
    hist.innerHTML = '';
    snap.forEach(d => {
      const p = d.data();
      const fmtTotal = n => Number(n||0).toFixed(2).replace('.',',') + ' €';
      const item = document.createElement('div');
      item.className = 'pres-hist-item';
      item.innerHTML = `
        <span style="font-size:1.3rem">📄</span>
        <div class="pres-hist-body">
          <div class="pres-hist-client">${esc(p.cliente||'Sin nombre')}</div>
          <div class="pres-hist-sub">📅 ${p.fecha||'—'} · ${esc(p.origen||'')} → ${esc(p.destino||'')}</div>
        </div>
        <div class="pres-hist-total">${fmtTotal(p.total)}</div>`;
      item.onclick = () => { if(p.pdfUrl) window.open(p.pdfUrl,'_blank'); };
      hist.appendChild(item);
    });
  });
}

// ════════════════════════════════════════
//  BOOT
// ════════════════════════════════════════
function checkLayout(){
  if(window.innerWidth>=768){
    document.body.classList.add('desktop');
  }else{
    document.body.classList.remove('desktop');
  }
}

async function boot(){
  await loadTarifas();
  initCal();
  subscribeFinanzas();
  subscribePipeline();
  initNotifs();
  checkLayout();
  window.addEventListener('resize', checkLayout);
  if('serviceWorker' in navigator)
    navigator.serviceWorker.register('firebase-messaging-sw.js').catch(()=>{});
}
