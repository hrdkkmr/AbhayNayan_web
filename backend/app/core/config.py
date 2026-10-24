"""Server configuration: parsing and validation of environment variables.

Problems are reported as (variable, code) pairs only. Values are never placed in messages or logs.
In `production`, any error-level problem stops the application at startup. In `development` and `test`
the same problems are logged and shown by /api/ready, so local and offline workflows keep working.
See docs/configuration.md for every variable, its default and the startup behaviour.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger('abhaynayan.config')

ENVIRONMENTS = ('development', 'test', 'production')
MIN_SECRET_LENGTH = 32
MIN_DISTINCT_CHARS = 12
HARD_MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Lower-cased substrings that mark a value as a placeholder or a well-known weak default.
PLACEHOLDER_MARKERS = ('change', 'replace', 'placeholder', 'example', 'your', 'secret', 'password', 'dummy', 'sample',
                       'todo', 'xxxx', 'test', 'default', 'insecure', 'demo')
RESEARCH_FLAGS = ('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', 'ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA')


class ConfigurationError(RuntimeError):
    """Raised at startup for an invalid production configuration. The message names variables and codes only."""


@dataclass(frozen=True)
class Problem:
    variable: str
    code: str
    severity: str  # 'error' | 'warning'

    def as_dict(self) -> dict[str, str]:
        return {'variable': self.variable, 'code': self.code, 'severity': self.severity}


@dataclass(frozen=True)
class Settings:
    environment: str
    session_signing_key: str | None
    token_max_ttl_seconds: int
    image_rate_per_minute: int
    image_rate_per_day: int
    image_max_concurrent: int
    auth_failures_per_minute_per_ip: int
    max_image_bytes: int
    allow_origins: tuple[str, ...]
    admin_token_set: bool
    gemini_key_set: bool
    gemini_model_set: bool
    research_flags_on: tuple[str, ...]
    worker_count: int
    problems: tuple[Problem, ...] = field(default_factory=tuple)

    @property
    def auth_configured(self) -> bool:
        return self.session_signing_key is not None

    @property
    def errors(self) -> tuple[Problem, ...]:
        return tuple(p for p in self.problems if p.severity == 'error')


def _flag(name: str) -> bool:
    return os.getenv(name, '').strip().lower() in {'1', 'true', 'yes'}


def secret_problem(value: str) -> str | None:
    """Returns a problem code for a weak secret, or None. Never returns or logs the value."""
    if len(value) < MIN_SECRET_LENGTH:
        return 'TOO_SHORT'
    lowered = value.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return 'PLACEHOLDER'
    if len(set(value)) < MIN_DISTINCT_CHARS:
        return 'LOW_ENTROPY'
    return None


def _int(name: str, default: int, lo: int, hi: int, problems: list[Problem]) -> int:
    raw = os.getenv(name, '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        problems.append(Problem(name, 'MALFORMED', 'error'))
        return default
    if not lo <= value <= hi:
        problems.append(Problem(name, 'OUT_OF_RANGE', 'error'))
        return default
    return value


def load() -> Settings:
    problems: list[Problem] = []
    environment = os.getenv('ABHAYNAYAN_ENV', 'development').strip().lower() or 'development'
    if environment not in ENVIRONMENTS:
        # Unknown environments fail closed everywhere: a typo must not silently mean "development".
        problems.append(Problem('ABHAYNAYAN_ENV', 'UNKNOWN_ENVIRONMENT', 'error'))
    production = environment == 'production'
    prod_severity = 'error' if production else 'warning'

    key = os.getenv('ABHAYNAYAN_SESSION_SIGNING_KEY', '').strip()
    signing_key: str | None = None
    if not key:
        problems.append(Problem('ABHAYNAYAN_SESSION_SIGNING_KEY', 'MISSING', prod_severity))
    elif (code := secret_problem(key)) is not None:
        # A weak key is never used, in any environment: protected endpoints then report AUTH_NOT_CONFIGURED.
        problems.append(Problem('ABHAYNAYAN_SESSION_SIGNING_KEY', code, 'error' if production else 'warning'))
    else:
        signing_key = key

    admin = os.getenv('ABHAYNAYAN_ADMIN_TOKEN', '').strip()
    if admin and production and (code := secret_problem(admin)) is not None:
        problems.append(Problem('ABHAYNAYAN_ADMIN_TOKEN', code, 'error'))

    origins = tuple(x.strip() for x in os.getenv('ABHAYNAYAN_ALLOW_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',') if x.strip())
    if production:
        if not os.getenv('ABHAYNAYAN_ALLOW_ORIGINS', '').strip():
            problems.append(Problem('ABHAYNAYAN_ALLOW_ORIGINS', 'MISSING', 'error'))
        if any(o == '*' for o in origins):
            problems.append(Problem('ABHAYNAYAN_ALLOW_ORIGINS', 'WILDCARD_ORIGIN', 'error'))
        if any(not o.startswith('https://') for o in origins if o != '*'):
            problems.append(Problem('ABHAYNAYAN_ALLOW_ORIGINS', 'INSECURE_ORIGIN', 'error'))

    gemini_key, gemini_model = bool(os.getenv('GEMINI_API_KEY', '').strip()), bool(os.getenv('GEMINI_MODEL', '').strip())
    if gemini_key != gemini_model:
        problems.append(Problem('GEMINI_MODEL' if gemini_key else 'GEMINI_API_KEY', 'INCOMPLETE', 'warning'))

    research_on = tuple(name for name in RESEARCH_FLAGS if _flag(name))
    if production:
        # Research artifacts derive from datasets whose licences are unverified (docs/model_audit.md §6).
        problems.extend(Problem(name, 'NOT_ALLOWED_IN_PRODUCTION', 'error') for name in research_on)

    workers = 1
    for name in ('WEB_CONCURRENCY', 'ABHAYNAYAN_WORKERS'):
        raw = os.getenv(name, '').strip()
        if raw.isdigit():
            workers = max(workers, int(raw))
    if production and workers > 1:
        # The rate limiter keeps counters in process memory; several workers would each allow the full quota.
        problems.append(Problem('WEB_CONCURRENCY', 'RATE_LIMITER_REQUIRES_SINGLE_PROCESS', 'error'))

    settings = Settings(
        environment=environment,
        session_signing_key=signing_key,
        token_max_ttl_seconds=_int('ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS', 3600, 60, 12 * 3600, problems),
        image_rate_per_minute=_int('ABHAYNAYAN_IMAGE_RATE_PER_MINUTE', 10, 1, 600, problems),
        image_rate_per_day=_int('ABHAYNAYAN_IMAGE_RATE_PER_DAY', 100, 1, 100_000, problems),
        image_max_concurrent=_int('ABHAYNAYAN_IMAGE_MAX_CONCURRENT', 2, 1, 32, problems),
        auth_failures_per_minute_per_ip=_int('ABHAYNAYAN_AUTH_FAILURES_PER_MINUTE_PER_IP', 20, 1, 1000, problems),
        max_image_bytes=_int('ABHAYNAYAN_MAX_IMAGE_BYTES', HARD_MAX_IMAGE_BYTES, 64 * 1024, HARD_MAX_IMAGE_BYTES, problems),
        allow_origins=origins,
        admin_token_set=bool(admin),
        gemini_key_set=gemini_key,
        gemini_model_set=gemini_model,
        research_flags_on=research_on,
        worker_count=workers,
        problems=tuple(problems),
    )
    return settings


def validate_for_startup(settings: Settings) -> None:
    """Stops a production start on any error; logs (names and codes only) otherwise."""
    for p in settings.problems:
        logger.warning('configuration %s %s=%s', p.severity, p.variable, p.code)
    if settings.environment not in ENVIRONMENTS or (settings.environment == 'production' and settings.errors):
        summary = ', '.join(f'{p.variable}={p.code}' for p in settings.errors)
        raise ConfigurationError(f'Invalid configuration for environment {settings.environment[:32]!r}: {summary}')


_current: Settings | None = None


def get() -> Settings:
    global _current
    if _current is None:
        _current = load()
    return _current


def reload() -> Settings:
    """Re-reads the environment (startup and tests)."""
    global _current
    _current = load()
    return _current
