"""Agent37 adapter for the information assistant (optional; server side only).

Uses the documented instance chat API (https://www.agent37.com/docs/agents-api/chat, read 24 Oct 2026):
`POST {instance_url}/v1/responses` with header `X-Agent37-Key`, body `{"input": ...}`, and a JSON reply carrying
`status` and `output_text`. A failed turn can return HTTP 200 with `status: "failed"`, so status is always checked.
`GET {instance_url}/v1/health` reports `healthy: true` once the harness is ready.

Configuration (environment only; never sent to clients or logged):
  AGENT37_API_KEY        workspace key (`sk_live_...`)
  AGENT37_INSTANCE_URL   https://<10-char instance id>.agent37.app
  AGENT37_TIMEOUT_SECONDS  5-120, default 30
Only the approved passages and the already-guarded question are sent: never records, images or identifiers.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger('abhaynayan.assistant.agent37')


class _HideInstanceUrls(logging.Filter):
    """httpx logs every request URL at INFO; the instance URL identifies the deployment, so those lines are dropped."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return '.agent37.app' not in record.getMessage() and 'api.agent37.com' not in record.getMessage()
        except Exception:  # a malformed record must not break logging
            return True


logging.getLogger('httpx').addFilter(_HideInstanceUrls())

INSTANCE_URL_PATTERN = re.compile(r'https://[a-z0-9]{10}\.agent37\.app')
DEFAULT_TIMEOUT = 30.0
MAX_RESPONSE_BYTES = 256 * 1024


@dataclass(frozen=True)
class Agent37Config:
    api_key: str
    instance_url: str
    timeout_seconds: float


@dataclass(frozen=True)
class ProviderResult:
    ok: bool
    output_text: str | None = None
    reason: str | None = None  # stable code when ok is False
    latency_ms: int = 0


def config_problem() -> str | None:
    """None when Agent37 is fully configured, otherwise a problem code (no values)."""
    key = os.getenv('AGENT37_API_KEY', '').strip()
    url = os.getenv('AGENT37_INSTANCE_URL', '').strip().rstrip('/')
    if not key and not url:
        return 'NOT_CONFIGURED'
    if not key or not url:
        return 'INCOMPLETE'
    if not key.startswith('sk_') or len(key) < 20:
        return 'MALFORMED_KEY'
    if not INSTANCE_URL_PATTERN.fullmatch(url):
        return 'MALFORMED_INSTANCE_URL'
    return None


def load_config() -> Agent37Config | None:
    if config_problem() is not None:
        return None
    raw = os.getenv('AGENT37_TIMEOUT_SECONDS', '').strip()
    try:
        timeout = min(120.0, max(5.0, float(raw))) if raw else DEFAULT_TIMEOUT
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    return Agent37Config(os.environ['AGENT37_API_KEY'].strip(), os.environ['AGENT37_INSTANCE_URL'].strip().rstrip('/'), timeout)


async def ask(config: Agent37Config, prompt: str, *, kb_version: str,
              transport: httpx.AsyncBaseTransport | None = None) -> ProviderResult:
    """One stateless turn (no session_id). Every failure becomes a ProviderResult with a reason code."""
    started = time.monotonic()
    body = {'input': prompt, 'stream': False, 'reasoning_effort': 'low',
            'metadata': {'app': 'abhaynayan-assistant', 'kb_version': kb_version}}
    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds, transport=transport, follow_redirects=False) as client:
            response = await client.post(f'{config.instance_url}/v1/responses', json=body,
                                         headers={'X-Agent37-Key': config.api_key, 'Accept': 'application/json'})
    except httpx.TimeoutException:
        return _result(False, None, 'PROVIDER_TIMEOUT', started)
    except httpx.HTTPError:
        return _result(False, None, 'PROVIDER_UNREACHABLE', started)
    if response.status_code in (401, 403):
        return _result(False, None, 'PROVIDER_AUTH_FAILED', started)
    if response.status_code == 429:
        return _result(False, None, 'PROVIDER_RATE_LIMITED', started)
    if response.status_code != 200:
        return _result(False, None, 'PROVIDER_UNAVAILABLE', started)
    if len(response.content) > MAX_RESPONSE_BYTES:
        return _result(False, None, 'PROVIDER_OUTPUT_TOO_LONG', started)
    try:
        data = response.json()
    except ValueError:
        return _result(False, None, 'PROVIDER_MALFORMED_RESPONSE', started)
    if not isinstance(data, dict):
        return _result(False, None, 'PROVIDER_MALFORMED_RESPONSE', started)
    if data.get('status') != 'completed':
        return _result(False, None, 'PROVIDER_TURN_FAILED', started)
    text = data.get('output_text')
    if not isinstance(text, str):
        return _result(False, None, 'PROVIDER_MALFORMED_RESPONSE', started)
    return _result(True, text, None, started)


async def health(config: Agent37Config, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """'healthy' | 'not_ready' | 'unreachable' | 'auth_failed' (never raises)."""
    try:
        async with httpx.AsyncClient(timeout=min(10.0, config.timeout_seconds), transport=transport) as client:
            response = await client.get(f'{config.instance_url}/v1/health', headers={'X-Agent37-Key': config.api_key})
    except httpx.HTTPError:
        return 'unreachable'
    if response.status_code in (401, 403):
        return 'auth_failed'
    try:
        return 'healthy' if response.status_code == 200 and response.json().get('healthy') is True else 'not_ready'
    except (ValueError, AttributeError):
        return 'not_ready'


def _result(ok: bool, text: str | None, reason: str | None, started: float) -> ProviderResult:
    latency = int((time.monotonic() - started) * 1000)
    # Outcome codes and latency only: never the prompt, the output, the key or the instance URL.
    logger.info('agent37 turn ok=%s reason=%s latency_ms=%d', ok, reason, latency)
    return ProviderResult(ok, text, reason, latency)
