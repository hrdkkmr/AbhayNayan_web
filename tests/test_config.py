"""Startup configuration validation (Phase 4, AC-SEC-11 partial). Values must never appear in messages."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.services import store

STRONG = 'Zq8rT2vW6yB1nM4kL7pX3cF9hJ5gD0sA-uE'
CLEAN = ['ABHAYNAYAN_ENV', 'ABHAYNAYAN_SESSION_SIGNING_KEY', 'ABHAYNAYAN_ADMIN_TOKEN', 'ABHAYNAYAN_ALLOW_ORIGINS', 'GEMINI_API_KEY',
         'GEMINI_MODEL', 'ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', 'ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA', 'WEB_CONCURRENCY',
         'ABHAYNAYAN_WORKERS', 'ABHAYNAYAN_IMAGE_RATE_PER_MINUTE', 'ABHAYNAYAN_MAX_IMAGE_BYTES']


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in CLEAN:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')

    def set_(**values):
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        return config.reload()
    return set_


def production(**extra) -> dict:
    return {'ABHAYNAYAN_ENV': 'production', 'ABHAYNAYAN_SESSION_SIGNING_KEY': STRONG,
            'ABHAYNAYAN_ALLOW_ORIGINS': 'https://app.invalid', **extra}


def codes(settings) -> set[tuple[str, str]]:
    return {(p.variable, p.code) for p in settings.errors}


def test_development_defaults_start_without_any_secret(env):
    s = env()
    assert s.environment == 'development' and not s.errors
    assert ('ABHAYNAYAN_SESSION_SIGNING_KEY', 'MISSING') in {(p.variable, p.code) for p in s.problems}
    config.validate_for_startup(s)  # no exception: local and offline workflows keep working
    assert s.auth_configured is False


def test_valid_production_configuration_starts(env):
    s = env(**production())
    assert not s.errors and s.auth_configured
    config.validate_for_startup(s)
    with TestClient(app) as c:
        assert c.get('/api/health').status_code == 200


@pytest.mark.parametrize('key,code', [
    ('short-Zq8rT2v', 'TOO_SHORT'),
    ('change-me-Zq8rT2vW6yB1nM4kL7pX3cF9hJ5', 'PLACEHOLDER'),
    ('your-signing-key-goes-here-0123456789', 'PLACEHOLDER'),
    ('a' * 48, 'LOW_ENTROPY'),
    ('abababababababababababababababababab', 'LOW_ENTROPY'),
])
def test_weak_production_signing_key_blocks_startup_without_echoing_it(env, key, code):
    s = env(**production(ABHAYNAYAN_SESSION_SIGNING_KEY=key))
    assert ('ABHAYNAYAN_SESSION_SIGNING_KEY', code) in codes(s)
    with pytest.raises(config.ConfigurationError) as e:
        config.validate_for_startup(s)
    assert key not in str(e.value) and 'ABHAYNAYAN_SESSION_SIGNING_KEY' in str(e.value) and code in str(e.value)


def test_missing_production_key_stops_the_app(env):
    env(**production(ABHAYNAYAN_SESSION_SIGNING_KEY=''))
    with pytest.raises(config.ConfigurationError) as e:
        with TestClient(app):
            pass
    assert 'ABHAYNAYAN_SESSION_SIGNING_KEY=MISSING' in str(e.value)


@pytest.mark.parametrize('origins,code', [('*', 'WILDCARD_ORIGIN'), ('http://app.invalid', 'INSECURE_ORIGIN'), ('', 'MISSING')])
def test_production_origins(env, origins, code):
    s = env(**production(ABHAYNAYAN_ALLOW_ORIGINS=origins))
    assert ('ABHAYNAYAN_ALLOW_ORIGINS', code) in codes(s)


@pytest.mark.parametrize('flag', config.RESEARCH_FLAGS)
def test_research_flags_not_allowed_in_production(env, flag):
    s = env(**production(**{flag: '1'}))
    assert (flag, 'NOT_ALLOWED_IN_PRODUCTION') in codes(s)


def test_research_flags_allowed_in_development(env):
    s = env(ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS='1')
    assert not s.errors and s.research_flags_on == ('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS',)


def test_multiple_workers_rejected_in_production(env):
    s = env(**production(WEB_CONCURRENCY='4'))
    assert ('WEB_CONCURRENCY', 'RATE_LIMITER_REQUIRES_SINGLE_PROCESS') in codes(s)


def test_weak_admin_token_rejected_in_production_only(env):
    weak = 'admin-token-12345678'
    assert ('ABHAYNAYAN_ADMIN_TOKEN', 'TOO_SHORT') in codes(env(**production(ABHAYNAYAN_ADMIN_TOKEN=weak)))
    assert not env(ABHAYNAYAN_ENV='development', ABHAYNAYAN_ADMIN_TOKEN=weak).errors


@pytest.mark.parametrize('value', ['staging', 'prod', 'Production '])
def test_unknown_environment_fails_closed_everywhere(env, value):
    s = env(ABHAYNAYAN_ENV=value)
    if value.strip().lower() == 'production':
        assert s.environment == 'production'
        return
    with pytest.raises(config.ConfigurationError):
        config.validate_for_startup(s)


@pytest.mark.parametrize('name,value,code', [
    ('ABHAYNAYAN_IMAGE_RATE_PER_MINUTE', 'ten', 'MALFORMED'),
    ('ABHAYNAYAN_IMAGE_RATE_PER_MINUTE', '0', 'OUT_OF_RANGE'),
    ('ABHAYNAYAN_MAX_IMAGE_BYTES', str(64 * 1024 * 1024), 'OUT_OF_RANGE'),  # cannot raise above the 8 MB hard limit
])
def test_numeric_settings_validated(env, name, value, code):
    s = env(**production(**{name: value}))
    assert (name, code) in codes(s)
    assert s.max_image_bytes <= config.HARD_MAX_IMAGE_BYTES


def test_incomplete_gemini_is_a_warning_not_a_startup_failure(env):
    s = env(**production(GEMINI_API_KEY='AIza-not-checked-here-only-presence'))
    assert ('GEMINI_MODEL', 'INCOMPLETE') in {(p.variable, p.code) for p in s.problems}
    config.validate_for_startup(s)


def test_logged_problems_never_contain_values(env, caplog):
    caplog.set_level(logging.WARNING, logger='abhaynayan.config')
    secret = 'change-me-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345'
    s = env(ABHAYNAYAN_SESSION_SIGNING_KEY=secret, ABHAYNAYAN_ADMIN_TOKEN='admin-short')
    config.validate_for_startup(s)
    assert 'ABHAYNAYAN_SESSION_SIGNING_KEY=PLACEHOLDER' in caplog.text
    assert secret not in caplog.text and 'admin-short' not in caplog.text


# ----- .env.example agrees with the validator --------------------------------------------------------

from pathlib import Path  # noqa: E402
import re  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / '.env.example'


def example_values() -> dict[str, str]:
    out = {}
    for line in EXAMPLE.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def test_env_example_lists_every_variable_the_validator_reads():
    read = set(re.findall(r"os\.getenv\('([A-Z0-9_]+)'", (Path(config.__file__)).read_text(encoding='utf-8')))
    read |= set(re.findall(r"_int\('([A-Z0-9_]+)'", Path(config.__file__).read_text(encoding='utf-8')))
    text = EXAMPLE.read_text(encoding='utf-8')
    missing = sorted(v for v in read | set(config.RESEARCH_FLAGS) if v not in text)
    assert missing == []


def test_env_example_starts_in_development_with_research_closed(env):
    s = env(**example_values())
    assert s.environment == 'development' and not s.errors
    assert s.auth_configured is False  # the placeholder key is never used
    assert s.research_flags_on == ()
    assert ('ABHAYNAYAN_SESSION_SIGNING_KEY', 'PLACEHOLDER') in {(p.variable, p.code) for p in s.problems}


def test_env_example_placeholders_are_rejected_in_production(env):
    s = env(**{**example_values(), 'ABHAYNAYAN_ENV': 'production'})
    found = codes(s)
    assert ('ABHAYNAYAN_SESSION_SIGNING_KEY', 'PLACEHOLDER') in found
    assert ('ABHAYNAYAN_ALLOW_ORIGINS', 'INSECURE_ORIGIN') in found
    with pytest.raises(config.ConfigurationError):
        config.validate_for_startup(s)


def test_env_example_contains_no_secret_values():
    for k, v in example_values().items():
        if any(w in k for w in ('KEY', 'TOKEN', 'SECRET')) and v:
            assert config.secret_problem(v) is not None, k  # any non-empty secret slot must be a rejected placeholder
