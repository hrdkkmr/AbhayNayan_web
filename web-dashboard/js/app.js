import * as store from './store.js';
import { assessImageQuality, correctAmbientLight, createSyntheticImage, extractOpticalFeatures, imageDataFromCanvas } from './vision.js';
import { formatEstimate, getDemoCases, riskTone, runDemoInference } from './inference.js';
import { LANGUAGES, localCounsel, navLabels } from './language.js';
import { buildFhirBundle, downloadJson } from './fhir.js';

const state = {
  page: 'home', language: 'en', workerName: 'Demo ASHA Worker', phc: 'Demo PHC · Bihta',
  simulateOffline: false, patients: [], selectedPatientId: '', screeningType: 'maternal_anemia',
  wizardStep: 1, previewDataUrl: '', imageData: null, captureSource: '', cameraStream: null,
  cameraActive: false, regionConfirmed: false, syntheticImage: false, quality: null,
  opticalFeatures: null, ambientResult: null, selectedCaseId: '', lastRecord: null,
  counselling: null, lastCounselLanguage: '', localOnly: false, referral: null,
  apiHealth: null, filter: 'all', search: '',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
const pageNames = { home: 'Home', new: 'New screening', patients: 'Patients', history: 'History', sync: 'Sync queue', phc: 'PHC dashboard', architecture: 'Pipeline & architecture', model: 'Model & data audit', settings: 'Settings', result: 'Screening result' };

async function apiRequest(path, options = {}) {
  if (state.simulateOffline || !navigator.onLine) throw new Error('Offline mode — saved locally on this device.');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 6500);
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  try {
    const response = await fetch(path, { ...options, headers, signal: controller.signal });
    if (!response.ok) {
      let detail = `Request failed (${response.status}).`;
      try { const body = await response.json(); detail = body.detail || detail; } catch { /* response may not be JSON */ }
      throw new Error(detail);
    }
    return response;
  } finally { clearTimeout(timer); }
}

function toast(message, type = 'success') {
  const region = $('#toastRegion');
  if (!region) return;
  const item = document.createElement('div');
  item.className = `toast ${type === 'error' ? 'error' : type === 'warning' ? 'warning' : ''}`;
  item.textContent = message;
  region.append(item);
  setTimeout(() => item.remove(), 3600);
}

function setHeader() {
  const nav = navLabels(state.language);
  $$('.nav-item[data-page]').forEach((button) => {
    const key = button.dataset.page;
    const label = button.querySelector('span:nth-child(2)');
    if (label && nav[key]) label.textContent = nav[key];
    button.classList.toggle('active', key === state.page || (state.page === 'result' && key === 'new'));
  });
  $('#currentSection').textContent = pageNames[state.page] || 'AbhayNayan';
  const language = LANGUAGES.find((item) => item.id === state.language) || LANGUAGES[0];
  $('#languageLabel').textContent = language.native;
  $('.language-symbol').textContent = language.symbol;
  $('#workerMiniName').textContent = state.workerName;
  $('#workerMiniPhc').textContent = state.phc;
  updateNetworkChip();
}

function updateNetworkChip() {
  const chip = $('#networkChip');
  const label = $('#networkLabel');
  if (!chip || !label) return;
  chip.classList.remove('online', 'offline', 'down');
  if (state.simulateOffline) { chip.classList.add('offline'); label.textContent = 'OFFLINE DEMO'; }
  else if (!navigator.onLine) { chip.classList.add('down'); label.textContent = 'NO NETWORK'; }
  else { chip.classList.add('online'); label.textContent = 'ONLINE'; }
  const count = document.querySelector('#navPending');
  if (count) store.getAll('syncQueue').then((items) => { count.textContent = String(items.length); }).catch(() => {});
}

function dateLabel(value, withTime = true) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const locale = state.language === 'hi' ? 'hi-IN' : state.language === 'bho' ? 'hi-IN' : 'en-IN';
  return new Intl.DateTimeFormat(locale, withTime ? { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: 'short', year: 'numeric' }).format(date);
}

