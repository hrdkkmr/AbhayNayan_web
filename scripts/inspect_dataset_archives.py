#!/usr/bin/env python3
"""Inventory a ZIP archive without extracting or downloading its members.

Works on a local path or a shared HTTPS URL that supports byte-range requests (Google Drive
`drive.usercontent.google.com/download?...&confirm=t` links do). Only the ZIP central
directory is read, so no images or records are fetched. Output is aggregate: member counts by
extension and folder, plus the names of non-image files (label tables, documents).

    python scripts/inspect_dataset_archives.py <path-or-url> [--depth 2]
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import zipfile
from pathlib import Path

IMAGE_EXT = {'jpg', 'jpeg', 'png', 'bmp', 'tif', 'tiff', 'heic', 'webp'}


class RangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests."""

    def __init__(self, url: str) -> None:
        import httpx
        self.client = httpx.Client(follow_redirects=True, timeout=60)
        self.url, self.pos, self.fetched = url, 0, 0
        response = self.client.get(url, headers={'Range': 'bytes=0-0'})
        if response.status_code != 206:
            raise SystemExit(f'Server does not support range requests (HTTP {response.status_code}).')
        self.size = int(response.headers['content-range'].split('/')[-1])

    def seekable(self) -> bool: return True
    def readable(self) -> bool: return True
    def tell(self) -> int: return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b''
        end = min(self.size, self.pos + n) - 1
        data = self.client.get(self.url, headers={'Range': f'bytes={self.pos}-{end}'}).content
        self.pos += len(data)
        self.fetched += len(data)
        return data

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def inventory(source: str, depth: int) -> dict:
    handle = RangeFile(source) if source.startswith('https://') else open(Path(source), 'rb')
    with zipfile.ZipFile(handle) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
    ext = lambda m: m.filename.rsplit('.', 1)[-1].lower() if '.' in m.filename.rsplit('/', 1)[-1] else '<none>'  # noqa: E731
    return {
        'archive_bytes': getattr(handle, 'size', None) or Path(source).stat().st_size,
        'bytes_read_for_listing': getattr(handle, 'fetched', None),
        'members': len(members),
        'by_extension': dict(collections.Counter(ext(m) for m in members)),
        'by_folder': dict(sorted(collections.Counter('/'.join(m.filename.split('/')[:-1][:depth]) for m in members).items())),
        'non_image_members': [{'name': m.filename, 'bytes': m.file_size} for m in members if ext(m) not in IMAGE_EXT],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source')
    parser.add_argument('--depth', type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(inventory(args.source, args.depth), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
