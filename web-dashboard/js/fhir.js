const now = () => new Date().toISOString();
const randomId = () => globalThis.crypto?.randomUUID?.() || 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16); });
const safeId = (value) => String(value || '').replace(/[^A-Za-z0-9.-]/g, '-').slice(0, 64) || 'unknown';
function stableSuffix(value) {
  let hash = 2166136261;
  for (const character of String(value)) { hash ^= character.charCodeAt(0); hash = Math.imul(hash, 16777619); }
  return (hash >>> 0).toString(16).padStart(8, '0');
}
const relatedId = (prefix, source) => `${prefix}-${safeId(source).slice(0, 48)}-${stableSuffix(source)}`.slice(0, 64);

export function buildFhirBundle(patient, result, worker = {}, screeningId = randomId()) {
  const bundleId = randomId();
  const patientId = safeId(patient?.id || 'demo-patient');
  const encounterId = relatedId('enc', screeningId);
  const observationId = relatedId('obs', screeningId);
  const reportId = relatedId('report', screeningId);
  const patientResource = {
    resourceType: 'Patient', id: patientId,
    identifier: [{ system: 'urn:abhaynayan:demo-patient-id', value: patientId }],
    active: true,
    name: patient?.name ? [{ text: patient.name }] : undefined,
    gender: fhirGender(patient?.sex),
    address: patient?.village ? [{ text: patient.village }] : undefined,
    meta: { tag: [{ system: 'urn:abhaynayan:tag', code: 'prototype', display: 'Prototype demonstration record' }] },
  };
  const encounterResource = {
    resourceType: 'Encounter', id: encounterId, status: 'finished', class: { system: 'http://terminology.hl7.org/CodeSystem/v3-ActCode', code: 'AMB', display: 'ambulatory' },
    subject: { reference: `Patient/${patientId}` }, period: { start: result.generated_at || now(), end: result.generated_at || now() },
    serviceProvider: worker?.phc ? { display: worker.phc } : undefined,
    meta: { tag: [{ system: 'urn:abhaynayan:tag', code: 'prototype', display: 'Prototype encounter' }] },
  };
  const observationCode = result.screening_type === 'maternal_anemia' ? 'Optical hemoglobin screening estimate' : 'Optical bilirubin screening estimate';
  const observationResource = {
    resourceType: 'Observation', id: observationId, status: 'preliminary', category: [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/observation-category', code: 'exam', display: 'Exam' }] }],
    code: { text: observationCode }, subject: { reference: `Patient/${patientId}` }, encounter: { reference: `Encounter/${encounterId}` }, effectiveDateTime: result.generated_at || now(),
    valueQuantity: { value: Number(result.estimate), unit: result.unit, system: 'http://unitsofmeasure.org', code: result.unit === 'g/dL' ? 'g/dL' : 'mg/dL' },
    method: { text: 'Smartphone optical screening prototype; synthetic demo case' },
    note: [{ text: 'Preliminary synthetic prototype estimate only; not a clinically validated measurement or diagnosis. Confirm with appropriate clinical testing and local protocol.' }],
    interpretation: [{ text: String(result.risk_category || 'DEMO_ONLY') }],
    component: [
      { code: { text: 'Prototype confidence (not clinical probability)' }, valueQuantity: { value: Number(result.confidence || 0), unit: 'fraction', system: 'http://unitsofmeasure.org', code: '1' } },
      { code: { text: 'Image quality score (prototype)' }, valueQuantity: { value: Number(result.quality_score || 0), unit: 'fraction', system: 'http://unitsofmeasure.org', code: '1' } },
    ],
    meta: { tag: [{ system: 'urn:abhaynayan:tag', code: 'synthetic-demo', display: 'Synthetic demo only' }] },
  };
  const reportResource = {
    resourceType: 'DiagnosticReport', id: reportId, status: 'preliminary', code: { text: 'AbhayNayan prototype screening report' },
    subject: { reference: `Patient/${patientId}` }, encounter: { reference: `Encounter/${encounterId}` }, effectiveDateTime: result.generated_at || now(), result: [{ reference: `Observation/${observationId}` }],
    conclusion: 'Synthetic prototype screening estimate only. Not a diagnosis or validated clinical result; confirm with appropriate clinical testing and local protocol.',
    meta: { tag: [{ system: 'urn:abhaynayan:tag', code: 'not-clinical-diagnostic', display: 'Not a clinical diagnosis' }] },
  };
  const resources = [patientResource, encounterResource, observationResource, reportResource].map(stripUndefined);
  return {
    resourceType: 'Bundle', id: bundleId, type: 'collection', timestamp: now(),
    meta: { tag: [{ system: 'urn:abhaynayan:tag', code: 'prototype', display: 'AbhayNayan hackathon prototype' }] },
    entry: resources.map((resource) => ({ fullUrl: `https://fhir.abhaynayan.invalid/${resource.resourceType}/${resource.id}`, resource })),
  };
}

function stripUndefined(value) {
  if (Array.isArray(value)) return value.map(stripUndefined);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined).map(([k, v]) => [k, stripUndefined(v)]));
  return value;
}
function fhirGender(sex) {
  const s = String(sex || '').toLowerCase();
  if (s === 'male' || s === 'm') return 'male';
  if (s === 'female' || s === 'f') return 'female';
  return 'unknown';
}
export function downloadJson(data, filename = 'abhaynayan-fhir-bundle.json') {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/fhir+json' });
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 1500);
}