function typeLabel(type) { return type === 'neonatal_jaundice' ? 'Neonatal jaundice' : 'Maternal anemia'; }
function regionLabelForType(type) { return type === 'neonatal_jaundice' ? 'sclera/eye region' : 'lower-eyelid conjunctiva'; }
function riskClass(category) {
  const tone = riskTone(category);
  return tone === 'red' ? 'badge-red' : tone === 'amber' ? 'badge-amber' : tone === 'green' ? 'badge-green' : 'badge-gray';
}
function localResultLabel(record) {
  return formatEstimate(record.result);
}
function safetyBlock(text = 'Synthetic prototype estimate only. Not a diagnosis or validated clinical measurement. Confirm with appropriate clinical testing and local protocol.') {
  return `<div class="safety-note"><strong>Safety boundary · synthetic demo</strong><br>${escapeHtml(text)}</div>`;
}
function pageHead(eyebrow, title, description, actions = '') {
  return `<div class="page-head"><div><div class="page-eyebrow">${escapeHtml(eyebrow)}</div><h1>${title}</h1><p>${description}</p></div>${actions ? `<div class="page-actions">${actions}</div>` : ''}</div>`;
}
function emptyState(icon, title, message, button = '') {
  return `<div class="empty-state"><div class="empty-icon">${icon}</div><strong>${title}</strong><span>${message}</span>${button}</div>`;
}
function recordRows(records, emptyCopy = 'Complete a synthetic demonstration to see a record here.') {
  if (!records.length) return emptyState('◷', 'No screening records yet', emptyCopy, `<button class="btn btn-primary btn-sm" data-action="start-screening">Start a demo screening</button>`);
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Patient ID</th><th>Screening</th><th>Prototype estimate</th><th>Demo tag</th><th>Date</th><th>Sync</th><th></th></tr></thead><tbody>${records.map((record) => `<tr>
    <td class="table-strong">${escapeHtml(record.patient?.patient_id || record.patient_id || '—')}</td>
    <td>${escapeHtml(typeLabel(record.result?.screening_type))}</td>
    <td class="table-strong">${escapeHtml(localResultLabel(record))}</td>
    <td><span class="badge ${riskClass(record.result?.risk_category)}">${escapeHtml(record.result?.risk_category || 'DEMO_ONLY')}</span></td>
    <td>${escapeHtml(dateLabel(record.created_at))}</td>
    <td><span class="badge ${record.sync_status === 'synced' ? 'badge-green' : 'badge-amber'}">${record.sync_status === 'synced' ? 'Synced' : 'Queued locally'}</span></td>
    <td><button class="btn btn-secondary btn-sm" data-action="open-record" data-screening-id="${escapeHtml(record.id)}">Review</button></td>
  </tr>`).join('')}</tbody></table></div>`;
}

async function renderHome() {
  const [patients, screenings, queue, referrals] = await Promise.all([
    store.getAll('patients'), store.getAll('screenings'), store.getAll('syncQueue'), store.getAll('referrals'),
  ]);
  const today = new Date().toDateString();
  const todayCount = screenings.filter((record) => new Date(record.created_at).toDateString() === today).length;
  let apiState = 'not checked';
  try {
    const response = await apiRequest('/api/health', { timeout: 1700 });
    state.apiHealth = await response.json(); apiState = 'connected';
  } catch { state.apiHealth = null; apiState = 'local-only'; }
  const newest = [...screenings].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 5);
  return `${`<section class="hero-panel"><div class="hero-content"><div class="hero-kicker"><span class="pulse-dot"></span> LOCAL-FIRST · DEMO ONLY</div><h1>Clearer next steps.<br>Closer to the community.</h1><p>Explore maternal anemia and newborn jaundice workflows with a transparent, synthetic screening prototype. No camera frame is uploaded.</p><div class="hero-buttons"><button class="btn btn-light" data-action="start-screening">＋ Start a screening</button><button class="btn btn-outline-light" data-page="architecture">Explore the pipeline <span>→</span></button></div></div><div class="hero-illustration" aria-hidden="true"><div class="hero-orbit"><div class="hero-shield">अ</div></div></div></section>`}
    <div class="online-banner ${state.simulateOffline || !navigator.onLine ? 'offline' : ''}" style="margin-top:14px"><div class="banner-icon">${state.simulateOffline || !navigator.onLine ? '⇄' : '▣'}</div><div class="banner-copy"><strong>${state.simulateOffline || !navigator.onLine ? 'Offline-first demo is ready' : `API ${apiState === 'connected' ? 'connected' : 'not reachable'} · local workflow remains available`}</strong><span>Patient details and camera pixels stay in this browser. Server sync sends a pseudonymous ID and synthetic demo record only.</span></div></div>
    <div class="card-grid grid-4" style="margin-top:15px">
      <div class="panel stat-card"><div class="stat-top"><span class="stat-label">Local screenings</span><span class="stat-icon">◷</span></div><div class="stat-number">${screenings.length}</div><div class="stat-caption">Synthetic demo records</div></div>
      <div class="panel stat-card"><div class="stat-top"><span class="stat-label">Today on this device</span><span class="stat-icon">▦</span></div><div class="stat-number">${todayCount}</div><div class="stat-caption">Not a population metric</div></div>
      <div class="panel stat-card stat-warning"><div class="stat-top"><span class="stat-label">Awaiting sync</span><span class="stat-icon">⇄</span></div><div class="stat-number">${queue.length}</div><div class="stat-caption">Stored locally until online</div></div>
      <div class="panel stat-card"><div class="stat-top"><span class="stat-label">Local patient profiles</span><span class="stat-icon">♙</span></div><div class="stat-number">${patients.length}</div><div class="stat-caption">Names remain on this device</div></div>
    </div>
    <div class="section-title-row"><div><h2>Choose a screening workflow</h2><p>Every output is a named synthetic fixture, not a pixel-derived measurement.</p></div></div>
    <div class="card-grid grid-2">
      <button class="action-card" data-action="start-maternal"><span class="action-icon">♡</span><span class="action-copy"><strong>Maternal anemia workflow</strong><span>Patient profile → local capture quality → optical feature visualization → selected synthetic Hb fixture → counselling and referral.</span></span><span class="action-arrow">→</span></button>
      <button class="action-card" data-action="start-jaundice"><span class="action-icon amber">☼</span><span class="action-copy"><strong>Neonatal jaundice workflow</strong><span>Newborn profile → local capture quality → manual sclera guide → selected synthetic bilirubin fixture → clinician-confirmation message.</span></span><span class="action-arrow">→</span></button>
    </div>
    <div class="section-title-row"><div><h2>Recent local records</h2><p>Results are prominently tagged synthetic and require clinical confirmation.</p></div><button class="view-link" data-page="history">View history →</button></div>
    <div class="panel">${recordRows(newest, 'There are no saved screenings on this device yet.')}</div>
    <div class="card-note" style="margin-top:15px"><strong>Prototype, not care advice.</strong> This build has no clinically approved TFLite model. Demo estimates are selected from fixed examples and are not derived from the live camera, imported image, or optical features. Do not use them to diagnose, triage, or change treatment.</div>`;
}

function selectedPatient() { return state.patients.find((person) => person.id === state.selectedPatientId) || null; }
function screeningTypeDetails(type) {
  return type === 'neonatal_jaundice'
    ? { title: 'Neonatal jaundice', subtitle: 'Forehead/sclera workflow · demo bilirubin fixture only', icon: '☼', guide: 'Sclera / eye region', unit: 'mg/dL' }
    : { title: 'Maternal anemia', subtitle: 'Palpebral conjunctiva workflow · demo Hb fixture only', icon: '♡', guide: 'Lower eyelid / conjunctiva', unit: 'g/dL' };
}
function stepIndicator(step) {
  const labels = ['Patient & pathway', 'Camera & quality', 'Features & demo case'];
  return `<div class="wizard-steps">${labels.map((label, index) => `<div class="wizard-step ${step === index + 1 ? 'active' : step > index + 1 ? 'done' : ''}"><span class="wizard-number">${step > index + 1 ? '✓' : index + 1}</span><span>${label}</span></div>`).join('')}</div>`;
}

function renderWizard() {
  const patient = selectedPatient();
  const details = screeningTypeDetails(state.screeningType);
  const step = state.wizardStep;
  let body = '';
  if (step === 1) {
    body = `<div class="card-grid grid-2">
      <div class="panel panel-pad"><div class="row-between"><div><h2 style="margin:0;color:var(--navy);font-size:14px">Select a local patient</h2><p style="margin:4px 0 12px;color:var(--body);font-size:9px">No name, phone, or photo is sent to the server.</p></div><button class="btn btn-secondary btn-sm" data-action="new-patient">＋ Add patient</button></div>
        <div class="form-field"><label for="patientSelect">Patient profile</label><select class="select" id="patientSelect">${state.patients.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === state.selectedPatientId ? 'selected' : ''}>${escapeHtml(item.name || 'Local profile')} · ${escapeHtml(item.id)}${item.isDemo ? ' · synthetic demo' : ' · local only'}</option>`).join('')}</select></div>
        ${patient ? `<div class="card-note" style="margin-top:12px"><strong>${escapeHtml(patient.name || 'Local profile')}</strong> · ${escapeHtml(patient.id)}<br>${patient.isDemo ? 'Synthetic profile · eligible for the fixed demo fixtures.' : 'Real/local profile · optical quality and feature visualization only; no synthetic estimate will be linked.'}</div>` : ''}
      </div>
      <div class="panel panel-pad"><h2 style="margin:0 0 4px;color:var(--navy);font-size:14px">Choose the workflow</h2><p style="margin:0 0 12px;color:var(--body);font-size:9px">This selection changes labels and synthetic examples; it does not diagnose.</p>
        <div class="col"><button class="screening-choice ${state.screeningType === 'maternal_anemia' ? 'selected' : ''}" data-task="maternal_anemia"><span class="choice-icon">♡</span><span><strong>Maternal anemia</strong><span>Conjunctiva guide · Hb units (g/dL)</span></span><span class="choice-arrow">→</span></button>
        <button class="screening-choice ${state.screeningType === 'neonatal_jaundice' ? 'selected' : ''}" data-task="neonatal_jaundice"><span class="choice-icon gold">☼</span><span><strong>Neonatal jaundice</strong><span>Sclera guide · bilirubin units (mg/dL)</span></span><span class="choice-arrow">→</span></button></div>
      </div></div>
      <div class="row-between" style="margin-top:16px"><span class="card-note">Patient details are stored only in this browser. A non-demo profile cannot receive a synthetic fixture result.</span><button class="btn btn-primary" data-action="wizard-next" ${patient ? '' : 'disabled'}>Continue to camera guide →</button></div>`;
  } else if (step === 2) {
    const q = state.quality;
    const isJaundice = state.screeningType === 'neonatal_jaundice';
    const preview = state.previewDataUrl ? `<img class="camera-image" alt="${state.syntheticImage ? 'Abstract synthetic image, not a patient photograph' : 'Locally held captured image preview'}" src="${escapeHtml(state.previewDataUrl)}">` : '';
    const qualityPct = Math.round((q?.qualityScore || 0) * 100);
    const qualityColor = qualityPct > 75 ? 'good' : qualityPct > 45 ? 'warn' : 'bad';
    body = `<div class="camera-layout"><div><div class="camera-stage" id="cameraStage">
      <video id="liveVideo" autoplay playsinline muted style="${state.cameraActive && !state.previewDataUrl ? '' : 'display:none'}"></video>${preview}
      ${!state.previewDataUrl && !state.cameraActive ? `<div class="camera-placeholder"><div class="camera-big">◉</div><strong>Camera stays on this device</strong><span>Start the rear camera, select a local image, or use the abstract fixture. There is no image-upload endpoint.</span></div>` : ''}
      <div class="camera-overlay"><div class="camera-guide ${isJaundice ? '' : 'eye-guide'}"></div><span class="camera-cross"></span></div>
      <div class="camera-caption"><span>${escapeHtml(details.guide)} · manual guide</span><span>${state.syntheticImage ? 'SYNTHETIC FIXTURE' : state.captureSource ? 'LOCAL IMAGE' : 'NO CAPTURE'}</span></div>
    </div><div class="camera-controls"><button class="btn btn-primary btn-sm" data-action="start-camera" ${state.cameraActive ? 'disabled' : ''}>◉ Open camera</button><button class="btn btn-secondary btn-sm" data-action="capture-frame" ${state.cameraActive ? '' : 'disabled'}>Capture frame</button><button class="btn btn-secondary btn-sm" data-action="open-file">Choose local image</button><button class="btn btn-amber btn-sm" data-action="synthetic-image">Use abstract synthetic image</button></div></div>
      <aside class="panel camera-side"><div class="row-between"><strong style="color:var(--navy);font-size:12px">Local image quality gate</strong><span class="badge ${q?.ready ? 'badge-green' : 'badge-gray'}">${q?.ready ? 'READY' : 'WAITING'}</span></div>
        <p style="margin:6px 0;color:var(--body);font-size:9px">Brightness and edge sharpness are measured in-browser. No anatomy landmarks are bundled.</p>
        <div class="signal-list"><div class="signal-row"><span>Brightness</span><strong>${q ? `${escapeHtml(q.brightness)} / 255` : '—'}</strong></div><div class="signal-row"><span>Edge/blur proxy</span><strong>${q ? `${Math.round(q.blurScore * 100)}%` : '—'}</strong></div><div class="signal-row"><span>Manual region check</span><strong>${q?.regionConfirmed ? 'CONFIRMED' : 'REQUIRED'}</strong></div></div>
        <div class="quality-meter"><span style="width:${qualityPct}%;background:${qualityColor === 'bad' ? '#c4484f' : qualityColor === 'warn' ? '#d9912b' : ''}"></span></div><div class="quality-readout"><span>Prototype quality score</span><strong>${q ? `${qualityPct}%` : '0%'}</strong></div>
        ${q?.reasons?.length ? `<ul style="padding-left:17px;color:#9b6220;font-size:8px;line-height:1.6">${q.reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join('')}</ul>` : q?.ready ? `<div class="callout" style="margin-top:10px">Quality gate passed for this demo flow. This is not a clinical capture-quality guarantee.</div>` : ''}
        ${state.captureSource && !state.syntheticImage ? `<label class="check-row" style="margin-top:12px"><input type="checkbox" id="regionConfirm" ${state.regionConfirmed ? 'checked' : ''}><span>I manually confirm the target region is inside the guide. Landmark detection is not available.</span></label>` : ''}
        <div class="card-note" style="margin-top:12px"><strong>Flash correction:</strong> only an experimental browser visualization is available; no synchronized hardware flash pair or clinical calibration is claimed.</div>
      </aside></div>
      ${safetyBlock('Capture quality and optical features are engineering demonstrations only. A named synthetic fixture is never inferred from this image.')}
      <div class="row-between" style="margin-top:15px"><button class="btn btn-secondary" data-action="wizard-back">← Back</button><button class="btn btn-primary" data-action="wizard-next" ${q?.ready ? '' : 'disabled'}>Review features & demo cases →</button></div>`;
  } else {
    const cases = getDemoCases(state.screeningType);
    const patientCanDemo = Boolean(patient?.isDemo && state.syntheticImage);
    const features = state.opticalFeatures;
    const caseOptions = cases.map((item) => `<button class="screening-choice ${state.selectedCaseId === item.id ? 'selected' : ''}" data-case-id="${escapeHtml(item.id)}"><span class="choice-icon ${item.category?.includes('HIGH') || item.category?.includes('ESCALATE') ? 'gold' : ''}">${item.category?.includes('HIGH') || item.category?.includes('ESCALATE') ? '↗' : '◈'}</span><span><strong>${escapeHtml(item.name)}</strong><span>Fixed synthetic fixture · ${escapeHtml(Number(item.value).toFixed(1))} ${escapeHtml(item.unit)} · ${escapeHtml(item.category)}</span></span><span class="choice-arrow">${state.selectedCaseId === item.id ? '✓' : '○'}</span></button>`).join('');
    body = `<div class="card-grid grid-2"><div class="panel panel-pad"><div class="row-between"><div><h2 style="margin:0;color:var(--navy);font-size:14px">Optical-feature preview</h2><p style="margin:4px 0 12px;color:var(--body);font-size:9px">Computed locally from the center guide; not used to select the estimate.</p></div><span class="badge badge-blue">LOCAL ONLY</span></div>
      ${features ? `<div class="kpi-strip"><div><strong>${features.rgb.r.toFixed(1)}</strong><span>R mean</span></div><div><strong>${features.rgb.g.toFixed(1)}</strong><span>G mean</span></div><div><strong>${features.rgb.b.toFixed(1)}</strong><span>B mean</span></div></div><div class="form-grid" style="margin-top:11px"><div class="metric-target"><strong>${features.hsv.h.toFixed(1)}° / ${features.hsv.s.toFixed(1)}%</strong><span>HSV hue / saturation</span></div><div class="metric-target"><strong>${features.labApprox.L.toFixed(1)} / ${features.labApprox.a.toFixed(1)} / ${features.labApprox.b.toFixed(1)}</strong><span>Approximate CIELAB L*a*b*</span></div><div class="metric-target"><strong>${features.yCrCb.y.toFixed(1)} / ${features.yCrCb.cr.toFixed(1)} / ${features.yCrCb.cb.toFixed(1)}</strong><span>Y / Cr / Cb</span></div><div class="metric-target"><strong>${features.sampleCount}</strong><span>Sampled pixels (downsampled)</span></div></div>` : `<div class="card-note">No feature vector available. Return to the camera step and capture a local or synthetic image.</div>`}
      <div class="card-note" style="margin-top:12px">${escapeHtml(features?.note || 'No image pixels are sent to the server.')} Color is uncalibrated; feature values are not hemoglobin or bilirubin readings.</div></div>
      <div class="panel panel-pad"><div class="row-between"><div><h2 style="margin:0;color:var(--navy);font-size:14px">Select a named synthetic case</h2><p style="margin:4px 0 12px;color:var(--body);font-size:9px">The estimate below is selected from a fixed fixture, never computed from the image.</p></div><span class="badge badge-amber">DEMO ONLY</span></div><div class="col">${caseOptions}</div>
        ${patientCanDemo ? `<div class="callout" style="margin-top:11px">Linked to <strong>${escapeHtml(patient.name)}</strong> (${escapeHtml(patient.id)}), a synthetic demo profile and abstract synthetic image only.</div>` : `<div class="safety-note danger" style="margin-top:11px"><strong>Estimate disabled for this capture/profile.</strong><br>${patient?.isDemo ? 'A real camera/import image may be used for local quality and feature visualization only. Go back and choose the abstract synthetic image to run a disconnected fixture demo.' : 'Current prototype has no clinical model. A synthetic result cannot be attached to a real/local patient profile.'}</div>`}
      </div></div>
      ${safetyBlock('This selected fixture is synthetic, not derived from camera pixels, optical features, or a trained clinical model. Do not use it for diagnosis, triage, or treatment decisions.')}
      <div class="row-between" style="margin-top:15px"><button class="btn btn-secondary" data-action="wizard-back">← Back to quality gate</button><button class="btn btn-primary" data-action="run-screening" ${patientCanDemo && state.selectedCaseId ? '' : 'disabled'}>Run selected synthetic case →</button></div>`;
  }
  return `${pageHead('Screening workspace', step === 1 ? 'Start a guided screening' : step === 2 ? 'Capture & local quality check' : 'Review features & choose a demo case', 'A transparent prototype workflow for frontline teams — not a medical device or diagnostic tool.')}<div class="panel panel-pad">${stepIndicator(step)}${body}</div>`;
}

