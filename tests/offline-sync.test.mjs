// Offline outbox and sync semantics in the real PWA module, driven through JSDOM.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import { runDemoInference } from '../web-dashboard/js/inference.js';

const html = await fs.readFile(new URL('../web-dashboard/index.html', import.meta.url), 'utf8');
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const waitFor = async (check, label) => {
  for (let i = 0; i < 150; i += 1) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`Timed out waiting for ${label}`);
};

let boot = 0;
// Starts the app in a fresh DOM. `saved` carries localStorage across "restarts".
async function startApp(saved, fetchImpl) {
  const dom = new JSDOM(html, { url: 'http://localhost:8000/', pretendToBeVisual: true, runScripts: 'outside-only' });
  for (const [key, value] of Object.entries(saved)) dom.window.localStorage.setItem(key, value);
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.localStorage = dom.window.localStorage;
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
  dom.window.HTMLCanvasElement.prototype.getContext = () => ({
    createLinearGradient: () => ({ addColorStop() {} }), fillRect() {}, beginPath() {}, ellipse() {}, stroke() {}, fill() {}, fillText() {}, setLineDash() {}, drawImage() {},
    getImageData: (_x, _y, width, height) => ({ data: new Uint8ClampedArray(width * height * 4).map((_, i) => (i % 4 === 3 ? 255 : 150)), width, height }),
  });
  dom.window.HTMLCanvasElement.prototype.toDataURL = () => 'data:image/png;base64,AA==';
  globalThis.fetch = fetchImpl;
  boot += 1;
  await import(`../web-dashboard/js/app.js?offline-sync=${boot}`);
  await waitFor(() => document.querySelector('.hero-panel'), 'home');
  return dom;
}
function snapshot(dom) {
  const out = {};
  for (let i = 0; i < dom.window.localStorage.length; i += 1) { const key = dom.window.localStorage.key(i); out[key] = dom.window.localStorage.getItem(key); }
  return out;
}
const rows = (name) => JSON.parse(localStorage.getItem(`abn_${name}`) || '[]');
const click = (selector) => document.querySelector(selector).click();

async function runMaternalDemo() {
  click('[data-action="start-maternal"]');
  await waitFor(() => document.querySelector('#patientSelect'), 'step 1');
  click('[data-action="wizard-next"]');
  await waitFor(() => document.querySelector('[data-action="synthetic-image"]'), 'capture step');
  click('[data-action="synthetic-image"]');
  await waitFor(() => document.querySelector('[data-action="wizard-next"]')?.disabled === false, 'quality gate');
  click('[data-action="wizard-next"]');
  await waitFor(() => document.querySelector('[data-action="run-screening"]'), 'fixture step');
  click('[data-action="run-screening"]');
  await waitFor(() => document.querySelector('.result-hero'), 'result');
}

function apiMock(handlers) {
  const calls = [];
  const fetchImpl = async (path, options = {}) => {
    calls.push({ path, body: options.body ? JSON.parse(options.body) : null });
    if (path === '/api/health') return json({ status: 'ok' });
    if (path === '/api/counselling') return json({}, 503);
    const handler = handlers[path];
    if (!handler) throw new TypeError(`no route ${path}`);
    return handler(options.body ? JSON.parse(options.body) : null);
  };
  return { calls, fetchImpl };
}

