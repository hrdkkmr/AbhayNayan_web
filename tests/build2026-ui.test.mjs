// Build 2026 additions: terms gate and versioning, Get-the-app QR destination, help assistant UI, quieter safety notes.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import { JSDOM } from 'jsdom';
import { APP_DISTRIBUTION, validateDestination } from '../web-dashboard/js/distribution.js';
import { qrMatrix, qrSvg } from '../web-dashboard/js/qr.js';
import { acceptanceNeeded, acceptanceRecord } from '../web-dashboard/js/terms.js';
import { TERMS_PATH, termsText } from './helpers/terms.mjs';

const html = await fs.readFile(new URL('../web-dashboard/index.html', import.meta.url), 'utf8');
const terms = JSON.parse(termsText);
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const waitFor = async (check, label) => {
  for (let i = 0; i < 150; i += 1) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`Timed out waiting for ${label}`);
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

let boot = 0;
async function startApp({ saved = {}, termsBody = termsText, api = {}, online = true } = {}) {
  const dom = new JSDOM(html, { url: 'http://localhost:8000/', pretendToBeVisual: true, runScripts: 'outside-only' });
  for (const [key, value] of Object.entries(saved)) dom.window.localStorage.setItem(key, value);
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.localStorage = dom.window.localStorage;
  Object.defineProperty(dom.window.navigator, 'onLine', { value: online, configurable: true });
  Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
  dom.window.HTMLCanvasElement.prototype.getContext = () => null;
  const calls = [];
  globalThis.fetch = async (path, options = {}) => {
    calls.push({ path: String(path), method: options.method || 'GET', body: options.body || null });
    if (path === TERMS_PATH) return termsBody === null ? json({}, 404) : new Response(termsBody, { status: 200 });
    if (api[path]) return api[path](options);
    if (String(path).startsWith('/api/')) return json({ detail: 'offline in test' }, 503);
    throw new Error(`Unexpected fetch ${path}`);
  };
  boot += 1;
  await import(`../web-dashboard/js/app.js?build2026=${boot}`);
  await waitFor(() => document.querySelector('.welcome-panel'), 'home');
  return { dom, calls };
}
function close(dom) {
  dom.window.close();
  delete globalThis.window; delete globalThis.document; delete globalThis.localStorage;
}
const settings = () => JSON.parse(localStorage.getItem('abn_settings') || '[]');
const acceptance = () => settings().find((row) => row.key === 'termsAcceptance')?.value ?? null;
const saveAcceptance = (value) => ({ abn_settings: JSON.stringify([{ key: 'termsAcceptance', value }]) });

test('terms acceptance logic is version based', () => {
  assert.equal(acceptanceNeeded(terms, null), true);
  const record = acceptanceRecord(terms, new Date('2026-10-24T10:00:00Z'));
  assert.deepEqual(record, { version: terms.version, acceptance_version: terms.acceptance_version, accepted_at: '2026-10-24T10:00:00.000Z' });
  assert.equal(acceptanceNeeded(terms, record), false);
  assert.equal(acceptanceNeeded({ ...terms, version: '1.1' }, record), false, 'a minor wording change keeps acceptance');
  assert.equal(acceptanceNeeded({ ...terms, version: '2.0', acceptance_version: '2.0' }, record), true, 'a material change asks again');
  assert.equal(acceptanceNeeded(terms, { ...record, accepted_at: '' }), true, 'no timestamp is not an acceptance');
  assert.equal(acceptanceNeeded(null, record), true, 'unknown terms are never treated as accepted');
});

test('the canonical terms file has the required sections, a version and a date', () => {
  assert.match(terms.version, /^\d+\.\d+$/);
  assert.match(terms.last_updated, /^\d{4}-\d{2}-\d{2}$/);
  const ids = terms.sections.map((s) => s.id);
  for (const id of ['purpose', 'status', 'estimates', 'image-checks', 'not-medical-advice', 'privacy', 'sync', 'consent', 'help']) assert.ok(ids.includes(id), id);
  const text = termsText.toLowerCase();
  assert.match(text, /not a medical device/);
  assert.match(text, /does not mean that the person is healthy/);
  assert.match(text, /not consent to take part in research/);
  assert.match(text, /sync of full outcome records is switched off/);
  assert.match(text, /not been reviewed by a lawyer/);
  assert.doesNotMatch(text, /guarantee|fully compliant|hipaa|certified/);
});

