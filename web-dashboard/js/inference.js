// Fixed demonstration values, mirrored from backend/app/core/inference.py. They carry no
// confidence or quality score: a fixture has neither, so the contract sends null.
const CASES = {
  maternal_anemia: {
    'maternal-normal': { value: 11.8, unit: 'g/dL', category: 'DEMO_LOW', name: 'Normal-like (synthetic)' },
    'maternal-moderate': { value: 9.4, unit: 'g/dL', category: 'DEMO_MODERATE', name: 'Moderate-risk-like (synthetic)' },
    'maternal-high': { value: 7.8, unit: 'g/dL', category: 'DEMO_HIGH', name: 'Higher-review (synthetic)' },
  },
  neonatal_jaundice: {
    'jaundice-review': { value: 12.8, unit: 'mg/dL', category: 'DEMO_REVIEW', name: 'Review case (synthetic)' },
    'jaundice-escalate': { value: 18.0, unit: 'mg/dL', category: 'DEMO_ESCALATE', name: 'Escalation-like (synthetic)' },
  },
};
export const DEMO_MODEL_VERSION = 'fixed-demo-fixtures-v1';

export const PROVENANCE = {
  DEMO_SYNTHETIC: { label: 'Synthetic demo value', short: 'DEMO', tone: 'badge-amber', detail: 'Fixed demonstration value. Not computed from any image or person.' },
  EXPERIMENTAL_RESEARCH_ONLY: { label: 'Experimental research output', short: 'EXPERIMENTAL', tone: 'badge-red', detail: 'Output of a non-validated research model. Not a measurement.' },
  VALIDATED_FOR_INTENDED_USE: { label: 'Validated screening estimate', short: 'VALIDATED', tone: 'badge-blue', detail: 'Screening estimate only; confirm with laboratory testing.' },
};

export function provenanceOf(result) {
  // Records saved before contract 1.0 have no provenance field; they were all demo fixtures.
  return result?.provenance || (result?.synthetic === false ? 'EXPERIMENTAL_RESEARCH_ONLY' : 'DEMO_SYNTHETIC');
}

export function getDemoCases(screeningType) {
  const cases = CASES[screeningType] || {};
  return Object.entries(cases).map(([id, item]) => ({ id, ...item }));
}

export function runDemoInference(screeningType, caseId) {
  const item = CASES[screeningType]?.[caseId];
  if (!item) throw new Error('Choose a supported synthetic demonstration case.');
  return {
    screening_type: screeningType,
    estimate: item.value,
    unit: item.unit,
    risk_category: item.category,
    confidence: null,
    quality_score: null,
    requires_confirmation: true,
    model_mode: 'DEMO',
    synthetic: true,
    provenance: 'DEMO_SYNTHETIC',
    model_version: DEMO_MODEL_VERSION,
    case_id: caseId,
    case_label: item.name,
    generated_at: new Date().toISOString(),
    limitations: ['Fixed demonstration value; not computed from any image, feature, or person.'],
    safety_note: 'Synthetic demonstration estimate only. Not a diagnosis or validated measurement. Confirm with appropriate clinical testing and local protocol.',
  };
}

export function formatEstimate(result) {
  return `${Number(result.estimate).toFixed(1)} ${result.unit}`;
}

export function formatScore(value, missing = 'Not available') {
  return value === null || value === undefined || Number.isNaN(Number(value)) ? missing : `${Math.round(Number(value) * 100)}%`;
}

export function riskTone(category) {
  if (String(category).includes('HIGH') || String(category).includes('ESCALATE')) return 'red';
  if (String(category).includes('MODERATE') || String(category).includes('REVIEW')) return 'amber';
  return 'green';
}
