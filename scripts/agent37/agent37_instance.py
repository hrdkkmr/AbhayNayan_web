"""Agent37 instance helper for the AbhayNayan assistant (docs/build2026/agent37.md).

Needs AGENT37_API_KEY (workspace key, sk_live_...) in the environment. The key is never printed or written.
Raw evidence goes to evidence/local/agent37/ (ignored by Git); review it before sharing.

  python scripts/agent37/agent37_instance.py create [--budget-micros 2000000]   # POST /v1/instances (billing starts)
  python scripts/agent37/agent37_instance.py health --instance-url https://<id>.agent37.app
  python scripts/agent37/agent37_instance.py smoke  --instance-url https://<id>.agent37.app
  python scripts/agent37/agent37_instance.py delete --instance-id <id> --yes     # ends billing, removes the instance

`smoke` sends the evaluation set's normal and ambiguous questions through the real API pipeline with
ABHAYNAYAN_ASSISTANT_PROVIDER=agent37, and also shows that refused questions never reach the provider.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
API = 'https://api.agent37.com'
EVIDENCE = ROOT / 'evidence' / 'local' / 'agent37'


def _key() -> str:
    key = os.getenv('AGENT37_API_KEY', '').strip()
    if not key:
        raise SystemExit('Set AGENT37_API_KEY in the environment (never on the command line or in a file in Git).')
    return key


def _save(name: str, data: dict) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f'{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{name}.json'
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(f'evidence: {path}')
    return path


def create(budget_micros: int) -> int:
    body = {'template': 'agent37-hermes', 'name': 'abhaynayan-assistant', 'budget': {'credit_micros': budget_micros},
            'metadata': {'project': 'abhaynayan', 'purpose': 'non-clinical information assistant'}}
    r = httpx.post(f'{API}/v1/instances', json=body, headers={'Authorization': f'Bearer {_key()}'}, timeout=300)
    print('HTTP', r.status_code)
    try:
        data = r.json()
    except ValueError:
        print(r.text[:500])
        return 1
    keep = {k: data.get(k) for k in ('id', 'url', 'status', 'template', 'name', 'created', 'created_at') if k in data}
    _save('create', {'http_status': r.status_code, 'request': body, 'response': keep if r.is_success else data})
    if r.is_success:
        print(f"instance id {keep.get('id')}  url {keep.get('url')}")
        print('Next: set AGENT37_INSTANCE_URL to that url (server environment only) and run `health`, then `smoke`.')
    return 0 if r.is_success else 1


def health(instance_url: str) -> int:
    os.environ['AGENT37_INSTANCE_URL'] = instance_url
    from app.assistant import agent37
    config = agent37.load_config()
    if config is None:
        print('configuration problem:', agent37.config_problem())
        return 2
    state = asyncio.run(agent37.health(config))
    _save('health', {'instance_url': instance_url, 'health': state, 'checked_at': datetime.now(timezone.utc).isoformat()})
    print('health:', state)
    return 0 if state == 'healthy' else 1


def smoke(instance_url: str) -> int:
    os.environ.update({'AGENT37_INSTANCE_URL': instance_url, 'ABHAYNAYAN_ASSISTANT_PROVIDER': 'agent37',
                       'AGENT37_TIMEOUT_SECONDS': os.getenv('AGENT37_TIMEOUT_SECONDS', '60')})
    from app.assistant import agent37, service
    if agent37.config_problem():
        print('configuration problem:', agent37.config_problem())
        return 2
    calls = {'n': 0}
    original = agent37.ask

    async def counted(*a, **kw):
        calls['n'] += 1
        return await original(*a, **kw)

    agent37.ask = counted
    cases = json.loads((ROOT / 'scripts' / 'assistant_eval' / 'eval_cases.json').read_text(encoding='utf-8'))['cases']
    rows = []

    async def run_all():
        for case in cases:
            if case['category'] not in ('normal', 'ambiguous', 'unsafe', 'personal'):
                continue
            before = calls['n']
            out = await service.ask(case['question'])
            rows.append({'id': case['id'], 'category': case['category'], 'mode': out['mode'],
                         'fallback_reason': out['fallback_reason'], 'refusal_code': out['refusal_code'],
                         'provider_called': calls['n'] > before, 'entry_ids': out['entry_ids'],
                         'answer_chars': len(out['answer'])})
            print(f"{case['id']:4} {case['category']:10} {out['mode']:15} {out['fallback_reason'] or ''}")

    asyncio.run(run_all())
    summary = {
        'questions': len(rows),
        'answered_by_agent37': sum(r['mode'] == 'AGENT37' for r in rows),
        'knowledge_base_fallbacks': sum(r['mode'] == 'KNOWLEDGE_BASE' for r in rows),
        'refused_without_provider_call': sum(r['mode'] == 'REFUSED' and not r['provider_called'] for r in rows),
        'refused_with_provider_call': sum(r['mode'] == 'REFUSED' and r['provider_called'] for r in rows),
        'provider_calls': calls['n'],
    }
    _save('smoke', {'instance_url': instance_url, 'kb_version': service.kb().kb_version, 'summary': summary, 'rows': rows,
                    'note': 'Answer texts are not stored here; see the instance logs in the Agent37 dashboard.'})
    print(json.dumps(summary, indent=2))
    return 0 if summary['answered_by_agent37'] > 0 and summary['refused_with_provider_call'] == 0 else 1


def delete(instance_id: str, yes: bool) -> int:
    if not yes:
        print('Deleting removes the instance and its data permanently. Re-run with --yes to confirm.')
        return 2
    r = httpx.delete(f'{API}/v1/instances/{instance_id}', headers={'Authorization': f'Bearer {_key()}'}, timeout=120)
    _save('delete', {'instance_id': instance_id, 'http_status': r.status_code})
    print('HTTP', r.status_code)
    return 0 if r.is_success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('create')
    c.add_argument('--budget-micros', type=int, default=2_000_000, help='credit cap in micro-dollars (default $2)')
    for name in ('health', 'smoke'):
        p = sub.add_parser(name)
        p.add_argument('--instance-url', required=True)
    d = sub.add_parser('delete')
    d.add_argument('--instance-id', required=True)
    d.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    if args.command == 'create':
        return create(args.budget_micros)
    if args.command == 'health':
        return health(args.instance_url)
    if args.command == 'smoke':
        return smoke(args.instance_url)
    return delete(args.instance_id, args.yes)


if __name__ == '__main__':
    raise SystemExit(main())
