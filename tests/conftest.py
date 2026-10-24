from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# Test-only signing key: exists only inside this pytest process, never in configuration files.
TEST_SIGNING_KEY = 'pyk-only-' + 'k7Qm2xVb9RtLw4Zp8NcYd3Hf6Js1Ga5E'


def research_token_headers(monkeypatch, roles=('research_operator',), user_id='usr-pytest-operator') -> dict[str, str]:
    """Configures the test signing key and returns an Authorization header for a server-issued token."""
    from app.core import auth, config
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', TEST_SIGNING_KEY)
    config.reload()
    return {'Authorization': f'Bearer {auth.issue(user_id, list(roles), 600)}'}


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_configuration():
    """Re-read configuration and drop limiter state after each test so environment changes cannot leak."""
    yield
    from app.core import config
    import app.main as main
    config.reload()
    main._limiter = None


@pytest.fixture
def test_body_site_verifier(monkeypatch):
    """Test-only stand-in for a body-site verifier. Production has none, so research routes fail closed
    (MODALITY_UNVERIFIED); this lets tests exercise the model path behind every other gate."""
    import app.main as main
    monkeypatch.setattr(main, 'BODY_SITE_VERIFIER', lambda site, image: True)