test('outbox survives restart, failed sync keeps records, retry does not duplicate, conflicts are flagged', async () => {
  const doms = [];
  try {
    // 1. Server unreachable while screening: record is saved and queued with the failure reason.
    const down = apiMock({ '/api/screenings': () => { throw new TypeError('Failed to fetch'); } });
    doms.push(await startApp({}, down.fetchImpl));
    await runMaternalDemo();
    assert.match(document.querySelector('.provenance-banner').textContent, /Synthetic demo value/);
    assert.match(document.body.textContent, /No calibrated uncertainty is produced/);
    assert.equal(rows('syncQueue').length, 1);
    const queued = rows('syncQueue')[0];
    assert.equal(queued.sync_status, 'queued');
    assert.equal(queued.result.provenance, 'DEMO_SYNTHETIC');
    assert.equal(queued.result.confidence, null);
    assert.ok(queued.last_sync_error);

    // 2. Restart the app: the queued record is still there and counted.
    const saved = snapshot(doms.at(-1)); doms.at(-1).window.close();
    let syncCalls = 0;
    const flaky = apiMock({
      '/api/sync': (body) => {
        syncCalls += 1;
        if (syncCalls === 1) return json({ detail: 'down', error: { code: 'SERVICE_UNAVAILABLE', message: 'down', status: 503, retryable: true, fields: [] } }, 503);
        return json({ accepted: 1, duplicate: 0, conflict: 0, rejected: 0, synced_ids: [body.records[0].id], server_time: new Date().toISOString(),
          results: [{ id: body.records[0].id, status: 'accepted' }] });
      },
    });
    doms.push(await startApp(saved, flaky.fetchImpl));
    await waitFor(() => document.querySelector('#navPending')?.textContent === '1', 'pending count after restart');

    // 3. First sync fails with 503: nothing is deleted and the attempt is recorded.
    click('.nav-item[data-page="sync"]');
    await waitFor(() => document.querySelector('[data-action="sync-now"]:not([disabled])'), 'sync button');
    click('[data-action="sync-now"]');
    await waitFor(() => rows('syncQueue')[0]?.sync_attempts === 2, 'failed attempt recorded');
    assert.equal(rows('syncQueue').length, 1);
    assert.equal(rows('screenings')[0].sync_status, 'queued');

    // 4. Retry succeeds: exactly one record is acknowledged and removed from the outbox.
    await waitFor(() => document.querySelector('[data-action="sync-now"]:not([disabled])'), 'sync button again');
    click('[data-action="sync-now"]');
    await waitFor(() => rows('syncQueue').length === 0, 'queue drained');
    assert.equal(rows('screenings').length, 1);
    assert.equal(rows('screenings')[0].sync_status, 'synced');
    const sent = flaky.calls.filter((c) => c.path === '/api/sync').map((c) => c.body.records);
    assert.equal(sent.length, 2);
    assert.deepEqual(sent[0].map((r) => r.id), sent[1].map((r) => r.id)); // same client id = idempotent retry
    for (const record of sent.flat()) {
      assert.equal(record.capture_audit, undefined); assert.equal(record.last_sync_error, undefined);
      assert.equal(record.patient.name, undefined); assert.equal(record.fhir_bundle, null);
    }

    // 5. A conflict is flagged locally, removed from the outbox, and surfaced on the dashboard.
    const saved2 = snapshot(doms.at(-1)); doms.at(-1).window.close();
    const conflicting = apiMock({
      '/api/screenings': () => { throw new TypeError('Failed to fetch'); },
      '/api/sync': (body) => json({ accepted: 0, duplicate: 0, conflict: 1, rejected: 0, synced_ids: [], server_time: new Date().toISOString(),
        results: [{ id: body.records[0].id, status: 'conflict', error: { code: 'ID_CONFLICT', message: 'server copy kept', status: 409, retryable: false, fields: [] } }] }),
    });
    doms.push(await startApp(saved2, conflicting.fetchImpl));
    await runMaternalDemo();
    click('.nav-item[data-page="sync"]');
    await waitFor(() => document.querySelector('[data-action="sync-now"]:not([disabled])'), 'sync button for conflict');
    click('[data-action="sync-now"]');
    await waitFor(() => rows('screenings').some((r) => r.sync_status === 'conflict'), 'conflict flagged');
    assert.equal(rows('syncQueue').length, 0);
    assert.equal(rows('screenings').length, 2); // local copy kept
    await waitFor(() => /Needs attention/.test(document.body.textContent), 'problem list');
    click('.nav-item[data-page="home"]');
    await waitFor(() => /Sync problems/.test(document.body.textContent), 'home stats');
    const problemCard = [...document.querySelectorAll('.stat-card')].find((card) => /Sync problems/.test(card.textContent));
    assert.equal(problemCard.querySelector('.stat-number').textContent, '1');
  } finally {
    for (const dom of doms) dom.window.close();
    delete globalThis.window; delete globalThis.document; delete globalThis.localStorage;
  }
});

