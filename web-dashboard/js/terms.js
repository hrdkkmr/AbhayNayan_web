// Terms & Conditions: loading and version-based acceptance. Content: /assets/terms/terms.json (canonical; Android ships a copy).
// Acceptance is stored only on this device as { version, acceptance_version, accepted_at }: no name or identifier.
export const TERMS_URL = '/assets/terms/terms.json';
export const ACCEPTANCE_SETTING = 'termsAcceptance';

export async function loadTerms(fetcher = fetch) {
  const response = await fetcher(TERMS_URL, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Terms could not be loaded (${response.status}).`);
  const terms = await response.json();
  if (!terms?.version || !terms?.acceptance_version || !Array.isArray(terms.sections)) throw new Error('Terms file is malformed.');
  return terms;
}

/** True when this device has no acceptance of the current material version (acceptance_version). */
export function acceptanceNeeded(terms, accepted) {
  if (!terms) return true;
  return !accepted || accepted.acceptance_version !== terms.acceptance_version || !accepted.accepted_at;
}

/** Recorded only after the person pressed "I accept" on a screen that showed the terms. */
export function acceptanceRecord(terms, now = new Date()) {
  return { version: terms.version, acceptance_version: terms.acceptance_version, accepted_at: now.toISOString() };
}
