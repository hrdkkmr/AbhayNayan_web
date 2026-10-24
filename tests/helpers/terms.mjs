// Shared by the JSDOM UI tests: serve the real terms file and accept the terms when the app asks (Build 2026 terms gate).
import fs from 'node:fs/promises';

export const TERMS_PATH = '/assets/terms/terms.json';
export const termsText = await fs.readFile(new URL('../../web-dashboard/assets/terms/terms.json', import.meta.url), 'utf8');

export function termsResponse(text = termsText) {
  return new Response(text, { status: 200, headers: { 'Content-Type': 'application/json' } });
}

/** Wraps a fetch mock so the terms file is served from disk; every other path goes to `fetchImpl`. */
export function withTerms(fetchImpl, text = termsText) {
  return async (path, options) => (path === TERMS_PATH ? termsResponse(text) : fetchImpl(path, options));
}

/** Clicks "I have read and accept" in the terms dialog, waiting for it first. */
export async function acceptTermsDialog(document, waitFor) {
  await waitFor(() => document.querySelector('.terms-dialog [data-action="accept-terms"]'), 'terms dialog');
  document.querySelector('.terms-dialog [data-action="accept-terms"]').click();
}
