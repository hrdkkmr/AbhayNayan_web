#!/usr/bin/env python3
"""Create a clean, privacy-conscious source release ZIP for AbhayNayan."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "AbhayNayan"
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", ".gradle", ".idea", "build", "dist", "out",
    "target", "coverage", ".next", ".vite", ".turbo",
}
REQUIRED_PATHS = {
    "README.md",
    "ARCHITECTURE.md",
    "PROJECT_PLAN.md",
    "backend/app/main.py",
    "web-dashboard/index.html",
    "android/gradlew",
    "android/gradle/wrapper/gradle-wrapper.jar",
    "android/app/src/main/java/in/abhaynayan/app/core/OpticalPipeline.kt",
    "android/app/src/test/java/in/abhaynayan/app/core/OpticalPipelineTest.kt",
    "tests/test_api.py",
    "scripts/run_local.sh",
}


def is_excluded(path: Path, include_android_apk: bool = False) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    name = path.name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name in {"local.properties", ".DS_Store", "Thumbs.db"}:
        return True
    lower = name.lower()
    if lower.endswith((".sqlite", ".sqlite3", ".sqlite3-shm", ".sqlite3-wal", ".db", ".pyc", ".pyo")):
        return True
    if lower.endswith((".log", ".tmp", ".bak")):
        return True
    if lower.endswith(".apk"):
        return not (include_android_apk and relative.as_posix() == "android/app/build/outputs/apk/debug/app-debug.apk")
    return False


def collect_files(include_android_apk: bool) -> list[Path]:
    files = [p for p in ROOT.rglob("*") if p.is_file() and not is_excluded(p, include_android_apk)]
    if include_android_apk:
        apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
        if not apk.is_file():
            raise SystemExit("--include-android-apk requested, but no debug APK exists at android/app/build/outputs/apk/debug/app-debug.apk")
        if apk not in files:
            files.append(apk)
    files.sort(key=lambda p: p.relative_to(ROOT).as_posix())
    return files


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "AbhayNayan-0.1.0-final.zip")
    parser.add_argument("--include-android-apk", action="store_true", help="Include a locally built debug APK (only if present). Build verification remains the operator's responsibility.")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    files = collect_files(args.include_android_apk)
    present = {p.relative_to(ROOT).as_posix() for p in files}
    missing = sorted(REQUIRED_PATHS - present)
    if missing:
        raise SystemExit("Required release files are missing: " + ", ".join(missing))

    # Never silently include a local operator secret or a generated clinical/demo database.
    if any(p.name == ".env" for p in files):
        raise SystemExit("Refusing to package a real .env file.")

    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            arcname = f"{ARCHIVE_ROOT}/{path.relative_to(ROOT).as_posix()}"
            archive.write(path, arcname)
    with ZipFile(output, "r") as archive:
        damaged = archive.testzip()
        if damaged:
            output.unlink(missing_ok=True)
            raise SystemExit(f"ZIP integrity check failed at {damaged}")
        names = set(archive.namelist())
        if any(f"{ARCHIVE_ROOT}/{name}" not in names for name in REQUIRED_PATHS):
            output.unlink(missing_ok=True)
            raise SystemExit("ZIP integrity check did not find all required release files.")

    digest = sha256(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    size_kib = output.stat().st_size / 1024
    print(f"Release ZIP: {output}")
    print(f"Files: {len(files)}")
    print(f"Size: {size_kib:.1f} KiB")
    print(f"SHA-256: {digest}")
    print(f"Checksum: {checksum_path}")
    print("Excluded: real .env files, generated SQLite databases, virtualenvs, node_modules, build outputs, and caches.")


if __name__ == "__main__":
    main()
