const clamp = (n, min = 0, max = 1) => Math.min(max, Math.max(min, n));

function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b); const min = Math.min(r, g, b); const d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
  }
  return { h: (h * 60 + 360) % 360, s: max === 0 ? 0 : d / max, v: max };
}

function srgbToLinear(channel) {
  const v = channel / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function rgbToLabApprox(r, g, b) {
  const R = srgbToLinear(r), G = srgbToLinear(g), B = srgbToLinear(b);
  let x = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047;
  let y = (R * 0.2126 + G * 0.7152 + B * 0.0722);
  let z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883;
  const f = (t) => t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116;
  x = f(x); y = f(y); z = f(z);
  return { L: 116 * y - 16, a: 500 * (x - y), b: 200 * (y - z) };
}

function rgbToYCrCb(r, g, b) {
  const y = 0.299 * r + 0.587 * g + 0.114 * b;
  return { y, cr: (r - y) * 0.713 + 128, cb: (b - y) * 0.564 + 128 };
}

function getPixels(imageData) {
  const { data, width, height } = imageData;
  const stride = Math.max(1, Math.floor(Math.sqrt((width * height) / 10000)));
  const samples = [];
  for (let y = 0; y < height; y += stride) {
    for (let x = 0; x < width; x += stride) {
      const i = (y * width + x) * 4;
      if (data[i + 3] > 10) samples.push([data[i], data[i + 1], data[i + 2], x, y]);
    }
  }
  return samples;
}

export function extractOpticalFeatures(imageData, region = 'center') {
  if (!imageData?.data?.length) throw new Error('No pixels available for optical analysis.');
  const { width, height } = imageData;
  const pixels = getPixels(imageData);
  const samples = pixels.filter((p) => {
    const nx = p[3] / width; const ny = p[4] / height;
    return nx > 0.17 && nx < 0.83 && ny > 0.20 && ny < 0.82;
  });
  const use = samples.length > 10 ? samples : pixels;
  const sums = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
  const ratios = [];
  for (const [r, g, b] of use) {
    const hsv = rgbToHsv(r, g, b);
    const lab = rgbToLabApprox(r, g, b);
    const ycc = rgbToYCrCb(r, g, b);
    sums[0] += r; sums[1] += g; sums[2] += b;
    sums[3] += hsv.h; sums[4] += hsv.s * 100; sums[5] += hsv.v * 100;
    sums[6] += lab.L; sums[7] += lab.a; sums[8] += lab.b;
    sums[9] += ycc.y; sums[10] += ycc.cr; sums[11] += ycc.cb;
    ratios.push(r / Math.max(1, g));
  }
  const n = Math.max(1, use.length);
  const mean = sums.map((x) => x / n);
  return {
    region,
    sampleCount: use.length,
    rgb: { r: round(mean[0], 2), g: round(mean[1], 2), b: round(mean[2], 2) },
    hsv: { h: round(mean[3], 2), s: round(mean[4], 2), v: round(mean[5], 2) },
    labApprox: { L: round(mean[6], 2), a: round(mean[7], 2), b: round(mean[8], 2) },
    yCrCb: { y: round(mean[9], 2), cr: round(mean[10], 2), cb: round(mean[11], 2) },
    redGreenRatio: round(ratios.reduce((a, b) => a + b, 0) / Math.max(1, ratios.length), 4),
    note: 'Prototype optical features only; not a hemoglobin or bilirubin measurement.',
  };
}

function round(n, places = 3) { return Number(Number(n).toFixed(places)); }

export function assessImageQuality(imageData, { regionConfirmed = false, motion = 0, synthetic = false, regionLabel = 'target region' } = {}) {
  if (synthetic) {
    return {
      ready: true, qualityScore: 0.91, brightness: 126, blurScore: 0.84,
      motionScore: 0.04, regionDetected: false, regionConfirmed: true,
      status: 'SYNTHETIC DEMO', reasons: [],
      detail: 'Abstract synthetic image; anatomy and model output are not real.',
    };
  }
  if (!imageData?.data?.length) {
    return { ready: false, qualityScore: 0, brightness: 0, blurScore: 0, motionScore: 0, regionDetected: false,
      regionConfirmed, status: 'NO IMAGE', reasons: ['Capture or select an image.'] };
  }
  const { data, width, height } = imageData;
  const count = Math.max(1, Math.floor((width * height) / 10000));
  let luminance = 0; let edge = 0; let samples = 0;
  const stride = Math.max(1, Math.floor(Math.sqrt((width * height) / 7000)));
  const grid = [];
  for (let y = 1; y < height - 1; y += stride) {
    for (let x = 1; x < width - 1; x += stride) {
      const idx = (y * width + x) * 4;
      const l = 0.2126 * data[idx] + 0.7152 * data[idx + 1] + 0.0722 * data[idx + 2];
      luminance += l; samples++;
      const right = idx + 4; const down = idx + width * 4;
      const lr = 0.2126 * data[right] + 0.7152 * data[right + 1] + 0.0722 * data[right + 2];
      const ld = 0.2126 * data[down] + 0.7152 * data[down + 1] + 0.0722 * data[down + 2];
      edge += Math.abs(l - lr) + Math.abs(l - ld);
      if (grid.length < 3000) grid.push(l);
    }
  }
  const brightness = luminance / Math.max(1, samples);
  const avgEdge = edge / Math.max(1, samples);
  const blurScore = clamp((avgEdge - 1.4) / 18);
  const motionScore = clamp(Number(motion) || 0);
  const lightScore = clamp(1 - Math.abs(brightness - 126) / 126);
  const reasons = [];
  if (brightness < 32) reasons.push('Too dark — add soft ambient light.');
  if (brightness > 228) reasons.push('Too bright — move away from glare or direct sunlight.');
  if (blurScore < 0.10) reasons.push('Image may be blurred — steady the phone and refocus.');
  if (motionScore > 0.48) reasons.push('Too much movement — pause and hold the phone still.');
  if (!regionConfirmed) reasons.push(`Confirm the ${regionLabel} is inside the guide before continuing.`);
  const qualityScore = clamp((lightScore * 0.45) + (blurScore * 0.35) + ((1 - motionScore) * 0.20));
  const ready = brightness >= 32 && brightness <= 228 && blurScore >= 0.10 && motionScore <= 0.48 && regionConfirmed;
  return {
    ready, qualityScore: round(qualityScore, 2), brightness: round(brightness, 1), blurScore: round(blurScore, 2),
    motionScore: round(motionScore, 2), regionDetected: false, regionConfirmed,
    status: ready ? 'QUALITY CHECK PASSED' : 'RECAPTURE / REPOSITION', reasons,
    detail: 'Brightness and edge sharpness are measured locally; device motion is not measured. Face/eye landmarks are not bundled; region confirmation is manual.',
  };
}

export function correctAmbientLight(ambientImageData, flashImageData = null, { synthetic = false } = {}) {
  if (!ambientImageData?.data?.length) return { available: false, message: 'No ambient frame available.', lightingQuality: 0 };
  if (!flashImageData?.data?.length) {
    const features = extractOpticalFeatures(ambientImageData, 'manual-center-roi');
    return { available: false, corrected: false, lightingQuality: 0.65, features,
      message: 'Flash/ambient pair unavailable; using one ambient frame only. No subtraction was performed.' };
  }
  const a = ambientImageData.data; const f = flashImageData.data;
  if (a.length !== f.length) return { available: false, corrected: false, lightingQuality: 0.3,
    message: 'Frame dimensions differ; correction skipped.' };
  const corrected = new Uint8ClampedArray(a.length);
  let delta = 0;
  for (let i = 0; i < a.length; i += 4) {
    for (let c = 0; c < 3; c++) {
      const d = f[i + c] - a[i + c];
      delta += Math.abs(d);
      // A guarded positive differential is shown only as an engineering visualization.
      corrected[i + c] = Math.round(clamp((d + 36) / 219) * 255);
    }
    corrected[i + 3] = 255;
  }
  const meanDelta = delta / Math.max(1, (a.length / 4) * 3);
  const output = new ImageData(corrected, ambientImageData.width, ambientImageData.height);
  return {
    available: true, corrected: true, synthetic,
    lightingQuality: round(clamp(1 - Math.abs(meanDelta - 42) / 90), 2),
    meanFrameDelta: round(meanDelta, 2), features: extractOpticalFeatures(output, 'manual-center-roi'),
    message: synthetic ? 'Synthetic A/B frame demonstration only; not clinically calibrated.' : 'Experimental pair correction; not clinically validated.',
  };
}

export function createSyntheticImage(canvas, screeningType, caseId = 'case-a') {
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const w = canvas.width = 640; const h = canvas.height = 360;
  const isJaundice = screeningType === 'neonatal_jaundice';
  const risk = String(caseId).includes('high') || String(caseId).includes('c') ? 2 : (String(caseId).includes('moderate') || String(caseId).includes('b') ? 1 : 0);
  const palettes = isJaundice
    ? [[222, 206, 154], [224, 188, 95], [205, 145, 53]]
    : [[175, 92, 96], [176, 119, 124], [190, 157, 157]];
  const base = palettes[Math.min(2, risk)];
  const background = ctx.createLinearGradient(0, 0, w, h);
  background.addColorStop(0, `rgb(${Math.max(0, base[0]-30)},${Math.max(0, base[1]-25)},${Math.max(0, base[2]-24)})`);
  background.addColorStop(1, `rgb(${Math.min(255, base[0]+22)},${Math.min(255, base[1]+19)},${Math.min(255, base[2]+15)})`);
  ctx.fillStyle = background; ctx.fillRect(0, 0, w, h);
  ctx.globalAlpha = 0.22;
  for (let i = 0; i < 26; i++) {
    const x = ((i * 73) % w) + 8; const y = ((i * 41) % h) + 4;
    ctx.beginPath(); ctx.ellipse(x, y, 8 + (i % 11), 3 + (i % 7), (i % 5) * 0.18, 0, Math.PI * 2);
    ctx.fillStyle = i % 2 ? '#fff5e9' : '#7b554e'; ctx.fill();
  }
  ctx.globalAlpha = 1;
  ctx.strokeStyle = 'rgba(255,255,255,.58)'; ctx.lineWidth = 2; ctx.setLineDash([9, 7]);
  ctx.beginPath(); ctx.ellipse(w/2, h/2, 184, 101, 0, 0, Math.PI*2); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = 'rgba(8,37,42,.78)'; ctx.fillRect(16, 15, 244, 31);
  ctx.fillStyle = '#e6faf1'; ctx.font = '700 12px system-ui';
  ctx.fillText(`SYNTHETIC ${isJaundice ? 'SCLERA' : 'CONJUNCTIVA'} ROI · NOT A PATIENT IMAGE`, 27, 35);
  ctx.fillStyle = 'rgba(255,255,255,.88)'; ctx.font = '600 11px system-ui';
  ctx.fillText('ABSTRACT COLOUR PATCH FOR PIPELINE DEMO ONLY', 21, h - 19);
  return canvas;
}

export function imageDataFromCanvas(canvas, scale = 0.5) {
  const w = Math.max(1, Math.floor(canvas.width * scale));
  const h = Math.max(1, Math.floor(canvas.height * scale));
  const small = document.createElement('canvas'); small.width = w; small.height = h;
  const ctx = small.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(canvas, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h);
}
