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
const VEHICLES  = ["Furgoneta pequeña","Furgoneta grande","Camión 3.5T","Camión 7.5T","Camión 12T","Camión articulado"];
const MATERIALS = ["Cajas pequeñas","Cajas grandes","Papel burbuja","Papel de embalaje","Cinta adhesiva",
                   "Mantas de protección","Fajas de carga","Traspaleta","Escalera","Carretilla","Plástico film","Esquineros"];
const WORKERS_PRESET = ["Trabajador 1","Trabajador 2","Trabajador 3","Trabajador 4"];
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
  }
});

// ── STATE ──
let calYear,calMonth,selDate,jobsCache={};
let curView='cal',curJob=null,isEditing=false,activeTab='info',formState={},formPhotos=[];
let tarifas={workerHour:15,...Object.fromEntries(MATERIALS.map(m=>[m,0]))};
let finEntries=[]; // loaded from Firestore

// ════════════════════════════════════════
//  VIEW ROUTER + BOTTOM NAV
// ════════════════════════════════════════
function showView(name){
  curView=name;
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  $('view-'+name).classList.add('active');
  const hasGlobalHeader=['cal','tarifas','finanzas'].includes(name);
  $('g-header').style.display=hasGlobalHeader?'flex':'none';
  $('bottom-nav').style.display=hasGlobalHeader?'flex':'none';
  // sync nav
  document.querySelectorAll('.nav-btn').forEach(b=>{
    b.classList.toggle('active',b.dataset.view===name);
  });
  if(name==='tarifas') renderTarifas();
  if(name==='finanzas') renderFinanzas();
  if(name==='presupuestos') renderPresupuestos();
}

