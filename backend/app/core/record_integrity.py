"""Canonical record hashing `abhaynayan.record-hash/1` (docs/record_contract.md §8).

Reference implementation for the proposed record sync v2 (docs/API_CONTRACT.md, "Record sync v2 (proposed)").
No route uses it yet: contract 1.4.0 has no endpoint that receives envelopes or hashes. It must produce exactly the
bytes of the Android `RecordIntegrity`; both are tested against `tests/fixtures/record_integrity_vectors.json`.

A content hash detects change. It is not a signature: anyone who can rewrite a record can rewrite its hash too.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

HASH_VERSION = 'abhaynayan.record-hash/1'


def _string(s: str) -> str:
    # ensure_ascii=False escapes only '"', '\\' and U+0000-U+001F (short forms for \b \f \n \r \t, else \u00xx).
    return json.dumps(s, ensure_ascii=False)


def _value(v: Any) -> str:
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError('Non-finite numbers cannot be hashed.')
        # Exact decimal value of the binary double, as a string; -0.0 is written as "0".
        return _string('0' if v == 0.0 else format(Decimal(v), 'f'))
    if isinstance(v, str):
        return _string(v)
    raise TypeError(f'Unsupported payload type {type(v).__name__}')


def canonical_json(fields: dict[str, Any]) -> str:
    """Flat object, keys sorted by code point, no whitespace."""
    return '{' + ','.join(f'{_string(k)}:{_value(fields[k])}' for k in sorted(fields)) + '}'


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def content_sha256(fields: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(fields))


def verify_item(item: dict[str, Any]) -> list[str]:
    """Problems with one proposed v2 sync item (empty means its hashes and warning list are consistent).

    Never repairs anything: a caller must reject an item with problems, not rewrite it.
    """
    problems: list[str] = []
    record = item.get('record')
    if item.get('hash_version') != HASH_VERSION or not isinstance(record, dict) or record.get('hash_version') != HASH_VERSION:
        return ['unsupported hash_version']
    if record.get('record_id') != item.get('record_id'):
        problems.append('record_id mismatch')
    prediction = item.get('prediction')
    envelope_sha = None
    codes: list[str] = []
    if prediction is not None:
        envelope_json = prediction.get('envelope_json')
        if not isinstance(envelope_json, str):
            return problems + ['envelope_json missing']
        envelope_sha = sha256_hex(envelope_json)
        if envelope_sha != prediction.get('envelope_sha256'):
            problems.append('envelope_sha256 mismatch')
        try:
            codes = [w.get('code', '') for w in json.loads(envelope_json).get('warnings', [])]
        except (ValueError, AttributeError):
            codes = []
    if record.get('prediction_sha256') != envelope_sha:
        problems.append('prediction_sha256 mismatch')
    try:
        if content_sha256(record) != item.get('content_sha256'):
            problems.append('content_sha256 mismatch')
    except (TypeError, ValueError):
        problems.append('record fields not hashable')
    if item.get('warning_codes') != codes:
        problems.append('warning list does not match the envelope')
    return problems
