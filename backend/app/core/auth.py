"""Verification of server-issued access tokens (compact JWS, HS256 only).

Only a holder of ABHAYNAYAN_SESSION_SIGNING_KEY can mint a valid token (scripts/issue_access_token.py today;
the Google sign-in exchange in Phase 8). Identity and roles come only from a verified token; client-supplied
headers, body fields and profile flags are never read for authorization. Tokens are never logged.

Rules: the header must be exactly alg=HS256 (no "none", no key IDs, no other algorithms); `iss`, `aud`, `sub`,
`iat`, `exp` and `jti` are required; lifetime may not exceed ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS; clock skew 60 s.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass

from app.core import config

ISSUER = 'abhaynayan-backend'
AUDIENCE = 'abhaynayan-api'
CLOCK_SKEW_SECONDS = 60
MAX_TOKEN_LENGTH = 4096
KNOWN_ROLES = frozenset({'patient', 'caregiver', 'clinician', 'org_admin', 'research_operator', 'synthetic_test', 'platform_operator'})
_SUBJECT = re.compile(r'usr-[A-Za-z0-9_-]{8,64}')
_HEADER = {'alg': 'HS256', 'typ': 'JWT'}


class AuthError(Exception):
    """Client-safe authentication failure: `code` is part of the API contract."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Principal:
    user_id: str
    roles: frozenset[str]
    token_id: str
    expires_at: int

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _b64d(text: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]*', text):
        raise ValueError('not base64url')
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _sign(key: str, signing_input: bytes) -> bytes:
    return hmac.new(key.encode('utf-8'), signing_input, hashlib.sha256).digest()


def issue(user_id: str, roles: list[str], ttl_seconds: int, key: str | None = None, now: int | None = None) -> str:
    """Mints a token. Only for server-side code and the operator CLI; never exposed as an API endpoint here."""
    settings = config.get()
    key = key or settings.session_signing_key
    if not key:
        raise AuthError(503, 'AUTH_NOT_CONFIGURED', 'Server authentication is not configured.')
    if not _SUBJECT.fullmatch(user_id):
        raise ValueError('user_id must look like usr-<8-64 url-safe characters>')
    unknown = set(roles) - KNOWN_ROLES
    if unknown or not roles:
        raise ValueError('roles must be a non-empty subset of the known roles')
    if not 0 < ttl_seconds <= settings.token_max_ttl_seconds:
        raise ValueError('ttl_seconds exceeds ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS')
    iat = int(time.time()) if now is None else now
    claims = {'iss': ISSUER, 'aud': AUDIENCE, 'sub': user_id, 'roles': sorted(set(roles)),
              'iat': iat, 'nbf': iat, 'exp': iat + ttl_seconds, 'jti': secrets.token_urlsafe(16)}
    head = _b64e(json.dumps(_HEADER, separators=(',', ':')).encode())
    body = _b64e(json.dumps(claims, separators=(',', ':')).encode())
    signing_input = f'{head}.{body}'.encode('ascii')
    return f'{head}.{body}.{_b64e(_sign(key, signing_input))}'


def _invalid() -> AuthError:
    # One message for every malformed/forged case, so responses do not help an attacker refine a token.
    return AuthError(401, 'TOKEN_INVALID', 'The access token is not valid.')


def verify(token: str, now: int | None = None) -> Principal:
    settings = config.get()
    key = settings.session_signing_key
    if not key:
        raise AuthError(503, 'AUTH_NOT_CONFIGURED', 'Server authentication is not configured.')
    if not token or len(token) > MAX_TOKEN_LENGTH or token.count('.') != 2:
        raise _invalid()
    head_b64, body_b64, sig_b64 = token.split('.')
    try:
        header = json.loads(_b64d(head_b64))
        signature = _b64d(sig_b64)
    except (ValueError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise _invalid() from None
    if header != _HEADER:
        raise _invalid()
    expected = _sign(key, f'{head_b64}.{body_b64}'.encode('ascii'))
    if not hmac.compare_digest(signature, expected):
        raise _invalid()
    try:
        claims = json.loads(_b64d(body_b64))
    except (ValueError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise _invalid() from None
    if not isinstance(claims, dict):
        raise _invalid()
    t = int(time.time()) if now is None else now
    iat, exp, nbf = claims.get('iat'), claims.get('exp'), claims.get('nbf', claims.get('iat'))
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (iat, exp, nbf))
    aud = claims.get('aud')
    audience_ok = aud == AUDIENCE or (isinstance(aud, list) and AUDIENCE in aud)
    roles = claims.get('roles')
    if (claims.get('iss') != ISSUER or not audience_ok or not ints
            or not isinstance(claims.get('sub'), str) or not _SUBJECT.fullmatch(claims['sub'])
            or not isinstance(claims.get('jti'), str) or not 8 <= len(claims['jti']) <= 128
            or not isinstance(roles, list) or not roles or not all(isinstance(r, str) and r in KNOWN_ROLES for r in roles)):
        raise _invalid()
    if exp <= iat or exp - iat > settings.token_max_ttl_seconds or iat > t + CLOCK_SKEW_SECONDS or nbf > t + CLOCK_SKEW_SECONDS:
        raise _invalid()
    if exp <= t - CLOCK_SKEW_SECONDS:
        raise AuthError(401, 'TOKEN_EXPIRED', 'The access token has expired. Request a new one.')
    return Principal(claims['sub'], frozenset(roles), claims['jti'], exp)


def bearer_token(authorization: str | None) -> str:
    """Extracts the token from `Authorization: Bearer <token>`; anything else is unauthenticated."""
    if not authorization:
        raise AuthError(401, 'UNAUTHENTICATED', 'Authentication is required. Send Authorization: Bearer <access token>.')
    scheme, _, token = authorization.strip().partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        raise AuthError(401, 'UNAUTHENTICATED', 'Authentication is required. Send Authorization: Bearer <access token>.')
    return token.strip()