function renderResult() {
  const record = state.lastRecord;
  if (!record) return `${pageHead('Screening result', 'No result selected', 'Choose a local history record to review.')}<div class="panel">${emptyState('◈', 'No result selected', 'Start a synthetic demonstration or open a saved record from history.')}</div>`;
  const result = record.result;
  const type = result.screening_type;
  const counsel = state.counselling || localCounsel(type, state.language, result.risk_category);
  const patient = state.patients.find((item) => item.id === record.patient?.patient_id);
  const severity = riskTone(result.risk_category);
  const safety = result.safety_note || 'Synthetic prototype estimate only; confirm with appropriate clinical testing.';
  const referralLabel = state.referral?.id ? `Referral ${state.referral.id} saved` : 'Create referral brief';
  const script = counsel.counselling_script || counsel.script || '';
  const counselMode = counsel.mode || 'LOCAL_FALLBACK';
  const audit = state.lastRecord.capture_audit || state.captureAudit || null;
  return `${pageHead('Prototype screening result', 'A demo estimate — never a diagnosis', 'This fixed synthetic example illustrates how the app presents a result. It was not inferred from the captured image or a patient’s optical features.', `<button class="btn btn-secondary" data-action="new-screening">＋ New screening</button>`)}
    <div class="result-hero"><div><div class="result-overline">SYNTHETIC FIXTURE · ${escapeHtml(typeLabel(type))}</div><div class="result-value">${escapeHtml(Number(result.estimate).toFixed(1))} <small>${escapeHtml(result.unit)}</small></div><div class="result-title">${escapeHtml(result.case_label || 'Synthetic demo case')}</div><div class="result-summary">Patient ID: ${escapeHtml(record.patient?.patient_id || '—')} · ${escapeHtml(dateLabel(record.created_at))} · no pixel-derived estimate</div></div><div class="risk-pill ${severity === 'red' ? 'badge-red' : severity === 'amber' ? 'badge-amber' : ''}">${escapeHtml(result.risk_category)}</div></div>
    <div class="result-metrics"><div class="metric-card"><span>Prototype confidence indicator · not clinical probability</span><strong>${Math.round(result.confidence * 100)}%</strong><em>Placeholder from fixed case metadata</em></div><div class="metric-card"><span>Fixed-case quality placeholder</span><strong>${Math.round(result.quality_score * 100)}%</strong><em>Case metadata; not the captured image score</em></div><div class="metric-card"><span>Inference mode</span><strong style="font-size:15px">${escapeHtml(result.model_mode)}</strong><em>Fixed deterministic fixture · model not present</em></div></div>
    <div style="margin-top:13px">${safetyBlock(safety)}</div>
    <div class="card-grid grid-2" style="margin-top:14px"><section class="panel panel-pad"><div class="row-between"><div><h2 style="font-size:13px;color:var(--navy);margin:0">Counselling & next step</h2><p style="font-size:9px;color:var(--body);margin:4px 0 10px">Generated ${counselMode === 'GEMINI' ? 'by optional server-side Gemini' : 'locally by deterministic language fallback'} · ${escapeHtml(counsel.language || state.language)}</p></div><span class="badge ${counselMode === 'GEMINI' ? 'badge-blue' : 'badge-gray'}">${escapeHtml(counselMode)}</span></div>
      <div class="language-tabs">${LANGUAGES.map((lang) => `<button class="language-tab ${state.language === lang.id ? 'active' : ''}" data-lang-tab="${lang.id}">${escapeHtml(lang.native)}</button>`).join('')}</div>
      <div class="counsel-box" style="margin-top:10px">${escapeHtml(script)}</div>
      <div class="action-list"><div class="action-line"><span class="check-mark">✓</span><span><strong>Recommended next step:</strong> ${escapeHtml(counsel.recommended_next_step || counsel.action || 'Confirm using appropriate clinical testing and local protocol.')}</span></div><div class="action-line"><span class="check-mark">ⓘ</span><span><strong>Demo tag explanation:</strong> ${escapeHtml(counsel.risk_explanation || counsel.risk || 'Software demonstration tag only; not a clinical risk classification.')}</span></div></div>
      <div class="card-note">${escapeHtml(counsel.safety_note || 'Do not use this demo estimate to change treatment.')}</div></section>
      <section class="panel panel-pad"><div class="row-between"><div><h2 style="font-size:13px;color:var(--navy);margin:0">Capture & pipeline audit</h2><p style="font-size:9px;color:var(--body);margin:4px 0 11px">On-device visualization only; the image is not stored with the screening record.</p></div><span class="badge badge-blue">LOCAL</span></div>
        <div class="signal-list"><div class="signal-row"><span>Source</span><strong>${escapeHtml(audit?.source || state.captureSource || 'Not retained in this session')}</strong></div><div class="signal-row"><span>Quality gate</span><strong>${audit?.quality ? `${Math.round(audit.quality.qualityScore * 100)}%` : `${Math.round(result.quality_score * 100)}% · fixture metadata`}</strong></div><div class="signal-row"><span>Region</span><strong>Manual guide · no landmarks</strong></div><div class="signal-row"><span>Image / optical feature upload</span><strong>NEVER</strong></div><div class="signal-row"><span>Server sync</span><strong>${record.sync_status === 'synced' ? 'PSEUDONYMOUS DEMO RECORD' : 'QUEUED LOCALLY'}</strong></div></div>
        <div class="callout" style="margin-top:13px">${patient ? `Local profile: ${escapeHtml(patient.name)} · ${escapeHtml(patient.id)}` : 'Patient name is not sent to the backend.'}. Optical RGB/HSV/Lab values are exploratory and are not used in this result.</div>
        <div class="row" style="margin-top:13px;flex-wrap:wrap"><button class="btn btn-secondary btn-sm" data-action="download-fhir">↓ FHIR JSON</button><button class="btn btn-secondary btn-sm" data-action="create-referral">${escapeHtml(referralLabel)}</button><button class="btn btn-quiet btn-sm" data-action="print-referral">Print / save PDF</button></div>
        ${state.referral?.pdfUrl ? `<div class="callout" style="margin-top:10px">Server PDF ready: <a href="${escapeHtml(state.referral.pdfUrl)}" target="_blank" rel="noopener">Download referral PDF</a></div>` : ''}
      </section></div>
    <div class="pipeline-list">${[['◉','Capture','Local only'],['⌖','ROI','Manual guide'],['◈','Features','Not calibrated'],['▣','Quality','Engineering proxy'],['◇','Inference','Fixed demo'],['♡','Action','Clinician confirm']].map((item, i) => `<div class="pipeline-node ${i < 4 ? 'done' : i === 4 ? 'current' : ''}"><div class="node-icon">${item[0]}</div><strong>${item[1]}</strong><span>${item[2]}</span></div>`).join('')}</div>`;
}

