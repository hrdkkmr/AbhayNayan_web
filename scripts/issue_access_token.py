"""Mint a short-lived access token for an operator (server-side tool; run where the signing key lives).

The key is read from ABHAYNAYAN_SESSION_SIGNING_KEY in the environment only, never from arguments, so it does
not appear in shell history or process lists. The token is printed to stdout and nothing is logged.
Until Google sign-in (Phase 8) exists, this is the only way to obtain a token.

    PYTHONPATH=backend python scripts/issue_access_token.py --user usr-operator-0001 --role research_operator --ttl 900
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.core import auth, config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--user', required=True, help='opaque user id, usr-<8-64 url-safe characters>')
    p.add_argument('--role', action='append', required=True, choices=sorted(auth.KNOWN_ROLES))
    p.add_argument('--ttl', type=int, default=900, help='seconds (<= ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS, default 900)')
    args = p.parse_args(argv)
    settings = config.reload()
    if not settings.auth_configured:
        bad = [f'{x.variable}={x.code}' for x in settings.problems if x.variable == 'ABHAYNAYAN_SESSION_SIGNING_KEY']
        print('error: signing key not usable: ' + (', '.join(bad) or 'unknown'), file=sys.stderr)
        return 2
    try:
        print(auth.issue(args.user, args.role, args.ttl))
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
