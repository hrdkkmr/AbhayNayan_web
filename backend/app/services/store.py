from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[2] / 'data' / 'abhaynayan.sqlite3'
DB_PATH = Path(os.getenv('ABHAYNAYAN_DB_PATH', str(DEFAULT_DB)))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def ping() -> None:
    """Readiness probe: opens the database and runs a trivial query. Raises on failure."""
    with closing(connect()) as conn:
        conn.execute('SELECT 1').fetchone()


def init_db() -> None:
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            demo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS screenings (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            screening_type TEXT NOT NULL,
            estimate REAL NOT NULL,
            unit TEXT NOT NULL,
            risk_category TEXT NOT NULL,
            confidence REAL NOT NULL,
            quality_score REAL NOT NULL,
            model_mode TEXT NOT NULL,
            synthetic INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            phc TEXT NOT NULL,
            village TEXT,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(patient_id) REFERENCES patients(patient_id)
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id TEXT PRIMARY KEY,
            screening_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(screening_id) REFERENCES screenings(id)
        );
        -- Provider usage telemetry: counts and outcome codes only; never prompts, outputs, keys, or patient data.
        CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            request_type TEXT NOT NULL,
            model_id TEXT,
            model_version TEXT,
            provider_called INTEGER NOT NULL,
            outcome_code TEXT NOT NULL,
            http_status INTEGER,
            latency_ms INTEGER,
            finish_reason TEXT,
            usage_available INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER,
            candidates_tokens INTEGER,
            total_tokens INTEGER,
            cached_tokens INTEGER,
            thoughts_tokens INTEGER,
            tool_use_prompt_tokens INTEGER,
            screening_type TEXT,
            language TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_screenings_created ON screenings(created_at);
        CREATE INDEX IF NOT EXISTS idx_screenings_type ON screenings(screening_type);
        CREATE INDEX IF NOT EXISTS idx_referrals_screening ON referrals(screening_id);
        CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);
        ''')
        # Additive migration for databases created before contract 1.0.0.
        columns = {row['name'] for row in db.execute('PRAGMA table_info(screenings)')}
        if 'provenance' not in columns:
            db.execute("ALTER TABLE screenings ADD COLUMN provenance TEXT NOT NULL DEFAULT 'DEMO_SYNTHETIC'")


def _dump(model: Any) -> str:
    if hasattr(model, 'model_dump'):
        return json.dumps(model.model_dump(mode='json'), ensure_ascii=False, separators=(',', ':'))
    return json.dumps(model, ensure_ascii=False, separators=(',', ':'))


def _nullable_score(value: Any) -> float:
    # Legacy NOT NULL columns: -1 means "not produced". The JSON payload keeps null.
    return -1.0 if value is None else float(value)


def _fingerprint(payload: dict[str, Any]) -> str:
    # Fields that define a screening's meaning; timestamps and FHIR bundles are excluded.
    result = payload['result']
    key = [payload['patient']['patient_id'], result['screening_type'], result['estimate'], result['unit'],
           result.get('case_id'), result.get('provenance', 'DEMO_SYNTHETIC'), result.get('model_version')]
    return json.dumps(key, separators=(',', ':'))


def upsert_screening(record: Any) -> bool:
    return upsert_screening_status(record) == 'accepted'


def upsert_screening_status(record: Any) -> str:
    """Insert once (first write wins). Returns 'accepted', 'duplicate' (same content), or 'conflict'."""
    payload = record.model_dump(mode='json')
    result = payload['result']
    created = payload.get('created_at') or datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO patients(patient_id,demo,created_at) VALUES (?,?,?)',
                   (payload['patient']['patient_id'], int(payload['patient'].get('demo', True)), created))
        cursor = db.execute('''
            INSERT OR IGNORE INTO screenings(
                id, patient_id, screening_type, estimate, unit, risk_category,
                confidence, quality_score, model_mode, synthetic, worker_id,
                phc, village, created_at, payload_json, provenance
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            payload['id'], payload['patient']['patient_id'], result['screening_type'],
            float(result['estimate']), result['unit'], result['risk_category'],
            _nullable_score(result.get('confidence')), _nullable_score(result.get('quality_score')), result['model_mode'],
            int(bool(result.get('synthetic', True))), payload.get('worker_id', 'demo-worker'),
            payload.get('phc', 'Demo PHC'), payload.get('village'), created, _dump(payload),
            result.get('provenance', 'DEMO_SYNTHETIC'),
        ))
        if cursor.rowcount == 1:
            return 'accepted'
        row = db.execute('SELECT payload_json FROM screenings WHERE id=?', (payload['id'],)).fetchone()
    existing = json.loads(row['payload_json']) if row else None
    return 'duplicate' if existing and _fingerprint(existing) == _fingerprint(payload) else 'conflict'


