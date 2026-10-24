# ADR-003: PostgreSQL for multi-user records; SQLite stays for local dev and tests

Status: **Proposed** (24 Oct 2026) · Hosting choice pending

## Context
`services/store.py` uses SQLite with hand-written SQL. That is fine for a single-tenant demo, but multi-user records with relationships, concurrent writers on a hosted service and audit logs need a server database. Render's free web instances have ephemeral disks, so SQLite data does not survive a redeploy there.

## Decision
- Introduce SQLAlchemy 2 Core + Alembic migrations. PostgreSQL in production; SQLite remains for tests and local runs through the same layer.
- Migrate existing tables first with no behaviour change (tests must stay green), then add `users`, `subjects`, `grants`, `organizations`, `audit_log`.
- No object storage until an upload feature needs it. When added: private bucket, per-object server-issued signed URLs with short expiry.

## Consequences
Adds two dependencies and a migration step to deploys. Needs a managed Postgres choice (Render, Neon, Supabase).
