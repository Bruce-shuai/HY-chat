import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.service as auth_service
import app.policies.service as policy_service
from app.auth.service import create_user
from app.core.config import (
    DEFAULT_JWT_SECRET_KEY,
    Settings,
    validate_runtime_settings,
)
from app.core.types import UserRole
from app.db.models import UserPolicy
from app.db.session import Base
from app.policies.service import authorize_model_access, record_token_usage
from app.tracing.service import REDACTED_VALUE, safe_json


def test_production_settings_reject_unsafe_defaults():
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        JWT_SECRET_KEY=DEFAULT_JWT_SECRET_KEY,
        INITIAL_ADMIN_EMAIL="",
        CORS_ORIGINS="*",
    )

    with pytest.raises(RuntimeError) as exc_info:
        validate_runtime_settings(settings)

    message = str(exc_info.value)
    assert "JWT_SECRET_KEY" in message
    assert "INITIAL_ADMIN_EMAIL" in message
    assert "CORS_ORIGINS" in message


def test_production_settings_accept_explicit_security_configuration():
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        JWT_SECRET_KEY="a-production-secret-with-more-than-32-characters",
        INITIAL_ADMIN_EMAIL="owner@example.com",
        CORS_ORIGINS="https://chat.example.com",
    )

    validate_runtime_settings(settings)


def test_configured_admin_email_prevents_first_registration_takeover(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(
        auth_service.settings, "initial_admin_email", "owner@example.com"
    )
    try:
        ordinary = create_user(db, "first@example.com", "secure-password", "First")
        owner = create_user(db, "owner@example.com", "secure-password", "Owner")
        later = create_user(db, "later@example.com", "secure-password", "Later")

        assert ordinary.role is UserRole.USER
        assert owner.role is UserRole.ADMIN
        assert later.role is UserRole.USER
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_trace_payload_redacts_common_credentials_recursively():
    payload = safe_json(
        {
            "Authorization": "Bearer top-secret",
            "nested": {
                "password": "plain-text-password",
                "prompt_tokens": 42,
                "provider_secret": "provider-secret",
            },
        }
    )

    assert payload == {
        "Authorization": REDACTED_VALUE,
        "nested": {
            "password": REDACTED_VALUE,
            "prompt_tokens": 42,
            "provider_secret": REDACTED_VALUE,
        },
    }


def test_trace_payload_summarizes_large_binary_fields():
    payload = safe_json(
        {
            "type": "image",
            "mimeType": "image/png",
            "data": "a" * 600,
        }
    )

    assert payload["data"]["redacted"] is True
    assert payload["data"]["reason"] == "large-binary-field"
    assert payload["data"]["chars"] == 600
    assert payload["data"]["sha256"]


def test_model_authorization_does_not_consume_rpm_and_token_updates_are_atomic(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    monkeypatch.setattr(auth_service.settings, "initial_admin_email", "")

    def fail_if_rpm_is_consumed(*_args):
        raise AssertionError("authorization-only checks must not consume RPM")

    monkeypatch.setattr(policy_service.redis, "incr", fail_if_rpm_is_consumed)
    try:
        user = create_user(db, "owner@example.com", "secure-password", "Owner")
        policy = authorize_model_access(
            db, user.id, auth_service.settings.zhipu_chat_model
        )
        assert policy.tokens_used == 0

        record_token_usage(db, user.id, 10)
        record_token_usage(db, user.id, 15)
        db.expire_all()

        assert db.get(UserPolicy, user.id).tokens_used == 25
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