def get_screenings(limit: int = 200) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute('SELECT payload_json FROM screenings ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return [json.loads(row['payload_json']) for row in rows]


def get_screening(screening_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute('SELECT payload_json FROM screenings WHERE id=?', (screening_id,)).fetchone()
    return json.loads(row['payload_json']) if row else None


def get_patients() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute('''SELECT p.patient_id, p.demo, p.created_at,
            COUNT(s.id) AS screening_count, MAX(s.created_at) AS last_screening
            FROM patients p LEFT JOIN screenings s ON p.patient_id=s.patient_id
            GROUP BY p.patient_id ORDER BY COALESCE(last_screening,p.created_at) DESC''').fetchall()
    return [dict(row) for row in rows]


def create_referral(referral_id: str, screening_id: str, payload: dict[str, Any]) -> bool:
    with connect() as db:
        cur = db.execute('INSERT OR IGNORE INTO referrals(id,screening_id,created_at,payload_json) VALUES (?,?,?,?)',
                         (referral_id, screening_id, datetime.now(timezone.utc).isoformat(), json.dumps(payload, ensure_ascii=False)))
        return cur.rowcount == 1


def get_referral(referral_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute('SELECT id,screening_id,created_at,payload_json FROM referrals WHERE id=?', (referral_id,)).fetchone()
    return {**dict(row), 'payload': json.loads(row['payload_json'])} if row else None


def get_referrals(limit: int = 200) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute('SELECT id,screening_id,created_at,payload_json FROM referrals ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return [{**dict(row), 'payload': json.loads(row['payload_json'])} for row in rows]


def dashboard_summary() -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    with connect() as db:
        totals = db.execute('SELECT COUNT(*) AS total FROM screenings').fetchone()['total']
        referrals = db.execute('SELECT COUNT(*) AS total FROM referrals').fetchone()['total']
        today_count = db.execute('SELECT COUNT(*) AS total FROM screenings WHERE substr(created_at,1,10)=?', (today,)).fetchone()['total']
        rows = db.execute('SELECT payload_json FROM screenings ORDER BY created_at DESC LIMIT 100').fetchall()
        by_provenance = {r['provenance']: r['n'] for r in db.execute('SELECT provenance, COUNT(*) AS n FROM screenings GROUP BY provenance')}
        by_type = {r['screening_type']: r['n'] for r in db.execute('SELECT screening_type, COUNT(*) AS n FROM screenings GROUP BY screening_type')}
    records = [json.loads(row['payload_json']) for row in rows]
    # pending_sync is None: the server cannot see device outboxes.
    return {'total_screenings': totals, 'referrals': referrals, 'pending_sync': None, 'today_screenings': today_count,
            'by_provenance': by_provenance, 'by_type': by_type, 'records': records}


USAGE_FIELDS = ('created_at', 'request_type', 'model_id', 'model_version', 'provider_called', 'outcome_code',
                'http_status', 'latency_ms', 'finish_reason', 'usage_available', 'prompt_tokens',
                'candidates_tokens', 'total_tokens', 'cached_tokens', 'thoughts_tokens',
                'tool_use_prompt_tokens', 'screening_type', 'language')


def record_llm_usage(event: dict[str, Any]) -> None:
    row = {name: event.get(name) for name in USAGE_FIELDS}
    row['created_at'] = row['created_at'] or datetime.now(timezone.utc).isoformat()
    row['provider_called'] = int(bool(row['provider_called']))
    row['usage_available'] = int(bool(row['usage_available']))
    with connect() as db:
        db.execute(f"INSERT INTO llm_usage({','.join(USAGE_FIELDS)}) VALUES ({','.join('?' * len(USAGE_FIELDS))})",
                   tuple(row[name] for name in USAGE_FIELDS))


def get_llm_usage(since: str | None = None, until: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[str] = []
    if since:
        clauses.append('created_at >= ?')
        params.append(since)
    if until:
        clauses.append('created_at <= ?')
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    with connect() as db:
        rows = db.execute(f"SELECT {','.join(USAGE_FIELDS)} FROM llm_usage {where} ORDER BY created_at", params).fetchall()
    return [dict(r) for r in rows]


def clear_demo_data() -> None:
    with connect() as db:
        db.executescript('DELETE FROM referrals; DELETE FROM screenings; DELETE FROM patients; DELETE FROM llm_usage;')
