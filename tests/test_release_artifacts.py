"""Research model artifacts must never enter release/deployment artifacts (audit M7; AC-MOD-07 backend side)."""
from __future__ import annotations

import importlib.util
import io
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


checker = load_script('check_release_artifacts')
packager = load_script('package_release')


def make_zip(path: Path, names: list[str], nested: dict[str, list[str]] | None = None) -> Path:
    with zipfile.ZipFile(path, 'w') as z:
        for n in names:
            z.writestr(n, b'x')
        for inner, inner_names in (nested or {}).items():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as nz:
                for n in inner_names:
                    nz.writestr(n, b'x')
            z.writestr(inner, buf.getvalue())
    return path


CLEAN = ['AndroidManifest.xml', 'classes.dex', 'res/drawable/x.xml', 'assets/fonts/x.ttf',
         'AbhayNayan/models/MODEL_REGISTRY.json', 'AbhayNayan/models/anemia_color_baseline.json', 'AbhayNayan/docs/model_cards/hb-hgb-cf.md',
         'AbhayNayan/ml/splits/njn_v1.json', 'AbhayNayan/ml/runs/hb-v1/final_results.json']  # image-ID splits and aggregate metrics are tracked


@pytest.mark.parametrize('bad', ['assets/models/hemoglobin/model.json', 'base/assets/models/jaundice_class/model.json',
                                 'AbhayNayan/models/njn_mnv3_logreg_v1.onnx', 'AbhayNayan/models/hb_hgb_cf_v1.json',
                                 'weights/net.tflite', 'x/model.PT', 'ml/runs/hb-v1/test_predicted_vs_measured.png'])
def test_checker_flags_prohibited_entries(tmp_path, bad):
    archive = make_zip(tmp_path / 'a.zip', CLEAN + [bad])
    assert checker.prohibited_entries(archive) == [bad]
    assert checker.main([str(archive)]) == 1


def test_checker_accepts_clean_archive_and_allowed_metadata(tmp_path):
    archive = make_zip(tmp_path / 'a.apk', CLEAN)
    assert checker.prohibited_entries(archive) == []
    assert checker.main([str(archive)]) == 0


def test_checker_opens_an_apk_inside_a_release_zip(tmp_path):
    archive = make_zip(tmp_path / 'r.zip', CLEAN, nested={'AbhayNayan/android/app-debug.apk': ['assets/models/hemoglobin/model.json']})
    assert checker.prohibited_entries(archive) == ['AbhayNayan/android/app-debug.apk!assets/models/hemoglobin/model.json']


def test_checker_unreadable_archive_is_an_error(tmp_path):
    p = tmp_path / 'broken.apk'
    p.write_bytes(b'not a zip')
    assert checker.main([str(p)]) == 2


def test_dockerfile_copies_no_research_artifacts():
    copies = [line.split()[1:-1] for line in (ROOT / 'Dockerfile').read_text(encoding='utf-8').splitlines()
              if line.strip().upper().startswith('COPY ')]
    sources = [s for srcs in copies for s in srcs if not s.startswith('--')]
    assert 'models' not in sources and 'models/' not in sources and '.' not in sources  # never the whole models dir or repo
    model_files = [s for s in sources if s.startswith('models/')]
    assert model_files == ['models/anemia_color_baseline.json']  # tracked research-baseline coefficients only
    assert not any(re.search(r'(hb_|njn_|\.onnx|assets/models)', s) for s in sources)


@pytest.mark.parametrize('rel,excluded', [
    ('models/hb_hgb_cf_v1.json', True), ('models/njn_mnv3_logreg_v1.onnx', True), ('models/njn_logreg_cf_v1.json', True),
    ('android/app/src/main/assets/models/hemoglobin/model.json', True), ('data/private/hb_manifest.csv', True),
    ('ml/runs/hb-v1/test_predicted_vs_measured.png', True),
    ('models/MODEL_REGISTRY.json', False), ('models/anemia_color_baseline.json', False), ('docs/model_audit.md', False),
])
def test_release_zip_exclusions(rel, excluded):
    assert packager.is_excluded(ROOT / rel) is excluded
