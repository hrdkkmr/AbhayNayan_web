"""Record hashing `abhaynayan.record-hash/1`: shared vectors with Android and the proposed v2 sync item checks."""
import copy
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import record_integrity as ri
from app.main import app
from app.services import store

VECTORS = json.loads((Path(__file__).parent / 'fixtures' / 'record_integrity_vectors.json').read_text(encoding='utf-8'))


def _fields(vector):
    def value(t, v):
        return {'null': lambda: None, 'bool': lambda: v == 'true', 'int': lambda: int(v), 'double': lambda: float(v), 'string': lambda: v}[t]()
    return {k: value(t, v) for k, t, v in vector['fields']}


@pytest.mark.parametrize('vector', VECTORS['vectors'], ids=lambda v: v['name'])
def test_shared_vectors(vector):
    fields = _fields(vector)
    assert ri.canonical_json(fields) == vector['canonical']
    assert ri.content_sha256(fields) == vector['sha256']


def test_canonical_form_is_independent_of_insertion_order():
    a = {'b': 1, 'a': 'x', 'c': None}
    assert ri.canonical_json(a) == ri.canonical_json(dict(reversed(list(a.items())))) == '{"a":"x","b":1,"c":null}'


def test_doubles_are_exact_decimal_strings_and_non_finite_is_refused():
    assert ri.canonical_json({'v': -0.0}) == ri.canonical_json({'v': 0.0}) == '{"v":"0"}'
    assert ri.canonical_json({'v': 12.0}) == '{"v":"12"}'
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            ri.canonical_json({'v': bad})


def _item():
    envelope = json.dumps({'schema': 'abhaynayan.prediction/2.0.0', 'result_id': 'prd-x', 'status': 'unable_to_estimate',
                           'warnings': [{'code': 'ORIENTATION_UNKNOWN'}, {'code': 'ORIENTATION_UNKNOWN'}]}, separators=(',', ':'))
    record = _fields(next(v for v in VECTORS['vectors'] if v['name'] == 'full_record_payload'))
    record['prediction_sha256'] = ri.sha256_hex(envelope)
    record['estimate'] = None
    return {'record_id': record['record_id'], 'hash_version': ri.HASH_VERSION, 'content_sha256': ri.content_sha256(record),
            'record': record, 'prediction': {'envelope_json': envelope, 'envelope_sha256': ri.sha256_hex(envelope)},
            'warning_codes': ['ORIENTATION_UNKNOWN', 'ORIENTATION_UNKNOWN']}


def test_consistent_item_has_no_problems_and_keeps_duplicate_warnings():
    assert ri.verify_item(_item()) == []


@pytest.mark.parametrize('tamper, expected', [
    (lambda i: i['prediction'].update(envelope_json=i['prediction']['envelope_json'].replace(',{"code":"ORIENTATION_UNKNOWN"}', '')),
     'envelope_sha256 mismatch'),
    (lambda i: i.update(warning_codes=['ORIENTATION_UNKNOWN']), 'warning list does not match the envelope'),
    (lambda i: i['record'].update(estimate=11.2), 'content_sha256 mismatch'),
    (lambda i: i['record'].update(record_id='scr-other'), 'record_id mismatch'),
    (lambda i: i.update(prediction=None), 'prediction_sha256 mismatch'),
    (lambda i: i.update(hash_version='abhaynayan.record-hash/9'), 'unsupported hash_version'),
])
def test_tampering_is_detected_not_repaired(tamper, expected):
    item = _item()
    tamper(item)
    before = copy.deepcopy(item)
    assert expected in ri.verify_item(item)
    assert item == before  # verification never rewrites the item


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    with TestClient(app) as test_client:
        yield test_client


def test_no_v2_sync_endpoint_is_exposed(client):
    # The format is specified and checkable, but no route accepts it yet (contract 1.4.0 added only the help assistant).
    assert client.post('/api/v2/sync', json=[_item()]).status_code in (404, 405)
    assert client.get('/api/health').json()['api_contract_version'] == '1.4.0'