document.querySelectorAll('.nav-btn').forEach(btn=>{
  btn.addEventListener('click',()=>showView(btn.dataset.view));
});

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
      html+=`<div class="job-pill" style="background:${statusColor(j.status)}"><span class="pill-time">${j.startTime||''}</span><span class="pill-name">${esc(j.clientName||'Trabajo')}</span></div>`;
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
  const q=query(collection(db,'trabajos'),where('date','>=',start),where('date','<=',end));
  jobsUnsub=onSnapshot(q,snap=>{
    jobsCache={};
    snap.forEach(d=>{const data=d.data();if(!jobsCache[data.date])jobsCache[data.date]=[];jobsCache[data.date].push({id:d.id,...data});});
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
    $('btn-day-add').onclick=openNewJob;return;
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
        <div class="job-time-row">⏰ ${job.startTime||'--:--'} – ${job.endTime||'--:--'}</div>
        ${job.vehicle?`<div class="job-detail-row">🚛 ${esc(job.vehicle)}</div>`:''}
        ${job.originAddress?`<div class="job-detail-row">📍 ${esc(job.originAddress)} → ${esc(job.destinAddress||'')}</div>`:''}
        ${(job.photos||[]).length?`<div class="job-detail-row">📷 ${job.photos.length} foto${job.photos.length!==1?'s':''}</div>`:''}
      </div>
      <div class="job-card-arrow">›</div>`;
    card.onclick=()=>openJobDetail(job);
    cont.appendChild(card);
  });
}

$('btn-back-cal').onclick=()=>showView('cal');
$('btn-new-job').onclick=openNewJob;

// ════════════════════════════════════════
//  JOB DETAIL
// ════════════════════════════════════════
function openJobDetail(job){curJob=job;formState={...job};formPhotos=[...(job.photos||[])];renderDetailView();showView('detail');}

function renderDetailView(){
  const job=curJob;
  const sc=statusColor(job.status);
  const cont=$('detail-content');
  const initial=(job.clientName||'?')[0].toUpperCase();
  const isCompleted=job.status==='completado';

  let profitSection='';
  if(isCompleted&&job.profit!=null){
    const pColor=job.profit>=0?'var(--green)':'var(--danger)';
    profitSection=`<div class="detail-section">
      <div class="detail-section-title">💰 Resultado económico</div>
      <div class="detail-row"><span>Presupuesto</span><strong>${fmt(job.price)} €</strong></div>
      <div class="detail-row"><span>Coste materiales</span><strong>${fmt(job.closingData?.totalMaterials)} €</strong></div>
      <div class="detail-row"><span>Coste mano de obra</span><strong>${fmt(job.closingData?.totalLabor)} €</strong></div>
      <div class="detail-row"><span>Gasolina</span><strong>${fmt(job.closingData?.fuel)} €</strong></div>
      <div class="detail-row"><span>Gastos extra</span><strong>${fmt(job.closingData?.extras)} €</strong></div>
      <div class="detail-row" style="margin-top:4px;padding-top:8px;border-top:1px solid var(--border)">
        <span style="font-weight:800">Beneficio</span>
        <strong style="color:${pColor};font-size:1.05rem">${job.profit>=0?'+':''}${fmt(job.profit)} €</strong>
      </div>
    </div>`;
  }

  cont.innerHTML=`
    <div class="detail-card">
      <div class="detail-client-row">
        <div class="detail-avatar">${initial}</div>
        <div>
          <div class="detail-client-name">${esc(job.clientName||'Sin nombre')}</div>
          <div class="detail-phone">${esc(job.phone||'')}</div>
        </div>
        <div class="status-badge" style="margin-left:auto;background:${sc}22;color:${sc}">${statusLabel(job.status)}</div>
      </div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">⏰ Horario</div>
      <div class="detail-row"><span>Inicio</span><strong>${esc(job.startTime||'—')}</strong></div>
      <div class="detail-row"><span>Fin aprox.</span><strong>${esc(job.endTime||'—')}</strong></div>
      ${job.price?`<div class="detail-row"><span>Presupuesto</span><strong>${fmt(job.price)} €</strong></div>`:''}
      ${job.payment?`<div class="detail-row"><span>Pago</span><strong>${esc(job.payment)}</strong></div>`:''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">🚛 Vehículo y equipo</div>
      <div class="detail-row"><span>Vehículo</span><strong>${esc(job.vehicle||'—')}</strong></div>
      <div class="detail-row"><span>Equipo</span><strong>${esc(job.team||'—')}</strong></div>
      ${job.plate?`<div class="detail-row"><span>Matrícula</span><strong>${esc(job.plate)}</strong></div>`:''}
    </div>
    <div class="detail-section">
      <div class="detail-section-title">📍 Origen</div>
      <div class="detail-row"><span>Dirección</span><strong>${esc(job.originAddress||'—')}</strong></div>
      <div class="detail-row"><span>Piso / Puerta</span><strong>${esc(job.originFloor||'—')}</strong></div>
      <div class="detail-row"><span>Ascensor</span><strong>${job.originElevator?'Sí':'No'}</strong></div>
    </div>
    <div class="detail-section">
      <div class="detail-section-title">🏠 Destino</div>
      <div class="detail-row"><span>Dirección</span><strong>${esc(job.destinAddress||'—')}</strong></div>
      <div class="detail-row"><span>Piso / Puerta</span><strong>${esc(job.destinFloor||'—')}</strong></div>
      <div class="detail-row"><span>Ascensor</span><strong>${job.destinElevator?'Sí':'No'}</strong></div>
    </div>
    ${(job.materials||[]).length?`<div class="detail-section"><div class="detail-section-title">📦 Material planificado</div><div class="mat-tags-row">${job.materials.map(m=>`<span class="mat-tag active">${esc(m)}</span>`).join('')}</div></div>`:''}
    ${job.notes?`<div class="detail-section"><div class="detail-section-title">📝 Notas</div><div class="notes-text">${esc(job.notes)}</div></div>`:''}
    ${(job.photos||[]).length?`<div class="detail-section"><div class="detail-section-title">📷 Fotos (${job.photos.length})</div><div class="photo-grid">${job.photos.map(p=>`<img class="photo-thumb" src="${p.url||p.localSrc}" loading="lazy" onclick="openLb('${p.url||p.localSrc}')" />`).join('')}</div></div>`:''}
    ${profitSection}
    ${isCompleted
      ? `<div class="completed-badge">✅ Trabajo completado y cerrado</div>`
      : `<button class="btn-complete" id="btn-complete-job">✅ Marcar como completado</button>`}
    <button class="btn-danger-outline" id="btn-del-job">🗑 Eliminar trabajo</button>`;

  if(!isCompleted){
    $('btn-complete-job').onclick=()=>openCloseModal();
  }
  $('btn-del-job').onclick=async()=>{
    if(!confirm('¿Eliminar este trabajo?'))return;
    try{await deleteDoc(doc(db,'trabajos',curJob.id));toast('Trabajo eliminado');showView('day');}
    catch(e){toast('Error eliminando','err');}
  };
}

$('btn-back-day').onclick=()=>showView('day');
$('btn-edit-job').onclick=()=>openJobForm(true);

// ════════════════════════════════════════
//  CLOSE MODAL — CIERRE ECONÓMICO
// ════════════════════════════════════════
let closeData = {};

function openCloseModal(){
  const job=curJob;
  closeData={workerHours:{},matQty:{},fuel:0,extras:0};
  const body=$('close-modal-body');

  // Determine number of workers from team string e.g. "Equipo C (3 personas)"
  const crewMatch=(job.team||'').match(/\((\d+)\s*personas?\)/i);
  const crewCount=crewMatch?parseInt(crewMatch[1]):2;
  const workerNames=Array.from({length:crewCount},(_,i)=>`Trabajador ${i+1}`);

  const matsUsed=(job.materials||[]);

  body.innerHTML=`
    <div class="form-section">
      <div class="form-section-title">⏱ Horas trabajadas por operario</div>
      <div class="worker-hours-grid" id="chk-workers">
        ${workerNames.map((w,i)=>`
          <div class="worker-row">
            <span class="worker-label">${esc(w)}</span>
            <input class="worker-input" type="number" min="0" step="0.5" placeholder="0" data-worker="${i}" />
            <span style="font-size:.75rem;color:var(--muted)">h</span>
          </div>`).join('')}
      </div>
    </div>
    ${matsUsed.length?`
    <div class="form-section">
      <div class="form-section-title">📦 Cantidad de material usada</div>
      <div class="mat-qty-grid" id="chk-mats">
        ${matsUsed.map(m=>`
          <div class="mat-qty-row">
            <span class="mat-qty-label">${esc(m)}</span>
            <input class="mat-qty-input" type="number" min="0" step="1" placeholder="0" data-mat="${esc(m)}" />
            <span style="font-size:.75rem;color:var(--muted)">ud</span>
          </div>`).join('')}
      </div>
    </div>`:''}
    <div class="form-section">
      <div class="form-section-title">⛽ Gastos adicionales</div>
      <div class="fi"><label>Gasto en gasolina (€)</label><input type="number" id="chk-fuel" min="0" step="0.5" placeholder="0.00" /></div>
      <div class="fi"><label>Gastos extra (peajes, etc.) (€)</label><input type="number" id="chk-extras" min="0" step="0.5" placeholder="0.00" /></div>
    </div>
    <div class="calc-preview" id="close-calc">
      <div class="calc-row"><span>Cargando cálculo…</span></div>
    </div>`;

  // Attach listeners for live calc
  body.querySelectorAll('.worker-input').forEach(inp=>{
    inp.addEventListener('input',updateCloseCalc);
  });
  body.querySelectorAll('.mat-qty-input').forEach(inp=>{
    inp.addEventListener('input',updateCloseCalc);
  });
  $('chk-fuel').addEventListener('input',updateCloseCalc);
  $('chk-extras').addEventListener('input',updateCloseCalc);

  updateCloseCalc();
  $('close-overlay').classList.add('open');
  document.body.style.overflow='hidden';
}

function updateCloseCalc(){
  const job=curJob;
  const hourRate=Number(tarifas.workerHour||0);

  // Worker hours
  let totalLabor=0;
  document.querySelectorAll('.worker-input').forEach(inp=>{
    const h=Number(inp.value||0);
    totalLabor+=h*hourRate;
    closeData.workerHours[inp.dataset.worker]=h;
  });

  // Material cost
  let totalMats=0;
  document.querySelectorAll('.mat-qty-input').forEach(inp=>{
    const m=inp.dataset.mat,qty=Number(inp.value||0);
    const unitPrice=Number(tarifas[m]||0);
    totalMats+=qty*unitPrice;
    closeData.matQty[m]=qty;
  });

  const fuel=Number($('chk-fuel')?.value||0);
  const extras=Number($('chk-extras')?.value||0);
  closeData.fuel=fuel;closeData.extras=extras;

  const totalCost=totalLabor+totalMats+fuel+extras;
  const budget=Number(job.price||0);
  const profit=budget-totalCost;
  const pClass=profit>=0?'profit-pos':'profit-neg';

  $('close-calc').innerHTML=`
    <div class="calc-row"><span>Presupuesto</span><span>${fmt(budget)} €</span></div>
    <div class="calc-row" style="color:var(--muted)"><span>Mano de obra</span><span>-${fmt(totalLabor)} €</span></div>
    <div class="calc-row" style="color:var(--muted)"><span>Materiales</span><span>-${fmt(totalMats)} €</span></div>
    <div class="calc-row" style="color:var(--muted)"><span>Gasolina</span><span>-${fmt(fuel)} €</span></div>
    <div class="calc-row" style="color:var(--muted)"><span>Gastos extra</span><span>-${fmt(extras)} €</span></div>
    <div class="calc-row total"><span>Total costes</span><span>${fmt(totalCost)} €</span></div>
    <div class="calc-row ${pClass}"><span>💰 Beneficio</span><span>${profit>=0?'+':''}${fmt(profit)} €</span></div>`;
}

function closeCloseModal(){
  $('close-overlay').classList.remove('open');
  document.body.style.overflow='';
}

$('close-modal-x').onclick=closeCloseModal;
$('close-modal-cancel').onclick=closeCloseModal;
$('close-overlay').onclick=e=>{if(e.target===$('close-overlay'))closeCloseModal();};

$('close-modal-save').addEventListener('click',async()=>{
  const job=curJob;
  const hourRate=Number(tarifas.workerHour||0);
  let totalLabor=0;
  document.querySelectorAll('.worker-input').forEach(inp=>{totalLabor+=Number(inp.value||0)*hourRate;});
  let totalMats=0;
  document.querySelectorAll('.mat-qty-input').forEach(inp=>{totalMats+=Number(inp.value||0)*Number(tarifas[inp.dataset.mat]||0);});
  const fuel=Number($('chk-fuel')?.value||0);
  const extras=Number($('chk-extras')?.value||0);
  const totalCost=totalLabor+totalMats+fuel+extras;
  const profit=Number(job.price||0)-totalCost;

  const closingData={workerHours:closeData.workerHours,matQty:closeData.matQty,
    fuel,extras,totalLabor,totalMaterials:totalMats,totalCost};

  $('close-modal-save').innerHTML='<span class="spin"></span>';
  $('close-modal-save').disabled=true;

  try{
    await setDoc(doc(db,'trabajos',job.id),{
      status:'completado',profit,closingData,
      completedBy:auth.currentUser.email,completedAt:serverTimestamp()
    },{merge:true});

    // Add profit as income entry in finanzas
    await addDoc(collection(db,'finanzas'),{
      type:'income',amount:profit,
      description:`Beneficio: ${job.clientName||'Sin nombre'} (${job.date})`,
      date:job.date,jobId:job.id,
      createdBy:auth.currentUser.email,createdAt:serverTimestamp()
    });

    toast('✅ Trabajo cerrado con éxito','ok');
    closeCloseModal();
    // Refresh curJob
    curJob={...curJob,status:'completado',profit,closingData};
    renderDetailView();
  }catch(e){toast('Error: '+e.message,'err');}
  finally{$('close-modal-save').textContent='Confirmar y cerrar';$('close-modal-save').disabled=false;}
});

// ════════════════════════════════════════
//  JOB FORM
// ════════════════════════════════════════
const FORM_TABS=[
  {id:'info',label:'📋 Info'},
  {id:'addresses',label:'📍 Direcciones'},
  {id:'resources',label:'🚛 Recursos'},
  {id:'materials',label:'📦 Material'},
  {id:'photos',label:'📷 Fotos'},
];

function openNewJob(){
  curJob=null;isEditing=false;
  formState={clientName:'',phone:'',email:'',startTime:'08:00',endTime:'12:00',
    vehicle:'',team:'',plate:'',price:'',payment:'',
    originAddress:'',originFloor:'',originElevator:false,
    destinAddress:'',destinFloor:'',destinElevator:false,
    materials:[],notes:'',status:'pendiente'};
  formPhotos=[];activeTab='info';
  $('form-title').textContent='Nuevo trabajo';
  renderTabBar();renderFormTab();showView('form');
}
function openJobForm(editing){
  isEditing=editing;activeTab='info';
  $('form-title').textContent=editing?'Editar trabajo':'Nuevo trabajo';
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
function renderFormTab(){
  const scroll=$('form-scroll'),f=formState;
  if(activeTab==='info'){
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">Cliente</div>
        <div class="fi"><label>Nombre del cliente</label><input id="f-client" placeholder="Nombre" value="${esc(f.clientName)}" /></div>
        <div class="fi"><label>Teléfono</label><input id="f-phone" type="tel" placeholder="Teléfono" value="${esc(f.phone)}" /></div>
        <div class="fi"><label>Email</label><input id="f-email" type="email" placeholder="Email" value="${esc(f.email)}" /></div>
        <div class="fi"><label>Presupuesto (€)</label><input id="f-price" type="number" placeholder="0.00" step="0.01" value="${esc(String(f.price))}" /></div>
        <div class="fi"><label>Método de pago</label>
          <select id="f-payment">
            <option value="">— —</option>
            ${['Efectivo','Transferencia','Tarjeta','Bizum'].map(p=>`<option${f.payment===p?' selected':''}>${p}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="form-section">
        <div class="form-section-title">Horario</div>
        <div class="time-row">
          <div class="fi"><label>Hora inicio</label><input id="f-start" type="time" value="${esc(f.startTime)}" /></div>
          <div class="fi"><label>Hora fin (aprox.)</label><input id="f-end" type="time" value="${esc(f.endTime)}" /></div>
        </div>
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
    const bind=(id,key)=>{const el=$(id);if(el)el.oninput=()=>formState[key]=el.value;};
    bind('f-client','clientName');bind('f-phone','phone');bind('f-email','email');
    bind('f-price','price');bind('f-start','startTime');bind('f-end','endTime');
    $('f-payment').onchange=e=>formState.payment=e.target.value;
    scroll.querySelectorAll('.status-opt').forEach(btn=>{btn.onclick=()=>{formState.status=btn.dataset.s;renderFormTab();};});
  }
  if(activeTab==='addresses'){
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">📍 Origen</div>
        <div class="fi"><label>Dirección</label><input id="f-oa" placeholder="Calle, número, ciudad…" value="${esc(f.originAddress)}" /></div>
        <div class="fi"><label>Piso / Puerta</label><input id="f-of" placeholder="3º B" value="${esc(f.originFloor)}" /></div>
        <div class="check-row"><input type="checkbox" id="f-oe" ${f.originElevator?'checked':''} /><label for="f-oe">Tiene ascensor</label></div>
      </div>
      <div class="form-section">
        <div class="form-section-title">🏠 Destino</div>
        <div class="fi"><label>Dirección</label><input id="f-da" placeholder="Calle, número, ciudad…" value="${esc(f.destinAddress)}" /></div>
        <div class="fi"><label>Piso / Puerta</label><input id="f-df" placeholder="2º A" value="${esc(f.destinFloor)}" /></div>
        <div class="check-row"><input type="checkbox" id="f-de" ${f.destinElevator?'checked':''} /><label for="f-de">Tiene ascensor</label></div>
      </div>
      <div class="form-section">
        <div class="form-section-title">📝 Notas</div>
        <div class="fi"><textarea id="f-notes" rows="4" placeholder="Observaciones, acceso difícil…">${esc(f.notes)}</textarea></div>
      </div>`;
    const bind=(id,key)=>{const el=$(id);if(el)el.oninput=()=>formState[key]=el.value;};
    bind('f-oa','originAddress');bind('f-of','originFloor');
    bind('f-da','destinAddress');bind('f-df','destinFloor');bind('f-notes','notes');
    $('f-oe').onchange=e=>formState.originElevator=e.target.checked;
    $('f-de').onchange=e=>formState.destinElevator=e.target.checked;
  }
  if(activeTab==='resources'){
    scroll.innerHTML=`
      <div class="form-section">
        <div class="form-section-title">🚛 Vehículo</div>
        ${VEHICLES.map(v=>`<button class="select-opt${f.vehicle===v?' active':''}" data-v="${esc(v)}">${esc(v)}</button>`).join('')}
      </div>
      <div class="form-section">
        <div class="form-section-title">👷 Equipo</div>
        ${['Equipo A (2 personas)','Equipo B (2 personas)','Equipo C (3 personas)','Equipo D (4 personas)'].map(w=>`<button class="select-opt${f.team===w?' active':''}" data-w="${esc(w)}">${esc(w)}</button>`).join('')}
      </div>
      <div class="form-section">
        <div class="form-section-title">🔑 Matrícula</div>
        <div class="fi"><label>Matrícula / ID vehículo</label><input id="f-plate" placeholder="1234 ABC" value="${esc(f.plate||'')}" /></div>
      </div>`;
    scroll.querySelectorAll('[data-v]').forEach(btn=>{btn.onclick=()=>{formState.vehicle=btn.dataset.v;renderFormTab();};});
    scroll.querySelectorAll('[data-w]').forEach(btn=>{btn.onclick=()=>{formState.team=btn.dataset.w;renderFormTab();};});
    const pl=$('f-plate');if(pl)pl.oninput=()=>formState.plate=pl.value;
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
  get('f-client','clientName');get('f-phone','phone');get('f-email','email');
  get('f-price','price');get('f-start','startTime');get('f-end','endTime');
  get('f-oa','originAddress');get('f-of','originFloor');
  get('f-da','destinAddress');get('f-df','destinFloor');
  get('f-notes','notes');get('f-plate','plate');
  const oe=$('f-oe');if(oe)formState.originElevator=oe.checked;
  const de=$('f-de');if(de)formState.destinElevator=de.checked;
  const fp=$('f-payment');if(fp)formState.payment=fp.value;
}

$('btn-form-cancel').onclick=()=>isEditing?showView('detail'):showView('day');
$('btn-save-job').addEventListener('click',async()=>{
  collectFormState();
  if(!formState.clientName){toast('Añade el nombre del cliente','err');return;}
  if(!selDate){toast('No hay fecha seleccionada','err');return;}
  $('btn-save-job').innerHTML='<span class="spin"></span>';
  $('btn-save-job').disabled=true;
  const data={...formState,date:selDate,photos:formPhotos,updatedBy:auth.currentUser.email,updatedAt:serverTimestamp()};
  try{
    if(isEditing&&curJob){
      await setDoc(doc(db,'trabajos',curJob.id),data,{merge:true});
      curJob={...curJob,...data};toast('✅ Trabajo actualizado','ok');
      renderDetailView();showView('detail');
    }else{
      data.createdBy=auth.currentUser.email;data.createdAt=serverTimestamp();
      await addDoc(collection(db,'trabajos'),data);
      toast('✅ Trabajo creado','ok');showView('day');
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
  cont.innerHTML=`
    <div class="tarifa-section">
      <div class="tarifa-section-title">👷 Mano de obra</div>
      <div class="tarifa-row">
        <span class="tarifa-label">Precio por hora / trabajador</span>
        <div class="tarifa-input-wrap">
          <input class="tarifa-input" type="number" min="0" step="0.5" id="t-worker-hour" value="${fmt(tarifas.workerHour)}" />
          <span class="tarifa-unit">€/h</span>
        </div>
      </div>
    </div>
    <div class="tarifa-section">
      <div class="tarifa-section-title">📦 Precio unitario de materiales</div>
      ${MATERIALS.map(m=>`
        <div class="tarifa-row">
          <span class="tarifa-label">${esc(m)}</span>
          <div class="tarifa-input-wrap">
            <input class="tarifa-input" type="number" min="0" step="0.1" data-mat="${esc(m)}" value="${fmt(tarifas[m]||0)}" />
            <span class="tarifa-unit">€/ud</span>
          </div>
        </div>`).join('')}
    </div>
    <button class="save-tarifas-btn" id="btn-save-tarifas">Guardar tarifas</button>`;

  $('btn-save-tarifas').addEventListener('click',async()=>{
    tarifas.workerHour=Number($('t-worker-hour').value||0);
    cont.querySelectorAll('[data-mat]').forEach(inp=>{tarifas[inp.dataset.mat]=Number(inp.value||0);});
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
  onMessage(messaging,p=>{const{title,body}=p.notification||{};toast(`🔔 ${title}: ${body}`);});
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
    const res = await fetch(CLOUD_FUNCTION_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
  initNotifs();
  checkLayout();
  window.addEventListener('resize', checkLayout);
  if('serviceWorker' in navigator)
    navigator.serviceWorker.register('firebase-messaging-sw.js').catch(()=>{});
}