test('neonatal workflow requires age in hours and sends it as screening context', async () => {
  let created;
  const counselling = [];
  const api = apiMock({
    '/api/screenings': (body) => {
      created = body;
      const result = runDemoInference(body.screening_type, body.case_id);
      return json({ id: body.id, patient: body.patient, result, context: body.context, created_at: result.generated_at, sync_status: 'synced', id_origin: 'client' });
    },
  });
  const original = api.fetchImpl;
  const dom = await startApp({}, async (path, options = {}) => {
    if (path === '/api/counselling') { counselling.push(JSON.parse(options.body)); return json({}, 503); }
    return original(path, options);
  });
  try {
    click('[data-action="start-jaundice"]');
    await waitFor(() => document.querySelector('#ctxInfantAge'), 'age field');
    const age = document.querySelector('#ctxInfantAge');
    assert.equal(age.value, '36'); // prefilled from the synthetic newborn profile
    age.value = ''; age.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    assert.equal(document.querySelector('[data-action="wizard-next"]').disabled, true);
    assert.equal(age.getAttribute('aria-invalid'), 'true');
    age.value = '50'; age.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    assert.equal(document.querySelector('[data-action="wizard-next"]').disabled, false);
    click('[data-action="wizard-next"]');
    await waitFor(() => document.querySelector('[data-action="synthetic-image"]'), 'capture');
    click('[data-action="synthetic-image"]');
    await waitFor(() => document.querySelector('[data-action="wizard-next"]')?.disabled === false, 'quality');
    click('[data-action="wizard-next"]');
    await waitFor(() => document.querySelector('[data-action="run-screening"]'), 'fixtures');
    click('[data-action="run-screening"]');
    await waitFor(() => document.querySelector('.result-hero'), 'result');
    assert.deepEqual(created.context, { infant_age_hours: 50, gestational_week: null, pregnancy: null });
    assert.match(document.querySelector('.result-summary').textContent, /newborn age 50 h/);
    await waitFor(() => counselling.length > 0, 'counselling request');
    assert.equal(counselling[0].infant_age_hours, 50);
    assert.equal(counselling[0].provenance, 'DEMO_SYNTHETIC');
    assert.equal(counselling[0].confidence, null);
    assert.match(counselling[0].request_id, /^cns-scr-/);
    // Counselling failure keeps the deterministic copy visible.
    assert.ok(document.querySelector('.counsel-box').textContent.length > 20);
  } finally {
    dom.window.close();
    delete globalThis.window; delete globalThis.document; delete globalThis.localStorage;
  }
});

test('every page renders without the error state, including model audit and admin usage', async () => {
  const report = { period: { since: '2026-10-10T00:00:00+00:00', until: '2026-10-10T01:00:00+00:00' }, models: ['m'], model_versions_reported: [],
    counselling_requests: 2, provider_requests: 1, provider_successful: 1, provider_failed_or_rejected: 0, served_without_provider_call: 1,
    outcomes: { OK: 1, NO_API_KEY: 1 }, tokens_provider_reported: { prompt: 10, output_candidates: 5, thoughts: null, cached: null, tool_use_prompt: null, total: 15 },
    requests_missing_usage_metadata: 0, avg_tokens_per_successful_request: { prompt: 10, output_candidates: 5, total: 15 },
    latency_ms: { count: 1, mean: 120, p50: 120, max: 120 }, estimated_cost: null, notes: ['Provider-reported.'] };
  let authHeader;
  const api = apiMock({
    '/api/model/status': () => json({ adapters: { maternal_anemia: { status: 'DISABLED_NO_VALID_MODEL', reason: 'No validated anemia model.', target: 'hemoglobin concentration', unit: 'g/dL', inference_location: 'none' } },
      candidate_models: [{ id: 'neonatal-bilirubin', status: 'DISABLED_NO_VALID_MODEL', note: 'No labels.' }], research_baseline: { metrics: { mae_g_dl: 1.5041 } } }),
    '/api/dashboard': () => json({ total_screenings: 0, referrals: 0, pending_sync: null, today_screenings: 0, by_provenance: {}, by_type: {}, records: [] }),
    '/api/referrals': () => json([]),
  });
  const dom = await startApp({}, async (path, options = {}) => {
    if (path.startsWith('/api/admin/usage')) { authHeader = new dom.window.Headers(options.headers).get('Authorization'); return json(report); }
    return api.fetchImpl(path, options);
  });
  try {
    for (const page of ['patients', 'history', 'sync', 'phc', 'architecture', 'model', 'settings', 'usage']) {
      click(`.nav-item[data-page="${page}"]`);
      await waitFor(() => document.querySelector('#currentSection').textContent !== 'Home' || page === 'home', `${page} header`);
      await new Promise((resolve) => setTimeout(resolve, 30));
      assert.doesNotMatch(document.querySelector('#mainContent').textContent, /Something needs attention/, page);
    }
    assert.match(document.body.textContent, /AI usage report/);
    click('.nav-item[data-page="model"]');
    await waitFor(() => /No validated anemia model/.test(document.body.textContent), 'adapter reason');
    assert.match(document.body.textContent, /R² −0\.197/);
    click('.nav-item[data-page="usage"]');
    await waitFor(() => document.querySelector('#usageForm'), 'usage form');
    document.querySelector('#adminToken').value = 'admin-token-123456789';
    document.querySelector('#usageForm').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
    await waitFor(() => /Requests missing usage metadata/.test(document.body.textContent), 'usage report');
    assert.equal(authHeader, 'Bearer admin-token-123456789');
    assert.match(document.body.textContent, /Not computed — no verified pricing configured/);
    assert.ok(document.querySelectorAll('.unavailable').length >= 2, 'null token fields are labelled unavailable');
    assert.equal(JSON.stringify(snapshot(dom)).includes('admin-token-123456789'), false, 'admin token is not persisted');
  } finally {
    dom.window.close();
    delete globalThis.window; delete globalThis.document; delete globalThis.localStorage;
  }
});
