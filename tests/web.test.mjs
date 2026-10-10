import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { assessImageQuality, correctAmbientLight, extractOpticalFeatures } from '../web-dashboard/js/vision.js';
import { formatEstimate, getDemoCases, riskTone, runDemoInference } from '../web-dashboard/js/inference.js';
import { LANGUAGES, localCounsel, navLabels } from '../web-dashboard/js/language.js';
import { buildFhirBundle } from '../web-dashboard/js/fhir.js';
import * as store from '../web-dashboard/js/store.js';

const localData = new Map();
globalThis.localStorage = {
  getItem: (key) => localData.has(key) ? localData.get(key) : null,
  setItem: (key, value) => localData.set(key, String(value)),
  removeItem: (key) => localData.delete(key),
};

function imageData(width, height, rgb = [120, 80, 40]) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    const offset = i * 4;
    data[offset] = rgb[0]; data[offset + 1] = rgb[1]; data[offset + 2] = rgb[2]; data[offset + 3] = 255;
  }
  return { data, width, height };
}

beforeEach(() => localData.clear());

test('maternal demo case catalog has three named fixtures', () => {
  assert.equal(getDemoCases('maternal_anemia').length, 3);
});

test('neonatal demo case catalog has two named fixtures', () => {
  assert.equal(getDemoCases('neonatal_jaundice').length, 2);
});

test('demo inference returns a fixed synthetic result', () => {
  const result = runDemoInference('maternal_anemia', 'maternal-moderate');
  assert.equal(result.estimate, 9.4);
  assert.equal(result.synthetic, true);
  assert.equal(result.model_mode, 'DEMO');
});

test('unknown demo case is rejected', () => {
  assert.throws(() => runDemoInference('maternal_anemia', 'unknown'));
});

test('estimate formatter preserves units and one decimal place', () => {
  assert.equal(formatEstimate({ screening_type: 'maternal_anemia', estimate: 9.444, unit: 'g/dL' }), '9.4 g/dL');
});

test('risk tone treats escalation as red and review as amber', () => {
  assert.equal(riskTone('DEMO_ESCALATE'), 'red');
  assert.equal(riskTone('REQUIRES_REVIEW'), 'amber');
  assert.equal(riskTone('DEMO_LOW'), 'green');
});

test('optical feature extraction rejects missing pixel data', () => {
  assert.throws(() => extractOpticalFeatures(null));
});

test('optical feature extraction returns color spaces and explicit safety note', () => {
  const result = extractOpticalFeatures(imageData(32, 32, [180, 90, 70]));
  assert.ok(result.rgb.r > result.rgb.g);
  assert.ok(result.hsv);
  assert.ok(result.labApprox);
  assert.ok(result.yCrCb);
  assert.match(result.note, /not a hemoglobin or bilirubin measurement/i);
});

test('quality gate blocks when no image is present', () => {
  const result = assessImageQuality(null);
  assert.equal(result.ready, false);
  assert.equal(result.status, 'NO IMAGE');
});

test('quality gate requires manual region confirmation', () => {
  const result = assessImageQuality(imageData(100, 100, [126, 126, 126]), { regionConfirmed: false });
  assert.equal(result.ready, false);
  assert.ok(result.reasons.some((item) => item.includes('Confirm')));
});

test('quality gate names the maternal target region instead of assuming sclera', () => {
  const result = assessImageQuality(imageData(100, 100, [126, 126, 126]), {
    regionConfirmed: false, regionLabel: 'lower-eyelid conjunctiva',
  });
  assert.ok(result.reasons.some((item) => item.includes('lower-eyelid conjunctiva')));
});

test('quality gate refuses very dark image', () => {
  const result = assessImageQuality(imageData(100, 100, [8, 8, 8]), { regionConfirmed: true });
  assert.equal(result.ready, false);
  assert.ok(result.reasons.some((item) => item.includes('dark')));
});

test('synthetic quality case is clearly marked and ready for demo path', () => {
  const result = assessImageQuality(imageData(4, 4), { synthetic: true });
  assert.equal(result.ready, true);
  assert.equal(result.status, 'SYNTHETIC DEMO');
  assert.match(result.detail, /not real/i);
});

test('ambient correction without pair skips subtraction', () => {
  const result = correctAmbientLight(imageData(10, 10));
  assert.equal(result.available, false);
  assert.equal(result.corrected, false);
  assert.match(result.message, /No subtraction/i);
});

test('ambient correction skips dimension mismatch', () => {
  const result = correctAmbientLight(imageData(10, 10), imageData(9, 10));
  assert.equal(result.corrected, false);
  assert.match(result.message, /dimensions differ/i);
});