async function renderPatients() {
  const patients = [...await store.getAll('patients')].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  const screenings = await store.getAll('screenings');
  const counts = new Map();
  for (const row of screenings) counts.set(row.patient?.patient_id, (counts.get(row.patient?.patient_id) || 0) + 1);
  const rows = patients.map((person) => `<tr><td class="table-strong">${escapeHtml(person.name || 'Local profile')}</td><td>${escapeHtml(person.id)}</td><td>${escapeHtml(person.age ?? '—')}</td><td>${escapeHtml(person.sex || '—')}</td><td><span class="badge ${person.isDemo ? 'badge-blue' : 'badge-gray'}">${person.isDemo ? 'SYNTHETIC DEMO' : 'LOCAL ONLY'}</span></td><td>${counts.get(person.id) || 0}</td><td><button class="btn btn-secondary btn-sm" data-action="screen-patient" data-patient-id="${escapeHtml(person.id)}">Start workflow</button></td></tr>`).join('');
  return `${pageHead('Local patient registry', 'Patient profiles', 'Demographic fields stay in browser storage and are not sent to the server.', `<button class="btn btn-primary" data-action="new-patient">＋ Add patient</button>`)}
    <div class="online-banner offline"><div class="banner-icon">▣</div><div class="banner-copy"><strong>Local-only patient information</strong><span>Names, age, pregnancy details, village, and consent status never leave this device. Synthetic fixtures can only be linked to a synthetic demo profile.</span></div></div>
    <div class="panel" style="margin-top:14px">${patients.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Name (local)</th><th>Pseudonymous ID</th><th>Age</th><th>Sex</th><th>Profile type</th><th>Screenings</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : emptyState('♙', 'No local profiles', 'Add a synthetic demo profile or a consented local-only profile.')}</div>
    ${safetyBlock('The patient registry is a prototype convenience. It is not a compliant EHR; avoid entering real identifiable health data in a shared or unmanaged device.')}`;
}

async function renderHistory() {
  const records = [...await store.getAll('screenings')].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const filtered = records.filter((record) => {
    const term = state.search.toLowerCase();
    const matchesText = !term || `${record.id} ${record.patient?.patient_id} ${record.result?.case_label} ${record.result?.risk_category}`.toLowerCase().includes(term);
    const matchesType = state.filter === 'all' || record.result?.screening_type === state.filter;
    return matchesText && matchesType;
  });
  return `${pageHead('Local audit trail', 'Screening history', 'Saved screening fixtures and sync state. Names and photos are never shown in this history table.', `<div class="search-bar"><label class="screen-reader" for="historySearch">Search local history</label><input id="historySearch" type="search" placeholder="Search ID or demo case…" value="${escapeHtml(state.search)}"></div>`)}
    <div class="row-between" style="margin-bottom:13px;flex-wrap:wrap"><div class="tabs-row"><button class="filter-tab ${state.filter === 'all' ? 'active' : ''}" data-filter="all">All workflows</button><button class="filter-tab ${state.filter === 'maternal_anemia' ? 'active' : ''}" data-filter="maternal_anemia">Maternal anemia</button><button class="filter-tab ${state.filter === 'neonatal_jaundice' ? 'active' : ''}" data-filter="neonatal_jaundice">Neonatal jaundice</button></div><span class="badge badge-blue">${filtered.length} LOCAL RESULT${filtered.length === 1 ? '' : 'S'}</span></div>
    <div class="panel">${recordRows(filtered, 'No records match this search. Start a synthetic demonstration to create a sample.')}</div>
    <div class="card-note" style="margin-top:13px">${records.length} record(s) stored in this browser. For a queued item, review the pseudonymous sync data in Sync queue before connecting.</div>`;
}

async function renderSync() {
  const queue = [...await store.getAll('syncQueue')].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  const synced = (await store.getAll('screenings')).filter((record) => record.sync_status === 'synced');
  return `${pageHead('Offline-first operations', 'Sync queue', 'Sync is idempotent and sends pseudonymous patient IDs plus synthetic fixture metadata. Image pixels and patient names are excluded.', `<button class="btn btn-primary" data-action="sync-now" ${queue.length ? '' : 'disabled'}>⇄ Sync ${queue.length || ''} queued record${queue.length === 1 ? '' : 's'}</button>`)}
    <div class="sync-flow"><div class="sync-stage"><div class="stage-icon">◉</div><strong>Camera / browser</strong><span>Image stays on device</span></div><span class="sync-arrow">→</span><div class="sync-stage"><div class="stage-icon">▣</div><strong>IndexedDB</strong><span>${queue.length} queued locally</span></div><span class="sync-arrow">→</span><div class="sync-stage"><div class="stage-icon">☁</div><strong>FastAPI</strong><span>${state.simulateOffline || !navigator.onLine ? 'Offline mode' : 'Connect when ready'}</span></div></div>
    <div class="card-grid grid-2"><div class="panel panel-pad"><div class="row-between"><h2 style="margin:0;color:var(--navy);font-size:13px">Pending records</h2><span class="badge ${queue.length ? 'badge-amber' : 'badge-green'}">${queue.length} QUEUED</span></div><div style="margin-top:10px">${queue.length ? recordRows(queue, 'Nothing waiting to sync.') : emptyState('✓', 'Queue is clear', 'New screenings created offline will appear here after save.')}</div></div>
      <div class="panel panel-pad"><h2 style="margin:0;color:var(--navy);font-size:13px">Connectivity simulation</h2><p style="color:var(--body);font-size:9px">Turn this switch on to force local-only mode even while connected, then test retry-safe sync.</p><label class="toggle"><input type="checkbox" id="simulateOffline" ${state.simulateOffline ? 'checked' : ''}><span class="toggle-track"></span><span>Simulate offline</span></label><hr class="divider"><div class="signal-row"><span>Browser IndexedDB</span><strong id="storageStatus">Checking…</strong></div><div class="signal-row" style="margin-top:8px"><span>Network state</span><strong>${navigator.onLine ? 'BROWSER ONLINE' : 'BROWSER OFFLINE'}</strong></div><div class="signal-row" style="margin-top:8px"><span>Successfully synced locally</span><strong>${synced.length}</strong></div></div></div>
    ${safetyBlock('This sync service is a demo store and is not an approved health-record exchange. Use pseudonymous synthetic records only.')}`;
}