test('first screening asks for the terms; "Not now" starts nothing and records nothing', async () => {
  const { dom } = await startApp();
  try {
    document.querySelector('[data-action="start-screening"]').click();
    await waitFor(() => document.querySelector('.terms-dialog'), 'terms dialog');
    assert.match(document.querySelector('.terms-dialog').textContent, /Before your first screening/);
    assert.match(document.querySelector('.terms-dialog').textContent, new RegExp(`version ${terms.version.replace('.', '\\.')}`));
    document.querySelector('.terms-dialog [data-action="close-modal"]:not(.modal-close)').click();
    await settle();
    assert.equal(document.querySelector('#patientSelect'), null, 'workflow did not open');
    assert.equal(acceptance(), null, 'nothing recorded without pressing accept');
    document.querySelector('[data-action="start-screening"]').click();
    await waitFor(() => document.querySelector('.terms-dialog [data-action="accept-terms"]'), 'dialog again');
    document.querySelector('.terms-dialog [data-action="accept-terms"]').click();
    await waitFor(() => document.querySelector('#patientSelect'), 'workflow after acceptance');
    const stored = acceptance();
    assert.equal(stored.version, terms.version);
    assert.equal(stored.acceptance_version, terms.acceptance_version);
    assert.ok(!Number.isNaN(Date.parse(stored.accepted_at)));
    assert.deepEqual(Object.keys(stored).sort(), ['acceptance_version', 'accepted_at', 'version'], 'no identity is stored with acceptance');
  } finally { close(dom); }
});

test('a stored acceptance is honoured; a material terms change asks again', async () => {
  const accepted = acceptanceRecord(terms, new Date('2026-10-24T09:00:00Z'));
  let { dom } = await startApp({ saved: saveAcceptance(accepted) });
  try {
    document.querySelector('[data-action="start-screening"]').click();
    await waitFor(() => document.querySelector('#patientSelect'), 'workflow without dialog');
    assert.equal(document.querySelector('.terms-dialog'), null);
  } finally { close(dom); }

  const changed = JSON.stringify({ ...terms, version: '2.0', acceptance_version: '2.0', last_updated: '2026-11-01' });
  ({ dom } = await startApp({ saved: saveAcceptance(accepted), termsBody: changed }));
  try {
    document.querySelector('[data-action="start-screening"]').click();
    await waitFor(() => document.querySelector('.terms-dialog'), 'dialog for changed terms');
    assert.match(document.querySelector('.terms-dialog').textContent, /The terms have changed/);
    assert.equal(document.querySelector('#patientSelect'), null);
  } finally { close(dom); }
});

test('if the terms cannot be loaded, no screening starts and the user is told why', async () => {
  const { dom } = await startApp({ termsBody: null });
  try {
    document.querySelector('[data-action="start-screening"]').click();
    await waitFor(() => document.querySelector('.terms-dialog'), 'failure dialog');
    assert.match(document.querySelector('.terms-dialog').textContent, /could not be loaded/);
    assert.equal(document.querySelector('[data-action="accept-terms"]'), null, 'nothing to accept when nothing was shown');
    assert.equal(document.querySelector('#patientSelect'), null);
  } finally { close(dom); }
});

