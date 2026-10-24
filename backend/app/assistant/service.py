"""Assistant service: feature flag, provider choice, rate limits, and the answer pipeline used by the API.

Environment (docs/configuration.md):
  ABHAYNAYAN_ASSISTANT_ENABLED   1 (default) or 0. 0 makes POST /api/assistant/ask return 503 ASSISTANT_DISABLED.
  ABHAYNAYAN_ASSISTANT_PROVIDER  knowledge_base (default) or agent37. agent37 also needs the AGENT37_* variables.
  ABHAYNAYAN_ASSISTANT_RATE_PER_MINUTE  per client IP, default 6 (1-120)
  ABHAYNAYAN_ASSISTANT_GLOBAL_RATE_PER_MINUTE  all clients together, default 60 (1-6000)
Counters are aggregate (outcome codes only) and kept in process memory.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.assistant import agent37, core
from app.core.ratelimit import Decision, SlidingWindow

PROVIDERS = ('knowledge_base', 'agent37')
MAX_PROVIDER_CONCURRENCY = 2

_kb: core.KnowledgeBase | None = None
_lock = threading.Lock()
_per_ip: SlidingWindow | None = None
_global: SlidingWindow | None = None
_semaphore: asyncio.Semaphore | None = None
_outcomes: Counter[str] = Counter()


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name, '').strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if lo <= value <= hi else default


def enabled() -> bool:
    return os.getenv('ABHAYNAYAN_ASSISTANT_ENABLED', '1').strip().lower() not in {'0', 'false', 'no', 'off'}


def provider() -> str:
    value = os.getenv('ABHAYNAYAN_ASSISTANT_PROVIDER', 'knowledge_base').strip().lower()
    return value if value in PROVIDERS else 'knowledge_base'


def kb() -> core.KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = core.load_kb()
    return _kb


def reset_state() -> None:
    """Tests and configuration changes."""
    global _per_ip, _global, _semaphore, _kb
    with _lock:
        _per_ip = _global = None
        _semaphore = None
        _kb = None
        _outcomes.clear()


def check_rate(ip: str) -> Decision:
    global _per_ip, _global
    with _lock:
        if _per_ip is None or _global is None:
            _per_ip = SlidingWindow(_int_env('ABHAYNAYAN_ASSISTANT_RATE_PER_MINUTE', 6, 1, 120), 60.0)
            _global = SlidingWindow(_int_env('ABHAYNAYAN_ASSISTANT_GLOBAL_RATE_PER_MINUTE', 60, 1, 6000), 60.0)
        now = time.monotonic()
        if _global.count('all', now) >= _global.limit:
            return Decision(False, _global.check_and_add('all', now).retry_after_seconds, 'global')
        decision = _per_ip.check_and_add(ip, now)
        if decision.allowed:
            _global.check_and_add('all', now)
        return decision


def status() -> dict[str, Any]:
    base = kb()
    chosen = provider()
    problem = agent37.config_problem() if chosen == 'agent37' else None
    return {
        'enabled': enabled(),
        'provider': chosen if problem is None else 'knowledge_base',
        'provider_configured': chosen == 'agent37' and problem is None,
        'provider_problem': problem,
        'kb_version': base.kb_version,
        'kb_sha256': base.sha256,
        'kb_entries': len(base.entries),
        'kb_review_status': base.review_status,
        'languages': ['en'],
        'max_question_chars': core.MAX_QUESTION_CHARS,
        'outcomes': dict(_outcomes),
    }


async def ask(question: str, *, transport: Any = None) -> dict[str, Any]:
    base = kb()
    answer, entries = core.answer_without_provider(base, question)
    if answer.mode == 'KNOWLEDGE_BASE' and provider() == 'agent37':
        answer = await _with_agent37(base, question, entries, answer, transport)
    _outcomes[answer.mode if answer.mode != 'REFUSED' else f'REFUSED:{answer.refusal_code}'] += 1
    if answer.fallback_reason:
        _outcomes[f'FALLBACK:{answer.fallback_reason}'] += 1
    return {
        'mode': answer.mode,
        'answer': answer.answer,
        'sources': answer.sources,
        'entry_ids': answer.entry_ids,
        'related': answer.related,
        'refusal_code': answer.refusal_code,
        'fallback_reason': answer.fallback_reason,
        'kb_version': base.kb_version,
        'language': 'en',
        'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'notice': 'General information only. Not medical advice, a diagnosis or a result.',
    }


async def _with_agent37(base: core.KnowledgeBase, question: str, entries: list[core.Entry], kb_answer: core.Answer,
                        transport: Any) -> core.Answer:
    global _semaphore
    config = agent37.load_config()
    if config is None:
        kb_answer.fallback_reason = 'PROVIDER_NOT_CONFIGURED'
        return kb_answer
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_PROVIDER_CONCURRENCY)
    if _semaphore.locked():
        kb_answer.fallback_reason = 'PROVIDER_BUSY'
        return kb_answer
    async with _semaphore:
        result = await agent37.ask(config, core.build_provider_prompt(question, entries), kb_version=base.kb_version,
                                   transport=transport)
    if not result.ok:
        kb_answer.fallback_reason = result.reason
        return kb_answer
    validated, reason = core.validate_provider_output(result.output_text, entries)
    if validated is None:
        kb_answer.fallback_reason = reason
        return kb_answer
    if validated.mode == 'NO_ANSWER':
        # Retrieval found approved text; the provider declining to reword it is not a reason to withhold it.
        kb_answer.fallback_reason = 'PROVIDER_DECLINED'
        return kb_answer
    return validated
