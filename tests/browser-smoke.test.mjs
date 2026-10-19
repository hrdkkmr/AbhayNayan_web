import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import { runDemoInference } from '../web-dashboard/js/inference.js';
import { localCounsel } from '../web-dashboard/js/language.js';

const waitFor = async (check, label) => {
  for (let i = 0; i < 100; i += 1) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`Timed out waiting for ${label}`);
};

test('PWA completes maternal and newborn synthetic flows with age-in-hours context', async () => {
  const html = await fs.readFile(new URL('../web-dashboard/index.html', import.meta.url), 'utf8');
  const dom = new JSDOM(html, { url: 'http://localhost:8000/', pretendToBeVisual: true, runScripts: 'outside-only' });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.localStorage = dom.window.localStorage;
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });

  const fakeContext = {
    createLinearGradient: () => ({ addColorStop() {} }),
    fillRect() {}, beginPath() {}, ellipse() {}, stroke() {}, fill() {}, fillText() {}, setLineDash() {}, drawImage() {},
    getImageData(_x, _y, width, height) {
      const data = new Uint8ClampedArray(width * height * 4);
      for (let i = 0; i < width * height; i += 1) {
        data[i * 4] = 170; data[i * 4 + 1] = 105; data[i * 4 + 2] = 100; data[i * 4 + 3] = 255;
      }
      return { data, width, height };
    },
  };
  dom.window.HTMLCanvasElement.prototype.getContext = () => fakeContext;
  dom.window.HTMLCanvasElement.prototype.toDataURL = () => 'data:image/png;base64,AA==';

  let screeningPayload;
  const counsellingRequests = [];
  const jsonResponse = (value) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } });
  globalThis.fetch = async (path, options = {}) => {
    if (path === '/api/health') return jsonResponse({ status: 'ok', mode: 'PROTOTYPE_DEMO', gemini_configured: false });
    if (path === '/api/screenings') {
      screeningPayload = JSON.parse(options.body);
      const result = runDemoInference(screeningPayload.screening_type, screeningPayload.case_id);
      return jsonResponse({ id: screeningPayload.id, patient: screeningPayload.patient, result,
        worker_id: screeningPayload.worker_id, phc: screeningPayload.phc, created_at: result.generated_at,
        sync_status: 'synced', fhir_bundle: { resourceType: 'Bundle', entry: [] } });
    }
    if (path === '/api/counselling') {
      const request = JSON.parse(options.body);
      counsellingRequests.push(request);
      const copy = localCounsel(request.screening_type, request.language);
      return jsonResponse({ summary: copy.summary, risk_explanation: copy.risk, counselling_script: copy.script,
        recommended_next_step: copy.action, referral_required: false, urgency: 'DEMO_ONLY', language: request.language,
        safety_note: copy.safety, mode: 'LOCAL_FALLBACK' });
    }
    throw new Error(`Unexpected API call in smoke test: ${path}`);
  };

  try {
    await import(`../web-dashboard/js/app.js?dom-smoke=${Date.now()}`);
    await waitFor(() => document.querySelector('.hero-panel'), 'home dashboard');
    document.querySelector('[data-action="start-screening"]').click();
    await waitFor(() => document.querySelector('#patientSelect'), 'patient/workflow step');
    document.querySelector('[data-action="wizard-next"]').click();
    await waitFor(() => document.querySelector('[data-action="synthetic-image"]'), 'capture step');
    document.querySelector('[data-action="synthetic-image"]').click();
    await waitFor(() => document.querySelector('[data-action="wizard-next"]')?.disabled === false, 'synthetic quality pass');
    document.querySelector('[data-action="wizard-next"]').click();
    await waitFor(() => document.querySelector('[data-action="run-screening"]'), 'fixture selection step');
    document.querySelector('[data-action="run-screening"]').click();
    await waitFor(() => document.querySelector('.result-hero'), 'result page');
    await waitFor(() => document.querySelector('.counsel-box')?.textContent?.length > 0, 'counselling copy');

    assert.match(document.body.textContent, /SYNTHETIC FIXTURE/);
    assert.match(document.body.textContent.toLowerCase(), /not a diagnosis/);
    assert.equal(screeningPayload.patient.demo, true);
    assert.equal(screeningPayload.image_base64, undefined);
    assert.equal(screeningPayload.patient.name, undefined);
    assert.equal(screeningPayload.case_id, 'maternal-normal');
    const localScreenings = JSON.parse(localStorage.getItem('abn_screenings'));
    assert.equal(localScreenings.length, 1);
    assert.equal(JSON.stringify(localScreenings).includes('data:image'), false);
    assert.equal(localScreenings[0].capture_audit.features, undefined);

    document.querySelector('.nav-item[data-page="history"]').click();
    await waitFor(() => document.querySelector('.data-table tbody tr'), 'saved maternal history row');
    assert.match(document.querySelector('.data-table tbody').textContent, /11\.8 g\/dL/);

    document.querySelector('.nav-item[data-page="home"]').click();
    await waitFor(() => document.querySelector('.hero-panel'), 'home before newborn flow');
    document.querySelector('[data-action="start-jaundice"]').click();
    await waitFor(() => document.querySelector('#patientSelect'), 'newborn profile selection');
    const profiles = JSON.parse(localStorage.getItem('abn_patients'));
    const newborn = profiles.find((patient) => patient.demoKind === 'newborn');
    assert.ok(newborn, 'a dedicated synthetic newborn profile is seeded');
    assert.equal(document.querySelector('#patientSelect').value, newborn.id);
    document.querySelector('[data-action="wizard-next"]').click();
    await waitFor(() => document.querySelector('[data-action="synthetic-image"]'), 'newborn capture step');
    document.querySelector('[data-action="synthetic-image"]').click();
    await waitFor(() => document.querySelector('[data-action="wizard-next"]')?.disabled === false, 'newborn synthetic quality pass');
    document.querySelector('[data-action="wizard-next"]').click();
    await waitFor(() => document.querySelector('[data-action="run-screening"]'), 'newborn fixture selection step');
    document.querySelector('[data-action="run-screening"]').click();
    await waitFor(() => document.querySelector('.result-hero'), 'newborn synthetic result');
    await waitFor(() => counsellingRequests.some((request) => request.screening_type === 'neonatal_jaundice'), 'newborn counselling context');
    const newbornCounselling = counsellingRequests.find((request) => request.screening_type === 'neonatal_jaundice');
    assert.equal(newbornCounselling.infant_age_hours, 36);
    assert.equal(newbornCounselling.pregnancy, false);
    assert.match(document.body.textContent, /12\.8 mg\/dL/);
    const allLocalScreenings = JSON.parse(localStorage.getItem('abn_screenings'));
    assert.equal(allLocalScreenings.length, 2);
    assert.equal(allLocalScreenings[1].patient.patient_id, newborn.id);

    document.querySelector('.nav-item[data-page="history"]').click();
    await waitFor(() => document.querySelectorAll('.data-table tbody tr').length === 2, 'maternal and newborn history rows');
  } finally {
    dom.window.close();
    delete globalThis.window; delete globalThis.document; delete globalThis.localStorage;
  }
});
