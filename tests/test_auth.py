import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