async function renderPHC() {
  let server = null; let serverError = '';
  try {
    const [dashboardResponse, referralResponse] = await Promise.all([apiRequest('/api/dashboard', { timeout: 1800 }), apiRequest('/api/referrals', { timeout: 1800 })]);
    server = await dashboardResponse.json(); state.remoteReferrals = await referralResponse.json();
  } catch (error) { serverError = error.message; state.remoteReferrals = []; }
  const records = server?.records || [...await store.getAll('screenings')].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 100);
  const refs = server ? (state.remoteReferrals || []) : await store.getAll('referrals');
  const total = server?.total_screenings ?? records.length;
  const referralsCount = server?.referrals ?? refs.length;
  const syncedLabel = server ? 'API / SQLite demo' : 'Local browser only';
  return `${pageHead('De-identified demo operations', 'PHC dashboard', 'Prototype view of synthetic, pseudonymous records only. Not an EHR, population report, or clinical triage queue.', `<button class="btn btn-secondary" data-action="refresh-phc">↻ Refresh</button>`)}
    <div class="online-banner ${server ? '' : 'offline'}"><div class="banner-icon">▤</div><div class="banner-copy"><strong>${server ? 'FastAPI dashboard connected' : 'Showing local-only records'}</strong><span>${server ? 'Server data is pseudonymous and synthetic.' : `API unavailable or offline (${escapeHtml(serverError || 'no connection')}). Local records remain accessible.`} Data source: ${syncedLabel}.</span></div></div>
    <div class="card-grid grid-4" style="margin-top:14px"><div class="panel stat-card"><div class="stat-top"><span class="stat-label">Demo records</span><span class="stat-icon">◷</span></div><div class="stat-number">${total}</div><div class="stat-caption">Synthetic only</div></div><div class="panel stat-card stat-warning"><div class="stat-top"><span class="stat-label">Referral briefs</span><span class="stat-icon">⇧</span></div><div class="stat-number">${referralsCount}</div><div class="stat-caption">Not clinical referrals</div></div><div class="panel stat-card"><div class="stat-top"><span class="stat-label">Queued sync</span><span class="stat-icon">⇄</span></div><div class="stat-number">${(await store.getAll('syncQueue')).length}</div><div class="stat-caption">On this device</div></div><div class="panel stat-card"><div class="stat-top"><span class="stat-label">Today (UTC server)</span><span class="stat-icon">▦</span></div><div class="stat-number">${server?.today_screenings ?? '—'}</div><div class="stat-caption">Not a population statistic</div></div></div>
    <div class="section-title-row"><div><h2>Screening records</h2><p>Patient ID only · no name or image · synthetic output</p></div></div><div class="panel">${recordRows(records, 'No server records are available yet.')}</div>
    <div class="section-title-row"><div><h2>Referral brief queue</h2><p>Prototype-generated paperwork for clinician review; not a diagnosis</p></div></div><div class="panel panel-pad">${refs.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Brief ID</th><th>Screening ID</th><th>Created</th><th></th></tr></thead><tbody>${refs.map((ref) => `<tr><td class="table-strong">${escapeHtml(ref.id)}</td><td>${escapeHtml(ref.screening_id || ref.payload?.screening?.id || '—')}</td><td>${escapeHtml(dateLabel(ref.created_at))}</td><td><a class="btn btn-secondary btn-sm" href="/api/referrals/${encodeURIComponent(ref.id)}/pdf" target="_blank" rel="noopener">PDF</a></td></tr>`).join('')}</tbody></table></div>` : emptyState('▤', 'No referral briefs yet', 'Create one from a synthetic demo result to see it here.')}</div>
    ${safetyBlock('This dashboard is an engineering demo. Do not use aggregate counts for clinical, service-planning, or public-health decisions.')}`;
}

function renderArchitecture() {
  return `${pageHead('System design', 'Architecture & optical pipeline', 'An honest walkthrough of what runs locally, what is simulated, and where a future validated model would attach.', `<button class="btn btn-secondary" data-action="refresh-pipeline">Check live status</button>`)}
    <div class="panel panel-pad"><div class="model-banner"><div>ⓘ</div><div><strong>Current build: PWA + FastAPI prototype</strong><span>Native APK, Camera2 bridge, MediaPipe landmarks, and a clinically approved TFLite model are not included or build-verified in this workspace.</span></div></div>
      <div class="pipeline-list">${[['◉','Capture','Browser local'],['⌖','ROI','Manual guide'],['▣','Quality','Measured proxy'],['◈','Features','RGB · HSV · Lab'],['◇','Inference','Fixed fixture'],['♡','Care action','Local guidance']].map((item, i) => `<div class="pipeline-node ${i < 3 ? 'done' : i === 4 ? 'current' : ''}"><div class="node-icon">${item[0]}</div><strong>${item[1]}</strong><span>${item[2]}</span></div>`).join('')}</div>
      <div class="component-grid"><article class="component-card"><div class="component-icon">◉</div><h3>Browser camera & local import</h3><p>getUserMedia or a user-picked file; frames are not sent to the backend or saved alongside the record.</p></article><article class="component-card"><div class="component-icon">⌖</div><h3>Manual ROI guide</h3><p>Static conjunctiva/sclera guide only. No face detector, MediaPipe landmark, or anatomical segmentation model is bundled.</p></article><article class="component-card"><div class="component-icon">▣</div><h3>Quality gate</h3><p>Locally estimates brightness and edge/blur proxy. User confirms the target region; no clinical capture standard is claimed.</p></article><article class="component-card"><div class="component-icon">◈</div><h3>Optical feature utility</h3><p>Exploratory RGB, HSV, approximate Lab, YCrCb and channel ratios; camera ISP, white balance and color remain uncalibrated.</p></article><article class="component-card"><div class="component-icon">◇</div><h3>Inference boundary</h3><p>Demo result comes from a named fixture. Feature vectors do not feed an Hb or bilirubin estimator. TFLite interface is replaceable but not active.</p></article><article class="component-card"><div class="component-icon">⇄</div><h3>Offline persistence & sync</h3><p>IndexedDB queue with localStorage fallback. Retry-safe FastAPI/SQLite demo sync carries a pseudonymous ID and synthetic case only.</p></article></div>
    </div>
    <div class="card-grid grid-2" style="margin-top:14px"><div class="panel panel-pad"><h2 style="font-size:13px;color:var(--navy);margin:0 0 10px">Current data boundary</h2><div class="timeline"><div class="timeline-row"><div class="timeline-time">Camera frame</div><div class="timeline-line"><span class="timeline-dot"></span></div><div class="timeline-copy"><strong>Remains in browser memory</strong><span>Not stored in the record and not posted to FastAPI/Gemini.</span></div></div><div class="timeline-row"><div class="timeline-time">Patient profile</div><div class="timeline-line"><span class="timeline-dot"></span></div><div class="timeline-copy"><strong>IndexedDB on device</strong><span>Names and demographics stay local; no phone field is collected.</span></div></div><div class="timeline-row"><div class="timeline-time">Sync API</div><div class="timeline-line"><span class="timeline-dot"></span></div><div class="timeline-copy"><strong>Pseudonymous synthetic demo record only</strong><span>Server regenerates FHIR representation and does not accept image upload.</span></div></div></div></div>
      <div class="panel panel-pad"><h2 style="font-size:13px;color:var(--navy);margin:0 0 10px">Performance evidence</h2><div class="safety-note"><strong>No performance claims are measured.</strong><br>There is no validated model, benchmark harness, target-device trace, latency result, memory profile, or APK build evidence in this prototype. Any future values must be measured on named hardware and labeled by sample size and method.</div><div class="card-note" style="margin-top:11px">Engineering objectives: offline completion, fast quality feedback, low-memory image downsampling, and predictable sync. These are goals, not observed results.</div></div></div>`;
}

async function renderModel() {
  let status = null;
  try { status = await (await apiRequest('/api/model/status', { timeout: 1500 })).json(); } catch { /* local facts remain */ }
  const metrics = status?.research_baseline?.metrics || {};
  return `${pageHead('Evidence & limitations', 'Model and dataset audit', 'A candid inventory of the available data, exploratory baseline, and the active synthetic inference path.', `<button class="btn btn-secondary" data-action="refresh-model">↻ Refresh</button>`)}
    <div class="model-banner"><div>⚠</div><div><strong>Active screening model: none</strong><span>All displayed values are deterministic synthetic fixtures. No estimate is computed from camera pixels, and no TFLite model is approved or bundled.</span></div></div>
    <div class="card-grid grid-2" style="margin-top:14px"><section class="panel panel-pad"><div class="row-between"><h2 style="font-size:13px;color:var(--navy);margin:0">Exploratory anemia color baseline</h2><span class="badge badge-amber">RESEARCH ONLY · DISABLED</span></div><p style="color:var(--body);font-size:9px">Five-fold subject-grouped Ridge regression on three precomputed RGB percentage features in a 104-row shared CSV. It is not an image model, external validation, or patient-level evidence.</p>
      <div class="result-metrics"><div class="metric-card"><span>MAE · exploratory</span><strong>${metrics.mae_g_dl ?? '1.5041'}</strong><em>g/dL internal grouped split</em></div><div class="metric-card"><span>RMSE · exploratory</span><strong>${metrics.rmse_g_dl ?? '1.9392'}</strong><em>g/dL internal grouped split</em></div><div class="metric-card"><span>R² · exploratory</span><strong>${metrics.r2 ?? '0.3987'}</strong><em>Not clinical performance</em></div></div>
      <div class="card-note" style="margin-top:11px">n=104 rows / 104 groups. Direct names were excluded from model inputs and output artifact. Dataset licensing, consent, provenance, and clinical suitability are unverified. The artifact is never used by the demo.</div></section>
      <section class="panel panel-pad"><div class="row-between"><h2 style="font-size:13px;color:var(--navy);margin:0">Neonatal jaundice archive</h2><span class="badge badge-gray">NO LABELED MODEL</span></div><p style="color:var(--body);font-size:9px">The inspected ZIP contained 478 JPEGs: 239 Forehead and 239 Sternum. No serum bilirubin label table was found in that archive.</p><div class="kpi-strip"><div><strong>478</strong><span>JPEG images</span></div><div><strong>239 / 239</strong><span>Forehead / sternum</span></div><div><strong>0</strong><span>Label tables found</span></div></div><div class="card-note" style="margin-top:11px">No jaundice model or performance result was trained/reported from these images. The fixture estimates shown in this prototype are synthetic only.</div></section></div>
    <div class="section-title-row"><div><h2>What is and is not in this build</h2><p>Transparency is a feature, not a footnote.</p></div></div><div class="component-grid"><article class="component-card"><div class="component-icon">✓</div><h3>Present</h3><p>Deterministic demo fixtures, browser quality/feature utilities, local store, FastAPI schemas and SQLite interface.</p></article><article class="component-card"><div class="component-icon">×</div><h3>Not present</h3><p>Approved TFLite model, native Camera2 implementation, bilirubin labels, clinical validation, target-phone benchmark.</p></article><article class="component-card"><div class="component-icon">↗</div><h3>Further review required</h3><p>Drive data consent, license, label provenance, fairness, device camera variation, ethics, and clinical protocol fit.</p></article></div>
    <div class="card-note" style="margin-top:14px">See <a href="/docs/dataset-audit.md" target="_blank" rel="noopener">dataset audit</a> in the repository. The audit records grouped internal metrics and reproducibility boundaries.</div>
    ${safetyBlock('The exploratory coefficients are disabled research material. They must never be used to screen or treat a person.')}`;
}

async function renderSettings() {
  const storage = await store.localStoreStatus();
  return `${pageHead('Device & worker settings', 'Settings', 'Worker profile and app preferences are stored locally. No Gemini key is accepted by or included in the browser.', `<button class="btn btn-secondary" data-action="export-backup">↓ Export local backup</button>`)}
    <div class="card-grid grid-2"><section class="panel panel-pad"><h2 style="font-size:13px;color:var(--navy);margin:0 0 12px">Worker profile · local only</h2><form id="settingsForm"><div class="form-grid"><div class="form-field"><label for="workerName">Display name</label><input id="workerName" class="input" name="workerName" maxlength="80" value="${escapeHtml(state.workerName)}" autocomplete="name"></div><div class="form-field"><label for="phcName">PHC / location label</label><input id="phcName" class="input" name="phc" maxlength="80" value="${escapeHtml(state.phc)}"></div><div class="form-field full"><label for="languageSelect">Interface / counselling language</label><select id="languageSelect" class="select" name="language">${LANGUAGES.map((item) => `<option value="${item.id}" ${state.language === item.id ? 'selected' : ''}>${escapeHtml(item.label)} · ${escapeHtml(item.native)}</option>`).join('')}</select></div></div><div class="row" style="margin-top:14px"><button class="btn btn-primary" type="submit">Save local settings</button></div></form>
      <hr class="divider"><label class="toggle"><input type="checkbox" id="simulateOfflineSettings" ${state.simulateOffline ? 'checked' : ''}><span class="toggle-track"></span><span>Simulate offline mode</span></label><p style="font-size:8px;color:var(--muted);margin:6px 0 0">Affects app network requests only; does not disable your device network.</p></section>
      <section class="panel panel-pad"><h2 style="font-size:13px;color:var(--navy);margin:0 0 10px">Privacy & storage</h2><div class="signal-list"><div class="signal-row"><span>Browser store</span><strong>${storage.indexedDb ? 'INDEXEDDB' : 'LOCALSTORAGE FALLBACK'}</strong></div><div class="signal-row"><span>Store name</span><strong>${escapeHtml(storage.name)}</strong></div><div class="signal-row"><span>Camera/photo upload</span><strong>DISABLED</strong></div><div class="signal-row"><span>Gemini key</span><strong>SERVER ENV ONLY</strong></div><div class="signal-row"><span>Raw Drive data included</span><strong>NO</strong></div></div><div class="callout" style="margin-top:12px">If enabled by the operator, the Gemini API key is read from the backend environment variable <code>GEMINI_API_KEY</code>. Never paste a key into this screen, a client bundle, or the chat.</div><div class="row" style="margin-top:15px"><button class="btn btn-danger-soft" data-action="clear-local-data">Clear all local app data</button></div></section></div>
    <div class="panel panel-pad" style="margin-top:14px"><h2 style="font-size:13px;color:var(--navy);margin:0 0 7px">Safety and support</h2><p style="font-size:9px;color:var(--body);margin:0 0 8px">This is a hackathon prototype—not a medical device or approved EHR. Do not use synthetic estimates for care decisions. Confirm with appropriate testing and qualified clinicians.</p><div class="row" style="flex-wrap:wrap"><button class="btn btn-secondary btn-sm" data-page="architecture">Architecture & boundary</button><button class="btn btn-secondary btn-sm" data-page="model">Dataset audit & evidence</button><button class="btn btn-secondary btn-sm" data-page="sync">Sync queue</button></div></div>`;
}

async function render() {
  setHeader();
  const content = $('#mainContent');
  if (!content) return;
  try {
    switch (state.page) {
      case 'new': content.innerHTML = renderWizard(); break;
      case 'result': content.innerHTML = renderResult(); break;
      case 'patients': content.innerHTML = await renderPatients(); break;
      case 'history': content.innerHTML = await renderHistory(); break;
      case 'sync': content.innerHTML = await renderSync(); break;
      case 'phc': content.innerHTML = await renderPHC(); break;
      case 'architecture': content.innerHTML = renderArchitecture(); break;
      case 'model': content.innerHTML = await renderModel(); break;
      case 'settings': content.innerHTML = await renderSettings(); break;
      default: state.page = 'home'; content.innerHTML = await renderHome();
    }
    if (state.page === 'sync') refreshStorageStatus();
  } catch (error) {
    content.innerHTML = `${pageHead('Application', 'Something needs attention', 'The local workflow is still protected; review the error and try again.')}<div class="safety-note">${escapeHtml(error.message || 'Unknown application error.')}</div>`;
  }
  $('#sidebar')?.classList.remove('open');
  $('#mainContent')?.focus({ preventScroll: true });
}

async function refreshStorageStatus() {
  const status = await store.localStoreStatus();
  const element = $('#storageStatus');
  if (element) element.textContent = status.indexedDb ? 'INDEXEDDB READY' : 'LOCALSTORAGE FALLBACK';
}

function selectDemoPatientForType(type) {
  const current = selectedPatient();
  if (current && !current.isDemo) return;
  const kind = type === 'neonatal_jaundice' ? 'newborn' : 'maternal';
  const matching = state.patients.find((person) => person.isDemo && person.demoKind === kind);
  if (matching) state.selectedPatientId = matching.id;
}

function startNew(type = null, patientId = null) {
  stopCamera();
  state.page = 'new'; state.wizardStep = 1;
  state.screeningType = type || 'maternal_anemia';
  if (patientId) state.selectedPatientId = patientId;
  else selectDemoPatientForType(state.screeningType);
  state.selectedCaseId = '';
  state.previewDataUrl = ''; state.imageData = null; state.captureSource = '';
  state.syntheticImage = false; state.regionConfirmed = false; state.quality = null;
  state.opticalFeatures = null; state.ambientResult = null; state.captureAudit = null;
  state.lastRecord = null; state.counselling = null; state.referral = null;
  render();
}

function stopCamera() {
  if (state.cameraStream) state.cameraStream.getTracks().forEach((track) => track.stop());
  state.cameraStream = null; state.cameraActive = false;
}

async function setLocalImage(imageData, dataUrl, source, synthetic = false) {
  state.imageData = imageData;
  state.previewDataUrl = dataUrl;
  state.captureSource = source;
  state.syntheticImage = synthetic;
  state.regionConfirmed = synthetic;
  state.quality = assessImageQuality(imageData, { regionConfirmed: synthetic, synthetic, regionLabel: regionLabelForType(state.screeningType) });
  try { state.opticalFeatures = extractOpticalFeatures(imageData, state.screeningType === 'neonatal_jaundice' ? 'manual-sclera-guide' : 'manual-conjunctiva-guide'); }
  catch { state.opticalFeatures = null; }
  state.ambientResult = correctAmbientLight(imageData, null, { synthetic });
  state.captureAudit = { source, synthetic, quality: state.quality, regionConfirmed: state.regionConfirmed, features: state.opticalFeatures };
  state.selectedCaseId = state.selectedCaseId || getDemoCases(state.screeningType)[0]?.id || '';
  stopCamera();
  await render();
}

async function openCamera() {
  if (!navigator.mediaDevices?.getUserMedia) { toast('Camera API is unavailable here. Choose a local image or synthetic fixture.', 'warning'); return; }
  state.previewDataUrl = ''; state.imageData = null; state.captureSource = ''; state.syntheticImage = false;
  state.regionConfirmed = false; state.quality = null; state.opticalFeatures = null; state.captureAudit = null;
  try {
    state.cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    state.cameraActive = true;
    await render();
    const video = $('#liveVideo');
    if (video) { video.srcObject = state.cameraStream; await video.play().catch(() => {}); }
    toast('Camera preview is local to this browser. No image upload is enabled.');
  } catch (error) { stopCamera(); toast(`Camera unavailable: ${error.message || 'permission denied'}. Use a local image or demo fixture.`, 'warning'); }
}

async function captureFrame() {
  const video = $('#liveVideo');
  if (!video || !video.videoWidth || !state.cameraStream) { toast('Wait for the camera preview, then capture.', 'warning'); return; }
  const canvas = document.createElement('canvas');
  const scale = Math.min(1, 960 / video.videoWidth);
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  canvas.getContext('2d', { willReadFrequently: true }).drawImage(video, 0, 0, canvas.width, canvas.height);
  const imageData = canvas.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, canvas.width, canvas.height);
  await setLocalImage(imageData, canvas.toDataURL('image/jpeg', 0.76), 'CAMERA_LOCAL', false);
  toast('Frame captured to local memory; it is not uploaded or saved with the record.');
}

async function openLocalFile(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) { toast('Choose an image file.', 'error'); return; }
  if (file.size > 15 * 1024 * 1024) { toast('Image is over 15 MB. Choose a smaller image to protect device memory.', 'warning'); return; }
  try {
    let bitmap;
    if ('createImageBitmap' in window) bitmap = await createImageBitmap(file);
    else {
      const url = URL.createObjectURL(file); const image = new Image();
      await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
      bitmap = image; bitmap._abnObjectUrl = url;
    }
    const scale = Math.min(1, 960 / bitmap.width, 720 / bitmap.height);
    const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext('2d', { willReadFrequently: true }); ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL('image/jpeg', 0.78);
    bitmap.close?.(); if (bitmap._abnObjectUrl) URL.revokeObjectURL(bitmap._abnObjectUrl);
    await setLocalImage(imageData, url, 'LOCAL_IMPORT', false);
    toast('Image analyzed in this browser only. Raw pixels were not stored with the screening.');
  } catch (error) { toast(`Could not read image: ${error.message || 'unsupported format'}.`, 'error'); }
}

async function useSyntheticImage() {
  const canvas = document.createElement('canvas');
  createSyntheticImage(canvas, state.screeningType, state.selectedCaseId || 'case-a');
  await setLocalImage(imageDataFromCanvas(canvas, 0.65), canvas.toDataURL('image/png'), 'ABSTRACT_SYNTHETIC_FIXTURE', true);
  toast('Abstract synthetic pixels loaded. This is not a patient photograph.');
}

async function runSelectedScreening() {
  const patient = selectedPatient();
  if (!patient?.isDemo) { toast('Synthetic fixtures cannot be attached to a real/local patient profile.', 'error'); return; }
  const expectedDemoKind = state.screeningType === 'neonatal_jaundice' ? 'newborn' : 'maternal';
  if (patient.demoKind && patient.demoKind !== expectedDemoKind) {
    toast(`Choose the matching ${expectedDemoKind === 'newborn' ? 'newborn' : 'maternal'} synthetic demo profile for this workflow.`, 'error'); return;
  }
  if (!state.syntheticImage) { toast('A real camera/import image is for local quality/features only. Select the abstract synthetic image for a disconnected fixture demo.', 'error'); return; }
  if (!state.quality?.ready) { toast('Complete the local quality gate before continuing.', 'warning'); return; }
  if (!state.selectedCaseId) { toast('Select a named synthetic demo case first.', 'warning'); return; }
  const result = runDemoInference(state.screeningType, state.selectedCaseId);
  const id = `scr-${uid()}`;
  const recordBase = {
    id, patient: { patient_id: patient.id, demo: true }, result,
    worker_id: 'demo-worker', phc: 'Demo PHC', village: null,
    created_at: result.generated_at, sync_status: 'queued', fhir_bundle: null,
  };
  let record = recordBase;
  let synced = false;
  if (!state.simulateOffline && navigator.onLine) {
    try {
      const response = await apiRequest('/api/screenings', { method: 'POST', body: JSON.stringify({
        id, patient: { patient_id: patient.id, demo: true }, screening_type: state.screeningType,
        case_id: state.selectedCaseId, worker_id: 'demo-worker', phc: 'Demo PHC',
      }), timeout: 5000 });
      record = await response.json(); synced = true;
    } catch { /* Save locally and queue; network/API failure must not block the demonstration. */ }
  }
  record.sync_status = synced ? 'synced' : 'queued';
  record.capture_audit = state.captureAudit ? {
    source: state.captureAudit.source, synthetic: Boolean(state.captureAudit.synthetic),
    regionConfirmed: Boolean(state.captureAudit.regionConfirmed),
    quality: state.captureAudit.quality ? {
      qualityScore: state.captureAudit.quality.qualityScore,
      brightness: state.captureAudit.quality.brightness,
      blurScore: state.captureAudit.quality.blurScore,
    } : null,
  } : null;
  if (!record.fhir_bundle) record.fhir_bundle = buildFhirBundle({ id: patient.id, name: patient.name, sex: patient.sex, village: patient.village }, result, { phc: state.phc }, id);
  await store.put('screenings', record);
  if (!synced) await store.put('syncQueue', record);
  state.lastRecord = record; state.page = 'result'; state.referral = null;
  state.counselling = localCounsel(state.screeningType, state.language, result.risk_category);
  state.lastCounselLanguage = state.language;
  await render();
  void loadCounselling(record);
  toast(synced ? 'Synthetic demo screening saved to the local device and demo API.' : 'Synthetic demo screening saved locally and added to the sync queue.', synced ? 'success' : 'warning');
}

async function loadCounselling(record) {
  const language = state.language;
  const fallback = localCounsel(record.result.screening_type, language, record.result.risk_category);
  state.counselling = fallback; state.lastCounselLanguage = language;
  try {
    const person = state.patients.find((item) => item.id === record.patient?.patient_id);
    const response = await apiRequest('/api/counselling', { method: 'POST', timeout: 7000, body: JSON.stringify({
      screening_type: record.result.screening_type, estimate: record.result.estimate, unit: record.result.unit,
      risk_category: record.result.risk_category, confidence: record.result.confidence, quality_score: record.result.quality_score,
      language, pregnancy: person?.pregnancy ?? null, gestational_week: person?.gestationalWeek || null,
      infant_age_hours: person?.infantAgeHours ?? null,
    }) });
    const data = await response.json();
    if (state.page === 'result' && state.lastRecord?.id === record.id && state.language === language) { state.counselling = data; await render(); }
  } catch { /* deterministic local copy remains visible */ }
}

function openRecord(recordId) {
  store.getOne('screenings', recordId).then(async (record) => {
    if (!record) { toast('Local record not found.', 'error'); return; }
    state.lastRecord = record; state.page = 'result'; state.referral = null;
    state.counselling = localCounsel(record.result.screening_type, state.language, record.result.risk_category);
    await render(); void loadCounselling(record);
  });
}

async function openNewPatient() {
  const modal = $('#modalRoot');
  modal.innerHTML = `<div class="modal"><div class="modal-head"><div><h2>Add a local patient profile</h2><p>Details stay in this browser and are not synchronized.</p></div><button class="modal-close" data-action="close-modal" aria-label="Close">×</button></div>
    <form id="patientModalForm"><div class="form-grid"><div class="form-field"><label for="newPatientName">Display name</label><input class="input" id="newPatientName" name="name" maxlength="80" required placeholder="Demo person"></div><div class="form-field"><label for="newPatientAge">Age (years)</label><input class="input" id="newPatientAge" name="age" type="number" min="0" max="120" required></div><div class="form-field"><label for="newPatientSex">Sex</label><select class="select" id="newPatientSex" name="sex"><option value="unknown">Prefer not to say</option><option value="female">Female</option><option value="male">Male</option></select></div><div class="form-field"><label for="newPatientVillage">Village / locality · local only</label><input class="input" id="newPatientVillage" name="village" maxlength="80"></div><div class="form-field"><label for="newPatientPregnancy">Pregnancy</label><select class="select" id="newPatientPregnancy" name="pregnancy"><option value="false">Not applicable / not recorded</option><option value="true">Pregnant</option></select></div><div class="form-field"><label for="gestationalWeek">Gestational week (optional)</label><input class="input" id="gestationalWeek" name="gestationalWeek" type="number" min="1" max="45"></div><div class="form-field"><label for="infantAgeHours">Infant age in hours (optional)</label><input class="input" id="infantAgeHours" name="infantAgeHours" type="number" min="0" max="8760"></div></div>
    <hr class="divider"><label class="check-row"><input type="checkbox" name="demo" value="true" checked><span><strong>Synthetic demo profile</strong> — permits fixed fixture demonstrations, but never a clinical estimate.</span></label><label class="check-row" style="margin-top:9px"><input type="checkbox" name="consent" value="true" required><span>I have consent to store this local demo/profile information on this device.</span></label><div class="safety-note" style="margin-top:12px"><strong>Real/local profile selected?</strong> The prototype will only run image-quality and feature visualization. It will disable synthetic estimates for that profile.</div><div class="row-between" style="margin-top:15px"><button type="button" class="btn btn-secondary" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit">Save profile locally</button></div></form></div>`;
}

