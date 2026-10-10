const CASES = {
  maternal_anemia: {
    'maternal-normal': { value: 11.8, unit: 'g/dL', category: 'DEMO_LOW', confidence: 0.82, quality: 0.91, name: 'Normal-like (synthetic)' },
    'maternal-moderate': { value: 9.4, unit: 'g/dL', category: 'DEMO_MODERATE', confidence: 0.82, quality: 0.91, name: 'Moderate-risk-like (synthetic)' },
    'maternal-high': { value: 7.8, unit: 'g/dL', category: 'DEMO_HIGH', confidence: 0.79, quality: 0.90, name: 'Higher-review (synthetic)' },
  },
  neonatal_jaundice: {
    'jaundice-review': { value: 12.8, unit: 'mg/dL', category: 'REQUIRES_REVIEW', confidence: 0.79, quality: 0.90, name: 'Review case (synthetic)' },
    'jaundice-escalate': { value: 18.0, unit: 'mg/dL', category: 'DEMO_ESCALATE', confidence: 0.76, quality: 0.88, name: 'Escalation-like (synthetic)' },
  },
};

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
    confidence: item.confidence,
    quality_score: item.quality,
    requires_confirmation: true,
    model_mode: 'DEMO',
    case_id: caseId,
    case_label: item.name,
    synthetic: true,
    generated_at: new Date().toISOString(),
    safety_note: 'Synthetic demonstration estimate only. Not a diagnosis or validated measurement. Confirm with appropriate clinical testing and local protocol.',
  };
}

export function formatEstimate(result) {
  const digits = result.screening_type === 'maternal_anemia' ? 1 : 1;
  return `${Number(result.estimate).toFixed(digits)} ${result.unit}`;
}

export function riskTone(category) {
  if (String(category).includes('HIGH') || String(category).includes('ESCALATE')) return 'red';
  if (String(category).includes('MODERATE') || String(category).includes('REVIEW')) return 'amber';
  return 'green';
}