test('Settings and the Terms page show the version, date and acceptance status', async () => {
  const { dom } = await startApp();
  try {
    document.querySelector('.nav-item[data-page="settings"]').click();
    await waitFor(() => document.querySelector('#termsCardTitle'), 'settings terms card');
    assert.match(document.body.textContent, /Not yet accepted on this device/);
    document.querySelector('[data-page="terms"].btn').click();
    await waitFor(() => document.querySelector('.terms-meta'), 'terms page');
    assert.match(document.querySelector('.terms-meta').textContent, new RegExp(`Version ${terms.version.replace('.', '\\.')}`));
    assert.equal(document.querySelectorAll('.terms-section').length, terms.sections.length);
    assert.equal(document.querySelectorAll('.terms-section h2').length, terms.sections.length, 'each section has a heading');
    document.querySelector('[data-action="accept-terms"]').click();
    await waitFor(() => acceptance() !== null, 'acceptance from the terms page');
    await waitFor(() => /Accepted on this device/.test(document.querySelector('.terms-meta').textContent), 'status updated');
    assert.equal(document.querySelector('[data-action="accept-terms"]'), null, 'no accept button once accepted');
  } finally { close(dom); }
});

test('destination validation refuses unsafe or misleading QR targets', () => {
  const ok = validateDestination(APP_DISTRIBUTION);
  assert.equal(ok.ok, true);
  assert.equal(ok.url, 'https://abhaynayan-web.onrender.com/');
  assert.equal(ok.label, 'Open the web app');
  assert.match(ok.scanText, /does not install/);
  const bad = (url, kind = 'web_app') => validateDestination({ kind, url }).ok;
  assert.equal(bad('http://abhaynayan-web.onrender.com/'), false, 'https only');
  assert.equal(bad('https://user:pass@abhaynayan-web.onrender.com/'), false, 'no credentials');
  assert.equal(bad('https://abhaynayan-web.onrender.com/?token=abc'), false, 'no query');
  assert.equal(bad('https://abhaynayan-web.onrender.com/#id=1'), false, 'no fragment');
  assert.equal(bad('https://example.org/builds/app-debug.apk', 'android_install_page'), false, 'never an APK file');
  assert.equal(bad('https://localhost/'), false);
  assert.equal(bad('https://10.0.2.2/'), false);
  assert.equal(bad('not a url'), false);
  assert.equal(validateDestination({ kind: 'apk', url: 'https://example.org/' }).ok, false, 'unknown kind');
  assert.equal(validateDestination({ kind: 'android_install_page', url: 'https://example.org/install' }).label, 'Install the Android app');
});