async function savePatientForm(form) {
  const data = new FormData(form);
  const isDemo = form.querySelector('[name="demo"]').checked;
  const hasConsent = form.querySelector('[name="consent"]').checked;
  if (!hasConsent) { toast('Consent is required to store a local profile.', 'warning'); return; }
  const id = await store.makePatientId();
  const patient = {
    id, name: String(data.get('name') || '').trim(), age: data.get('age') ? Number(data.get('age')) : null,
    sex: String(data.get('sex') || 'unknown'), pregnancy: data.get('pregnancy') === 'true',
    gestationalWeek: data.get('gestationalWeek') ? Number(data.get('gestationalWeek')) : null,
    infantAgeHours: data.get('infantAgeHours') !== '' ? Number(data.get('infantAgeHours')) : null,
    village: String(data.get('village') || '').trim(), phone: '', consent: hasConsent,
    isDemo, demoKind: isDemo ? (data.get('infantAgeHours') !== '' ? 'newborn' : 'maternal') : null,
    createdAt: new Date().toISOString(),
  };
  await store.put('patients', patient);
  state.patients = await store.getAll('patients'); state.selectedPatientId = patient.id;
  $('#modalRoot').innerHTML = '';
  toast('Patient profile stored locally on this device.');
  await render();
}

async function syncNow() {
  const queue = await store.getAll('syncQueue');
  if (!queue.length) { toast('There are no queued records to sync.'); return; }
  if (state.simulateOffline || !navigator.onLine) { toast('Offline mode is active. The queue remains safely on this device.', 'warning'); return; }
  let sent = 0;
  try {
    for (let offset = 0; offset < queue.length; offset += 100) {
      const batch = queue.slice(offset, offset + 100).map((record) => ({
        id: record.id, patient: record.patient, result: record.result, worker_id: record.worker_id,
        phc: record.phc, village: null, created_at: record.created_at, sync_status: 'queued', fhir_bundle: null,
      }));
      const response = await apiRequest('/api/sync', { method: 'POST', body: JSON.stringify({ records: batch }), timeout: 10000 });
      const result = await response.json(); sent += result.accepted + result.duplicate;
      for (const item of queue.slice(offset, offset + 100)) {
        await store.remove('syncQueue', item.id);
        const saved = await store.getOne('screenings', item.id);
        if (saved) { saved.sync_status = 'synced'; await store.put('screenings', saved); }
      }
    }
    toast(`${sent} synthetic record(s) synchronized. No photos or patient names were sent.`);
  } catch (error) { toast(`Sync paused; queued records remain local. ${error.message}`, 'warning'); }
  updateNetworkChip(); await render();
}

