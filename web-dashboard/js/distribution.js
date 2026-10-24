// Where the "Get the AbhayNayan app" QR code points. Change only this object (docs/configuration.md §QR destination).
// kind 'web_app' opens the web app; 'android_install_page' is for an authorized public installation page, once one exists.
// Never point this at an APK file, a debug or research build, or a URL with tokens or personal data.
export const APP_DISTRIBUTION = Object.freeze({
  kind: 'web_app',
  url: 'https://abhaynayan-web.onrender.com/',
  verifiedOn: '2026-10-24',
  verification: 'HTTP 200 with the AbhayNayan page title. No public Android release exists (no GitHub releases; no Play Store listing).',
});

const KINDS = {
  web_app: { label: 'Open the web app', scanText: 'Scan to open the AbhayNayan web app in your phone’s browser. This does not install an Android app.' },
  android_install_page: { label: 'Install the Android app', scanText: 'Scan to open the official AbhayNayan Android installation page.' },
};

/** Returns { ok, kind, url, label, scanText } or { ok: false, error }. A failed check must not render a QR code. */
export function validateDestination(config = APP_DISTRIBUTION) {
  const kind = KINDS[config?.kind];
  if (!kind) return { ok: false, error: 'Unknown destination type.' };
  let url;
  try { url = new URL(String(config.url || '')); } catch { return { ok: false, error: 'The destination is not a valid URL.' }; }
  if (url.protocol !== 'https:') return { ok: false, error: 'The destination must use https.' };
  if (url.username || url.password) return { ok: false, error: 'The destination must not contain credentials.' };
  if (url.search || url.hash) return { ok: false, error: 'The destination must not contain query or fragment parts.' };
  const host = url.hostname.toLowerCase();
  if (host === 'localhost' || host.endsWith('.local') || /^[\d.]+$/.test(host) || host.includes(':')) {
    return { ok: false, error: 'The destination must be a public host name.' };
  }
  if (/\.(apk|aab|apks|xapk)$/i.test(url.pathname)) return { ok: false, error: 'The destination must be a page, not an app file.' };
  return { ok: true, kind: config.kind, url: url.href, label: kind.label, scanText: kind.scanText };
}
