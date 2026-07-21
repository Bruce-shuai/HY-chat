import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.service as auth_service
from app.db.session import Base, get_db
from app.main import app
from app.storage.service import storage


@pytest.mark.asyncio
async def test_auth_roles_policy_and_token_revocation(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "backend", "local")
    monkeypatch.setattr(storage, "local_root", tmp_path / "storage")
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            first = await client.post(
                "/auth/register",
                json={
                    "email": "admin@example.com",
                    "password": "secure-password",
                    "display_name": "Admin",
                },
            )
            assert first.status_code == 201
            assert first.json()["user"]["role"] == "admin"
            admin_token = first.json()["access_token"]

            second = await client.post(
                "/auth/register",
                json={
                    "email": "user@example.com",
                    "password": "secure-password",
                    "display_name": "User",
                },
            )
            assert second.status_code == 201
            assert second.json()["user"]["role"] == "user"
            user_token = second.json()["access_token"]
            user_id = second.json()["user"]["id"]

            forbidden = await client.get(
                "/admin/stats",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert forbidden.status_code == 403

            stats = await client.get(
                "/admin/stats",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert stats.status_code == 200
            assert stats.json()["users"] == 2

            policy = await client.patch(
                f"/admin/users/{user_id}/policy",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "allowed_models": ["glm-5.1"],
                    "rpm_limit": 5,
                    "monthly_token_quota": 100,
                },
            )
            assert policy.status_code == 200
            assert policy.json()["policy"]["allowed_models"] == ["glm-5.1"]

            legacy_policy = await client.patch(
                f"/admin/users/{user_id}/policy",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "allowed_models": ["glm-5.2", "glm-4-flash", "glm-4-plus"],
                    "allow_high_cost_tools": True,
                },
            )
            assert legacy_policy.status_code == 200
            legacy_body = legacy_policy.json()["policy"]
            assert legacy_body["allowed_models"] == [
                "glm-5.2",
                "glm-5.1",
                "glm-5-turbo",
            ]
            assert legacy_body["allow_high_cost_tools"] is True

            models = await client.get(
                "/models",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert [item["id"] for item in models.json()["models"]] == [
                "glm-5.2",
                "glm-5.1",
                "glm-5-turbo",
            ]

            conversation = await client.post(
                "/conversations",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"title": "测试会话", "selected_model": "glm-5.1"},
            )
            assert conversation.status_code == 201
            created_conversation = conversation.json()

            renamed = await client.patch(
                f"/conversations/by-thread/{created_conversation['thread_id']}",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"title": "重命名会话"},
            )
            assert renamed.status_code == 200
            assert renamed.json()["title"] == "重命名会话"

            conversations = await client.get(
                "/conversations",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert conversations.json()["conversations"][0]["title"] == "重命名会话"

            deleted_conversation = await client.delete(
                f"/conversations/by-thread/{created_conversation['thread_id']}",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert deleted_conversation.status_code == 200
            conversations = await client.get(
                "/conversations",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert conversations.json()["conversations"] == []

            revoked = await client.post(
                "/auth/logout-all",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert revoked.status_code == 200
            me = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert me.status_code == 401

            delete_self = await client.delete(
                f"/admin/users/{first.json()['user']['id']}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert delete_self.status_code == 409

            deleted = await client.delete(
                f"/admin/users/{user_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert deleted.status_code == 204

            deleted_user = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {second.json()['access_token']}"},
            )
            assert deleted_user.status_code == 401

            remaining_users = await client.get(
                "/admin/users",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert len(remaining_users.json()["users"]) == 1
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.asyncio
async def test_password_change_and_reset_flows(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "backend", "local")
    monkeypatch.setattr(storage, "local_root", tmp_path / "storage")
    monkeypatch.setattr(auth_service.settings, "app_env", "local")
    monkeypatch.setattr(auth_service.settings, "password_reset_expose_token", True)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            registered = await client.post(
                "/auth/register",
                json={
                    "email": "owner@example.com",
                    "password": "secure-password",
                    "display_name": "Owner",
                },
            )
            assert registered.status_code == 201
            access_token = registered.json()["access_token"]

            wrong_current = await client.post(
                "/auth/password/change",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "current_password": "wrong-password",
                    "new_password": "stronger-password",
                },
            )
            assert wrong_current.status_code == 400

            changed = await client.post(
                "/auth/password/change",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "current_password": "secure-password",
                    "new_password": "stronger-password",
                },
            )
            assert changed.status_code == 200
            changed_token = changed.json()["access_token"]

            stale_me = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert stale_me.status_code == 401

            old_login = await client.post(
                "/auth/login",
                json={"email": "owner@example.com", "password": "secure-password"},
            )
            assert old_login.status_code == 401

            new_login = await client.post(
                "/auth/login",
                json={"email": "owner@example.com", "password": "stronger-password"},
            )
            assert new_login.status_code == 200

            missing_reset = await client.post(
                "/auth/password-reset/request",
                json={"email": "missing@example.com"},
            )
            assert missing_reset.status_code == 200
            assert missing_reset.json()["reset_token"] is None

            reset_request = await client.post(
                "/auth/password-reset/request",
                json={"email": "OWNER@example.com"},
            )
            assert reset_request.status_code == 200
            reset_token = reset_request.json()["reset_token"]
            assert reset_token

            reset = await client.post(
                "/auth/password-reset/confirm",
                json={
                    "token": reset_token,
                    "new_password": "reset-password",
                },
            )
            assert reset.status_code == 200

            stale_after_reset = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {changed_token}"},
            )
            assert stale_after_reset.status_code == 401

            reused_reset = await client.post(
                "/auth/password-reset/confirm",
                json={
                    "token": reset_token,
                    "new_password": "another-password",
                },
            )
            assert reused_reset.status_code == 401

            changed_password_login = await client.post(
                "/auth/login",
                json={"email": "owner@example.com", "password": "stronger-password"},
            )
            assert changed_password_login.status_code == 401

            reset_password_login = await client.post(
                "/auth/login",
                json={"email": "owner@example.com", "password": "reset-password"},
            )
            assert reset_password_login.status_code == 200
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