function minimalServerRecord(record) {
  return {
    id: record.id, patient: record.patient, result: record.result, worker_id: record.worker_id || 'demo-worker',
    phc: record.phc || 'Demo PHC', village: null, created_at: record.created_at,
    sync_status: record.sync_status || 'queued', fhir_bundle: null,
  };
}

async function createReferral() {
  const record = state.lastRecord;
  if (!record) { toast('Open a screening result first.', 'warning'); return; }
  const language = state.language;
  const counsel = state.counselling || localCounsel(record.result.screening_type, language, record.result.risk_category);
  const id = `ref-${uid()}`;
  const referral = {
    id, screening_id: record.id, screening: record, worker_name: state.workerName,
    language, counselling: counsel.counselling_script || counsel.script || '',
    next_step: counsel.recommended_next_step || counsel.action || 'Confirm with appropriate clinical testing and local protocol.',
    created_at: new Date().toISOString(), pdfUrl: '',
  };
  await store.put('referrals', referral);
  try {
    const response = await apiRequest('/api/referrals', { method: 'POST', body: JSON.stringify({
      id, screening: minimalServerRecord(record), worker_name: state.workerName, language,
      counselling: referral.counselling, next_step: referral.next_step,
    }), timeout: 7000 });
    const created = await response.json(); referral.pdfUrl = created.pdf_url; referral.serverCreated = true;
    await store.put('referrals', referral);
    toast('Referral brief saved. Use the server PDF link or print/save locally.');
  } catch (error) {
    referral.serverCreated = false; await store.put('referrals', referral);
    toast('Referral brief saved locally. Use Print / Save PDF while offline.', 'warning');
  }
  state.referral = referral; await render();
}

