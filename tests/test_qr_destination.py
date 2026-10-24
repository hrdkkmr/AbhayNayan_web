"""The web QR code decodes to exactly the configured destination (independent decoder: OpenCV).

The matrix comes from the real browser module (web-dashboard/js/qr.js, run with Node) and is decoded with
cv2.QRCodeDetector. Skipped, with the reason, where Node or OpenCV is unavailable (OpenCV is in .venv-ml only).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = 'https://abhaynayan-web.onrender.com/'
cv2 = pytest.importorskip('cv2', reason='OpenCV is needed to decode the QR code (installed in .venv-ml)')
np = pytest.importorskip('numpy')
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='Node.js is needed to run the browser QR module')

SCRIPT = """
import { APP_DISTRIBUTION, validateDestination } from './web-dashboard/js/distribution.js';
import { qrMatrix } from './web-dashboard/js/qr.js';
const d = validateDestination(APP_DISTRIBUTION);
console.log(JSON.stringify({ destination: d, matrix: qrMatrix(d.url) }));
"""


def _render(matrix: list[list[bool]], scale: int = 8, quiet: int = 4):
    size = len(matrix) + 2 * quiet
    img = np.full((size, size), 255, dtype=np.uint8)
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                img[r + quiet, c + quiet] = 0
    return np.kron(img, np.ones((scale, scale), dtype=np.uint8))


def test_web_qr_decodes_to_exact_destination():
    proc = subprocess.run([NODE, '--input-type=module', '-e', SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out['destination']['ok'] is True and out['destination']['url'] == EXPECTED
    assert out['destination']['label'] == 'Open the web app'
    decoded, points, _ = cv2.QRCodeDetector().detectAndDecode(_render(out['matrix']))
    assert points is not None, 'QR not detected'
    assert decoded == EXPECTED
