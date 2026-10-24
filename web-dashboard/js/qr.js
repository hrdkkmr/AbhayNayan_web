import { qrcode } from './vendor/qrcode-generator-2.0.4.mjs';

const QUIET_ZONE = 4; // modules, as the QR specification requires

/** Module matrix for `text` (error correction M, smallest version that fits). Throws if it does not fit. */
export function qrMatrix(text) {
  const qr = qrcode(0, 'M');
  qr.addData(String(text), 'Byte');
  qr.make();
  const size = qr.getModuleCount();
  return Array.from({ length: size }, (_, r) => Array.from({ length: size }, (_, c) => qr.isDark(r, c)));
}

/** High-contrast SVG with a quiet zone. Black modules on white, independent of the page theme. */
export function qrSvg(text, { title = 'QR code' } = {}) {
  const matrix = qrMatrix(text);
  const n = matrix.length + QUIET_ZONE * 2;
  let path = '';
  matrix.forEach((row, r) => row.forEach((dark, c) => { if (dark) path += `M${c + QUIET_ZONE} ${r + QUIET_ZONE}h1v1h-1z`; }));
  const safeTitle = String(title).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" role="img" aria-label="${safeTitle}" shape-rendering="crispEdges"><title>${safeTitle}</title><rect width="${n}" height="${n}" fill="#ffffff"/><path d="${path}" fill="#000000"/></svg>`;
}