function printReferral() {
  const record = state.lastRecord;
  if (!record) { toast('Open a result before printing a referral.', 'warning'); return; }
  const popup = window.open('', '_blank', 'width=850,height=900');
  if (!popup) { toast('Popup blocked. Allow popups or use the server PDF link after creating a brief.', 'warning'); return; }
  popup.opener = null;
  const patient = state.patients.find((item) => item.id === record.patient?.patient_id);
  const counsel = state.counselling || localCounsel(record.result.screening_type, state.language, record.result.risk_category);
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>AbhayNayan · Referral Brief</title><style>body{font:14px/1.6 Arial,sans-serif;color:#18323a;max-width:760px;margin:34px auto;padding:0 22px}h1{color:#123642;font-size:23px;margin-bottom:3px}.sub{color:#657c81;font-size:12px;margin:0 0 22px}.grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #dce7e8}.item{padding:10px;border-bottom:1px solid #dce7e8}.label{display:block;color:#73888d;font-size:11px}.value{font-weight:700}.notice{margin-top:22px;padding:14px;background:#fff7e8;border-left:4px solid #d18b24}.foot{margin-top:18px;color:#657c81;font-size:11px}@media print{button{display:none}body{margin:0 auto}}</style></head><body><h1>ABHAYNAYAN · SCREENING REFERRAL BRIEF</h1><p class="sub">Prototype-generated summary for clinician review · not a diagnosis</p><div class="grid"><div class="item"><span class="label">Patient ID</span><span class="value">${escapeHtml(record.patient?.patient_id || patient?.id)}</span></div><div class="item"><span class="label">Patient name · local only</span><span class="value">${escapeHtml(patient?.name || 'Not recorded')}</span></div><div class="item"><span class="label">Screening workflow</span><span class="value">${escapeHtml(typeLabel(record.result.screening_type))}</span></div><div class="item"><span class="label">Date</span><span class="value">${escapeHtml(dateLabel(record.created_at))}</span></div><div class="item"><span class="label">Synthetic estimate · not a lab result</span><span class="value">${escapeHtml(localResultLabel(record))}</span></div><div class="item"><span class="label">Demo tag</span><span class="value">${escapeHtml(record.result.risk_category)}</span></div><div class="item"><span class="label">Model mode</span><span class="value">${escapeHtml(record.result.model_mode)} · fixed fixture</span></div><div class="item"><span class="label">Worker / PHC</span><span class="value">${escapeHtml(state.workerName)} · ${escapeHtml(state.phc)}</span></div></div><h2>Recommended next step</h2><p>${escapeHtml(counsel.recommended_next_step || counsel.action || 'Confirm with appropriate clinical testing and local protocol.')}</p><h2>Counselling summary</h2><p>${escapeHtml(counsel.counselling_script || counsel.script || '')}</p><div class="notice"><strong>Safety notice</strong><br>${escapeHtml(record.result.safety_note)} Do not use this demo value to diagnose, triage, delay care, or change treatment. Confirm with appropriate clinical testing and local protocol.</div><p class="foot">No camera image is included in this document. This prototype is not an approved health record or medical device.</p><button onclick="window.print()">Print / Save as PDF</button></body></html>`;
  popup.document.open(); popup.document.write(html); popup.document.close();
}

async function exportBackup() {
  const [patients, screenings, referrals] = await Promise.all([store.getAll('patients'), store.getAll('screenings'), store.getAll('referrals')]);
  const payload = { exported_at: new Date().toISOString(), app: 'AbhayNayan prototype', warning: 'May contain locally stored patient-profile information. Keep this backup private and encrypted.', patients, screenings, referrals };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `abhaynayan-local-backup-${new Date().toISOString().slice(0, 10)}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1500);
  toast('Local backup downloaded. Protect it as sensitive information.');
}

async function clearLocalData() {
  if (!window.confirm('Delete all patient profiles, screening records, referral briefs, and settings from this browser? This cannot be undone.')) return;
  stopCamera(); await store.clearAllLocalData();
  state.patients = []; state.selectedPatientId = ''; state.workerName = 'Demo ASHA Worker'; state.phc = 'Demo PHC · Bihta';
  state.language = 'en'; state.simulateOffline = false; state.lastRecord = null; state.referral = null;
  await store.ensureDemoPatient('maternal'); await store.ensureDemoPatient('newborn');
  state.patients = await store.getAll('patients');
  state.selectedPatientId = state.patients.find((person) => person.demoKind === 'maternal')?.id || state.patients[0]?.id || '';
  state.page = 'settings'; await render(); toast('Local app data cleared; fresh maternal and newborn demo profiles were created.');
}

async function handleClick(event) {
  const target = event.target.closest('button, a');
  if (!target) return;
  if (target.dataset.page) {
    event.preventDefault();
    if (target.dataset.page === 'new') { startNew(); return; }
    stopCamera(); state.page = target.dataset.page; await render(); return;
  }
  if (target.dataset.task) {
    state.screeningType = target.dataset.task;
    selectDemoPatientForType(state.screeningType);
    state.selectedCaseId = ''; await render(); return;
  }
  if (target.dataset.caseId) { state.selectedCaseId = target.dataset.caseId; await render(); return; }
  if (target.dataset.filter) { state.filter = target.dataset.filter; await render(); return; }
  if (target.dataset.langTab) { state.language = target.dataset.langTab; await store.setSetting('language', state.language); state.counselling = localCounsel(state.lastRecord?.result.screening_type || state.screeningType, state.language, state.lastRecord?.result.risk_category || 'DEMO_ONLY'); await render(); if (state.lastRecord) void loadCounselling(state.lastRecord); return; }
  if (target.dataset.screeningId) { openRecord(target.dataset.screeningId); return; }
  if (target.dataset.patientId && target.dataset.action === 'screen-patient') { state.selectedPatientId = target.dataset.patientId; startNew(null, target.dataset.patientId); return; }
  const action = target.dataset.action;
  switch (action) {
    case 'start-screening': startNew(); break;
    case 'start-maternal': startNew('maternal_anemia'); break;
    case 'start-jaundice': startNew('neonatal_jaundice'); break;
    case 'new-screening': startNew(); break;
    case 'new-patient': await openNewPatient(); break;
    case 'close-modal': $('#modalRoot').innerHTML = ''; break;
    case 'wizard-next':
      if (state.wizardStep === 1) {
        if (!selectedPatient() || !state.screeningType) { toast('Select a local patient and workflow.', 'warning'); break; }
        state.wizardStep = 2; await render();
      } else if (state.wizardStep === 2) {
        if (!state.quality?.ready) { toast('The image quality gate has not passed.', 'warning'); break; }
        state.wizardStep = 3; await render();
      }
      break;
    case 'wizard-back': state.wizardStep = Math.max(1, state.wizardStep - 1); await render(); break;
    case 'start-camera': await openCamera(); break;
    case 'capture-frame': await captureFrame(); break;
    case 'open-file': $('#imagePicker').click(); break;
    case 'synthetic-image': await useSyntheticImage(); break;
    case 'run-screening': await runSelectedScreening(); break;
    case 'sync-now': await syncNow(); break;
    case 'open-record': openRecord(target.dataset.screeningId); break;
    case 'download-fhir': {
      const record = state.lastRecord;
      if (!record) break;
      const patient = state.patients.find((item) => item.id === record.patient?.patient_id);
      const bundle = record.fhir_bundle || buildFhirBundle({ id: patient?.id, name: patient?.name, sex: patient?.sex, village: patient?.village }, record.result, { phc: state.phc }, record.id);
      downloadJson(bundle, `abhaynayan-${record.id}-fhir.json`); toast('FHIR R4-style prototype Bundle exported locally.'); break;
    }
    case 'create-referral': await createReferral(); break;
    case 'print-referral': printReferral(); break;
    case 'refresh-phc': case 'refresh-pipeline': case 'refresh-model': await render(); toast('View refreshed from currently reachable sources.'); break;
    case 'export-backup': await exportBackup(); break;
    case 'clear-local-data': await clearLocalData(); break;
    default: break;
  }
}

async function handleChange(event) {
  const target = event.target;
  if (target.id === 'patientSelect') { state.selectedPatientId = target.value; await render(); return; }
  if (target.id === 'regionConfirm') {
    state.regionConfirmed = target.checked;
    if (state.imageData) {
      state.quality = assessImageQuality(state.imageData, { regionConfirmed: state.regionConfirmed, synthetic: false, regionLabel: regionLabelForType(state.screeningType) });
      if (state.captureAudit) { state.captureAudit.quality = state.quality; state.captureAudit.regionConfirmed = state.regionConfirmed; }
    }
    await render(); return;
  }
  if (target.id === 'simulateOffline' || target.id === 'simulateOfflineSettings') {
    state.simulateOffline = target.checked; await store.setSetting('simulateOffline', state.simulateOffline); updateNetworkChip(); await render(); return;
  }
  if (target.id === 'languageSelect') { state.language = target.value; await store.setSetting('language', state.language); await render(); return; }
}

async function handleSubmit(event) {
  if (event.target.id === 'patientModalForm') { event.preventDefault(); await savePatientForm(event.target); return; }
  if (event.target.id === 'settingsForm') {
    event.preventDefault(); const data = new FormData(event.target);
    state.workerName = String(data.get('workerName') || 'Demo ASHA Worker').trim().slice(0, 80) || 'Demo ASHA Worker';
    state.phc = String(data.get('phc') || 'Demo PHC').trim().slice(0, 80) || 'Demo PHC';
    state.language = String(data.get('language') || 'en');
    await Promise.all([store.setSetting('workerName', state.workerName), store.setSetting('phc', state.phc), store.setSetting('language', state.language)]);
    toast('Settings saved locally.'); await render();
  }
}

async function initialize() {
  try {
    state.language = await store.getSetting('language', 'en');
    state.workerName = await store.getSetting('workerName', 'Demo ASHA Worker');
    state.phc = await store.getSetting('phc', 'Demo PHC · Bihta');
    state.simulateOffline = Boolean(await store.getSetting('simulateOffline', false));
    await store.ensureDemoPatient('maternal');
    await store.ensureDemoPatient('newborn');
    state.patients = await store.getAll('patients');
    state.selectedPatientId = state.patients.find((person) => person.isDemo && person.demoKind === 'maternal')?.id || state.patients.find((person) => person.isDemo)?.id || state.patients[0]?.id || '';
  } catch (error) { console.error('Local store initialization failed:', error); }
  document.addEventListener('click', (event) => { void handleClick(event); });
  document.addEventListener('change', (event) => { void handleChange(event); });
  document.addEventListener('submit', (event) => { void handleSubmit(event); });
  let historySearchTimer;
  document.addEventListener('input', (event) => {
    if (event.target.id !== 'historySearch') return;
    state.search = event.target.value;
    const cursor = event.target.selectionStart;
    clearTimeout(historySearchTimer);
    historySearchTimer = setTimeout(async () => {
      if (state.page !== 'history') return;
      await render();
      const input = $('#historySearch');
      if (input) { input.focus(); input.setSelectionRange(cursor, cursor); }
    }, 130);
  });
  $('#mobileMenu')?.addEventListener('click', () => $('#sidebar')?.classList.toggle('open')); 
  $('#languageButton')?.addEventListener('click', async () => {
    const index = LANGUAGES.findIndex((item) => item.id === state.language);
    state.language = LANGUAGES[(index + 1) % LANGUAGES.length].id;
    await store.setSetting('language', state.language);
    if (state.lastRecord) state.counselling = localCounsel(state.lastRecord.result.screening_type, state.language, state.lastRecord.result.risk_category);
    await render(); if (state.lastRecord) void loadCounselling(state.lastRecord);
  });
  $('#imagePicker')?.addEventListener('change', async (event) => { await openLocalFile(event.target.files?.[0]); event.target.value = ''; });
  window.addEventListener('online', () => { updateNetworkChip(); });
  window.addEventListener('offline', () => { updateNetworkChip(); });
  updateNetworkChip(); await render();
}

void initialize();
