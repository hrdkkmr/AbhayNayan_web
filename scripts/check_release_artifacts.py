"""Fail if a release archive (ZIP, APK, AAB) contains research model artifacts.

Research models derive from datasets whose licences are unverified (docs/model_audit.md §6, finding M7), so they
must never be distributed. The patterns match the Android Gradle task `verifyRelease*HasNoResearchModels`.
Prints entry names only; exits 1 if anything prohibited is found, 2 if an archive cannot be read.

    python scripts/check_release_artifacts.py dist/AbhayNayan-0.1.0-final.zip app-release.aab
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

PROHIBITED = (
    re.compile(r'(^|/)assets/models/'),                       # Android research assets (also base/assets/ in AABs)
    re.compile(r'\.(onnx|tflite|keras|h5|pt|pth)$', re.I),    # model weight formats
    re.compile(r'(^|/)models/(hb|njn)_[^/]*$'),               # trained research artifacts (web repo models/ layout)
    re.compile(r'predicted_vs_measured', re.I),               # per-patient evaluation plots
)


def prohibited_entries(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
    found = [n for n in names if any(p.search(n) for p in PROHIBITED)]
    # An APK/AAB inside a ZIP is opened and checked too.
    for inner in (n for n in names if n.lower().endswith(('.apk', '.aab'))):
        with zipfile.ZipFile(archive) as z, z.open(inner) as fh:
            with zipfile.ZipFile(io.BytesIO(fh.read())) as nested:
                found += [f'{inner}!{n}' for n in nested.namelist() if any(p.search(n) for p in PROHIBITED)]
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print('usage: check_release_artifacts.py ARCHIVE [ARCHIVE ...]', file=sys.stderr)
        return 2
    status = 0
    for arg in argv:
        path = Path(arg)
        try:
            found = prohibited_entries(path)
        except (OSError, zipfile.BadZipFile):
            print(f'{path.name}: cannot read archive', file=sys.stderr)
            return 2
        if found:
            status = 1
            print(f'{path.name}: PROHIBITED research model files:')
            for name in found:
                print(f'  {name}')
        else:
            print(f'{path.name}: ok, no research model files')
    return status


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