test('ambient correction pair is explicitly experimental', () => {
  globalThis.ImageData = class ImageDataMock {
    constructor(data, width, height) { this.data = data; this.width = width; this.height = height; }
  };
  const result = correctAmbientLight(imageData(12, 12, [30, 40, 50]), imageData(12, 12, [80, 90, 100]));
  assert.equal(result.corrected, true);
  assert.match(result.message, /not clinically validated/i);
});

test('language module exposes English, Hindi, and Bhojpuri', () => {
  assert.deepEqual(LANGUAGES.map((item) => item.id), ['en', 'hi', 'bho']);
});

test('Hindi fallback provides safety-oriented maternal copy', () => {
  const result = localCounsel('maternal_anemia', 'hi');
  assert.match(result.safety, /दवा/);
  assert.match(result.summary, /प्रोटोटाइप/);
});

test('unknown language falls back to English counselling', () => {
  assert.equal(localCounsel('maternal_anemia', 'xx').summary, localCounsel('maternal_anemia', 'en').summary);
});

test('navigation has English labels', () => {
  assert.equal(navLabels('en').home, 'Home');
});

test('FHIR local bundle includes patient, encounter, observation, and report', () => {
  const result = runDemoInference('neonatal_jaundice', 'jaundice-review');
  const bundle = buildFhirBundle({ id: 'ABH-LOCAL-1', name: 'Demo Patient' }, result, {}, 'scr-web-test');
  assert.deepEqual(bundle.entry.map((entry) => entry.resource.resourceType), ['Patient', 'Encounter', 'Observation', 'DiagnosticReport']);
});

test('FHIR observation is preliminary and contains synthetic safety note', () => {
  const result = runDemoInference('maternal_anemia', 'maternal-normal');
  const bundle = buildFhirBundle({ id: 'ABH-LOCAL-2' }, result, {}, 'scr-web-test-2');
  const observation = bundle.entry.find((entry) => entry.resource.resourceType === 'Observation').resource;
  assert.equal(observation.status, 'preliminary');
  assert.match(observation.note[0].text, /synthetic/i);
});

test('FHIR Bundle fullUrls and resource references are stable absolute demo URLs', () => {
  const result = runDemoInference('maternal_anemia', 'maternal-normal');
  const bundle = buildFhirBundle({ id: 'ABH-LOCAL-3' }, result, {}, 'screen-100');
  assert.ok(bundle.entry.every((entry) => entry.fullUrl.startsWith('https://fhir.abhaynayan.invalid/')));
  const observation = bundle.entry.find((entry) => entry.resource.resourceType === 'Observation').resource;
  assert.ok(observation.subject.reference.startsWith('Patient/'));
  assert.ok(bundle.entry.every((entry) => entry.resource.id.length <= 64));
});

test('browser store writes, reads, and removes fallback rows', async () => {
  await store.put('patients', { id: 'ABH-LOCAL-4', name: 'Demo' });
  assert.equal((await store.getOne('patients', 'ABH-LOCAL-4')).name, 'Demo');
  assert.equal((await store.getAll('patients')).length, 1);
  await store.remove('patients', 'ABH-LOCAL-4');
  assert.equal((await store.getAll('patients')).length, 0);
});

test('settings use local fallback store', async () => {
  await store.setSetting('language', 'bho');
  assert.equal(await store.getSetting('language', 'en'), 'bho');
  assert.equal(await store.getSetting('unset', 'en'), 'en');
});

test('demo patient profile is generated and persisted locally', async () => {
  const patient = await store.ensureDemoPatient();
  assert.equal(patient.isDemo, true);
  assert.equal(patient.name, 'Demo Patient');
  assert.equal(patient.demoKind, 'maternal');
  assert.equal((await store.getAll('patients')).length, 1);
});

test('newborn demo profile carries distinct age-in-hours context', async () => {
  await store.ensureDemoPatient('maternal');
  const patient = await store.ensureDemoPatient('newborn');
  assert.equal(patient.isDemo, true);
  assert.equal(patient.demoKind, 'newborn');
  assert.equal(patient.age, 0);
  assert.equal(patient.pregnancy, false);
  assert.equal(patient.infantAgeHours, 36);
  assert.equal((await store.getAll('patients')).length, 2);
});

test('local patient IDs are pseudonymous and year-scoped', async () => {
  const patientId = await store.makePatientId();
  assert.match(patientId, /^ABH-\d{4}-\d{4}$/);
});

test('clear local store purges fallback patient and setting data', async () => {
  await store.put('patients', { id: 'ABH-LOCAL-5' });
  await store.setSetting('language', 'hi');
  await store.clearAllLocalData();
  assert.equal((await store.getAll('patients')).length, 0);
  assert.equal(await store.getSetting('language', null), null);
});
