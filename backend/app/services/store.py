from __future__ import annotations

import json
import os
import sqlite3
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
        CREATE INDEX IF NOT EXISTS idx_screenings_created ON screenings(created_at);
        CREATE INDEX IF NOT EXISTS idx_screenings_type ON screenings(screening_type);
        CREATE INDEX IF NOT EXISTS idx_referrals_screening ON referrals(screening_id);
        ''')


def _dump(model: Any) -> str:
    if hasattr(model, 'model_dump'):
        return json.dumps(model.model_dump(mode='json'), ensure_ascii=False, separators=(',', ':'))
    return json.dumps(model, ensure_ascii=False, separators=(',', ':'))


def upsert_screening(record: Any) -> bool:
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
                phc, village, created_at, payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            payload['id'], payload['patient']['patient_id'], result['screening_type'],
            float(result['estimate']), result['unit'], result['risk_category'],
            float(result['confidence']), float(result['quality_score']), result['model_mode'],
            int(bool(result.get('synthetic', True))), payload.get('worker_id', 'demo-worker'),
            payload.get('phc', 'Demo PHC'), payload.get('village'), created, _dump(payload),
        ))
        return cursor.rowcount == 1


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
    records = [json.loads(row['payload_json']) for row in rows]
    return {'total_screenings': totals, 'referrals': referrals, 'pending_sync': 0,
            'today_screenings': today_count, 'records': records}


def clear_demo_data() -> None:
    with connect() as db:
        db.executescript('DELETE FROM referrals; DELETE FROM screenings; DELETE FROM patients;')