test('QR generation is local, deterministic and uses the pinned library', async () => {
  const vendored = await fs.readFile(new URL('../web-dashboard/js/vendor/qrcode-generator-2.0.4.mjs', import.meta.url));
  assert.equal(crypto.createHash('sha256').update(vendored).digest('hex'), 'ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0');
  assert.doesNotMatch(vendored.toString(), /fetch\(|XMLHttpRequest|new Function|\beval\(/);
  const a = qrMatrix(APP_DISTRIBUTION.url); const b = qrMatrix(APP_DISTRIBUTION.url);
  assert.deepEqual(a, b);
  assert.ok(a.length >= 21 && (a.length - 17) % 4 === 0, 'valid QR size');
  const svg = qrSvg(APP_DISTRIBUTION.url, { title: 'QR <test>' });
  assert.match(svg, /fill="#ffffff"/); assert.match(svg, /fill="#000000"/);
  assert.match(svg, new RegExp(`viewBox="0 0 ${a.length + 8} ${a.length + 8}"`), 'four-module quiet zone');
  assert.match(svg, /QR &lt;test&gt;/);
});

test('Get the app page shows a real QR, the exact link, copy and fallback; no external request', async () => {
  const { dom, calls } = await startApp();
  try {
    document.querySelector('.nav-item[data-page="getapp"]').click();
    await waitFor(() => document.querySelector('.qr-card svg'), 'qr');
    const link = document.querySelector('.qr-card a.btn');
    assert.equal(link.getAttribute('href'), 'https://abhaynayan-web.onrender.com/');
    assert.equal(link.textContent, 'Open the web app');
    assert.equal(document.querySelector('#appLinkText').textContent, 'https://abhaynayan-web.onrender.com/');
    assert.match(document.body.textContent, /Cannot scan a QR code\?/);
    assert.match(document.body.textContent, /no public Android release/i);
    assert.doesNotMatch(document.querySelector('.qr-card').textContent, /Install the Android app/);
    assert.ok(document.querySelector('[data-action="copy-app-link"]'));
    assert.ok(calls.every((c) => c.path.startsWith('/')), 'only same-origin requests');
  } finally { close(dom); }
});

test('help assistant: sends only the question, shows the answer source, and fails gracefully', async () => {
  const answers = [
    json({ mode: 'KNOWLEDGE_BASE', answer: 'Approved text about offline use.', sources: [{ title: 'AbhayNayan Terms & Conditions', url: 'app:terms' }], entry_ids: ['offline-use'], related: [], refusal_code: null, fallback_reason: null, kb_version: '2026-10-24.1', language: 'en', notice: 'General information only.' }),
    json({ mode: 'REFUSED', answer: 'I cannot estimate hemoglobin or bilirubin.', sources: [], entry_ids: [], related: [], refusal_code: 'CLINICAL_REQUEST', kb_version: '2026-10-24.1' }),
    json({ detail: 'off', error: { code: 'ASSISTANT_DISABLED', message: 'off', status: 503, retryable: false } }, 503),
  ];
  const { dom, calls } = await startApp({ api: { '/api/assistant/ask': () => answers.shift() } });
  try {
    document.querySelector('.nav-item[data-page="assistant"]').click();
    await waitFor(() => document.querySelector('#assistantForm'), 'assistant form');
    document.querySelector('#assistantQuestion').value = 'Does the app work offline?';
    document.querySelector('#assistantForm').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
    await waitFor(() => document.querySelector('.assistant-answer'), 'answer');
    assert.match(document.querySelector('.answer-text').textContent, /Approved text about offline use/);
    assert.match(document.querySelector('.assistant-answer').textContent, /Approved help text/);
    const sent = calls.find((c) => c.path === '/api/assistant/ask');
    assert.deepEqual(JSON.parse(sent.body), { question: 'Does the app work offline?' }, 'no identifiers, records or images are sent');

    document.querySelector('[data-suggest]').click();
    await waitFor(() => /Cannot help with this here/.test(document.body.textContent), 'refusal label');
    assert.match(document.querySelector('.answer-text').textContent, /cannot estimate/);

    document.querySelector('[data-suggest]').click();
    await waitFor(() => /switched off on this server/.test(document.body.textContent), 'disabled message');
    assert.equal(document.querySelector('.assistant-answer'), null, 'no stale or invented answer is shown');
    document.querySelector('.nav-item[data-page="home"]').click();
    await waitFor(() => document.querySelector('.welcome-panel'), 'rest of the app still works');
  } finally { close(dom); }
});

test('help assistant is disabled offline with an explanation', async () => {
  const { dom } = await startApp({ online: false });
  try {
    document.querySelector('.nav-item[data-page="assistant"]').click();
    await waitFor(() => document.querySelector('#assistantForm'), 'assistant form');
    assert.equal(document.querySelector('#assistantQuestion').disabled, true);
    assert.match(document.body.textContent, /needs a connection\. The rest of the app works offline/);
    assert.match(document.querySelector('#networkLabel').textContent, /NO NETWORK/, 'no false online indicator');
  } finally { close(dom); }
});

test('information pages use one-line notes, not large warning banners; the footer makes no endorsement claim', async () => {
  const { dom } = await startApp();
  try {
    for (const page of ['home', 'patients', 'sync', 'phc', 'assistant', 'getapp', 'terms']) {
      document.querySelector(`.nav-item[data-page="${page}"]`).click();
      await settle();
      assert.equal(document.querySelectorAll('#mainContent .safety-note:not(.danger)').length, 0, `${page} has no large safety banner`);
    }
    assert.match(document.querySelector('.app-footer').textContent, /not affiliated with or endorsed by any government body/);
    assert.doesNotMatch(document.body.innerHTML, /Government of India|Ayushman|National Health Authority|emblem/i);
  } finally { close(dom); }
});
