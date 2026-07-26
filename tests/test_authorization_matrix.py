from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.rag.service as rag_service_module
from app.auth.service import create_token
from app.auth.types import TokenType
from app.core.config import get_settings
from app.core.types import UserRole
from app.db.models import (
    Conversation,
    KnowledgeDocument,
    StoredFile,
    TraceSpan,
    User,
    UserMemory,
    UserPolicy,
)
from app.db.session import Base, get_db
from app.main import app
from app.rag.service import RagService
from app.services.file_service import FileService
from app.services.memory_service import remember_from_messages, user_memory_map
from app.storage.service import storage


@dataclass(frozen=True)
class AuthorizationMatrix:
    client: TestClient
    session_factory: sessionmaker[Session]
    headers: dict[str, dict[str, str]]
    ids: dict[str, str]


@dataclass(frozen=True)
class AccessAttempt:
    name: str
    method: str
    path: str
    kwargs: dict[str, Any]
    expected_status: int = 404


@pytest.fixture
def isolated_langgraph_auth(monkeypatch: pytest.MonkeyPatch):
    init_db_module = importlib.import_module("app.db.init_db")
    monkeypatch.setattr(init_db_module, "init_db", lambda: None)
    previous_module = sys.modules.pop("app.auth.langgraph", None)
    module = importlib.import_module("app.auth.langgraph")
    try:
        yield module
    finally:
        sys.modules.pop("app.auth.langgraph", None)
        if previous_module is not None:
            sys.modules["app.auth.langgraph"] = previous_module


def _policy() -> UserPolicy:
    settings = get_settings()
    return UserPolicy(
        allowed_models=settings.available_chat_models,
        rpm_limit=30,
        monthly_token_quota=1_000_000,
        tokens_used=0,
        quota_reset_at=datetime.utcnow(),
        allow_high_cost_tools=False,
    )


def _user(user_id: str, email: str, role: UserRole) -> User:
    user = User(
        id=user_id,
        email=email,
        display_name=user_id,
        password_hash="not-used-by-token-auth-tests",
        role=role,
        is_active=True,
        token_version=0,
    )
    user.policy = _policy()
    return user


@pytest.fixture(scope="module")
def authorization_matrix(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("authorization-matrix")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    previous_backend = storage.backend
    previous_local_root = storage.local_root
    storage.backend = "local"
    storage.local_root = root / "storage"

    ids = {
        "admin": "admin-user",
        "user_a": "user-a",
        "user_b": "user-b",
        "conversation": "conversation-a",
        "thread": "thread-a",
        "document": "document-a",
        "trace": "trace-a",
    }
    source_path = root / "owner-a-file.txt"
    source_path.write_text("private file owned by user A", encoding="utf-8")
    rag_path = root / "owner-a-rag.txt"
    rag_path.write_text("private RAG document owned by user A", encoding="utf-8")

    with testing_session() as db:
        users = {
            "admin": _user(ids["admin"], "admin@example.com", UserRole.ADMIN),
            "user_a": _user(ids["user_a"], "a@example.com", UserRole.USER),
            "user_b": _user(ids["user_b"], "b@example.com", UserRole.USER),
        }
        db.add_all(users.values())
        db.add(
            Conversation(
                id=ids["conversation"],
                user_id=ids["user_a"],
                thread_id=ids["thread"],
                title="A private conversation",
                selected_model=get_settings().zhipu_chat_model,
            )
        )
        db.commit()

        stored_file = FileService(db).create_from_path(
            path=source_path,
            user_id=ids["user_a"],
            filename=source_path.name,
            content_type="text/plain",
            conversation_id=ids["conversation"],
        )
        ids["file"] = stored_file.id

        db.add_all(
            [
                KnowledgeDocument(
                    id=ids["document"],
                    user_id=ids["user_a"],
                    stored_file_id=stored_file.id,
                    filename=rag_path.name,
                    content_type="text/plain",
                    file_path=str(rag_path),
                    sha256="a" * 64,
                    status="ready",
                    chunk_count=1,
                ),
                TraceSpan(
                    id=ids["trace"],
                    user_id=ids["user_a"],
                    conversation_id=ids["conversation"],
                    thread_id=ids["thread"],
                    run_id="run-a",
                    name="model:authorization-matrix",
                    span_type="model",
                    status="success",
                    input={"messages": [{"role": "user", "content": "A secret"}]},
                    output={"content": "A private answer"},
                ),
            ]
        )
        db.commit()
        headers = {
            name: {"Authorization": f"Bearer {create_token(user, TokenType.ACCESS)}"}
            for name, user in users.items()
        }

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield AuthorizationMatrix(
            client=client,
            session_factory=testing_session,
            headers=headers,
            ids=ids,
        )
    finally:
        client.close()
        app.dependency_overrides.clear()
        storage.backend = previous_backend
        storage.local_root = previous_local_root
        Base.metadata.drop_all(engine)
        engine.dispose()


USER_B_DENIED_ATTEMPTS = [
    AccessAttempt(
        "conversation.read",
        "GET",
        "/conversations/{conversation}",
        {},
    ),
    AccessAttempt(
        "conversation.update",
        "PATCH",
        "/conversations/{conversation}",
        {"json": {"title": "B overwrote A"}},
    ),
    AccessAttempt(
        "conversation.delete",
        "DELETE",
        "/conversations/{conversation}",
        {},
    ),
    AccessAttempt(
        "thread.update",
        "PATCH",
        "/conversations/by-thread/{thread}",
        {"json": {"title": "B overwrote A through thread ID"}},
    ),
    AccessAttempt(
        "thread.delete",
        "DELETE",
        "/conversations/by-thread/{thread}",
        {},
    ),
    AccessAttempt(
        "file.read",
        "GET",
        "/files/{file}/content",
        {},
    ),
    AccessAttempt(
        "file.presign",
        "GET",
        "/files/{file}/download-url",
        {},
    ),
    AccessAttempt(
        "file.delete",
        "DELETE",
        "/files/{file}",
        {},
    ),
    AccessAttempt(
        "file.associate-with-foreign-conversation",
        "POST",
        "/files",
        {
            "data": {"conversation_id": "{conversation}"},
            "files": {"file": ("b.txt", b"B must not attach here", "text/plain")},
        },
    ),
    AccessAttempt(
        "rag.delete",
        "DELETE",
        "/rag/documents/{document}",
        {},
    ),
    AccessAttempt(
        "trace.read",
        "GET",
        "/traces/{trace}",
        {},
    ),
    AccessAttempt(
        "chat.invoke-with-foreign-conversation",
        "POST",
        "/chat/stream",
        {
            "json": {
                "message": "read A conversation",
                "conversation_id": "{conversation}",
                "use_cache": False,
            }
        },
    ),
    AccessAttempt(
        "chat.invoke-with-foreign-thread",
        "POST",
        "/chat/stream",
        {
            "json": {
                "message": "resume A thread",
                "thread_id": "{thread}",
                "use_cache": False,
            }
        },
    ),
]


def _format_values(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format_map(ids)
    if isinstance(value, dict):
        return {key: _format_values(item, ids) for key, item in value.items()}
    if isinstance(value, list):
        return [_format_values(item, ids) for item in value]
    if isinstance(value, tuple):
        return tuple(_format_values(item, ids) for item in value)
    return value


@pytest.mark.parametrize(
    "attempt",
    USER_B_DENIED_ATTEMPTS,
    ids=lambda attempt: attempt.name,
)
def test_user_b_cannot_access_user_a_resources(
    authorization_matrix: AuthorizationMatrix,
    attempt: AccessAttempt,
):
    response = authorization_matrix.client.request(
        attempt.method,
        attempt.path.format_map(authorization_matrix.ids),
        headers=authorization_matrix.headers["user_b"],
        **_format_values(attempt.kwargs, authorization_matrix.ids),
    )

    assert response.status_code == attempt.expected_status


@pytest.mark.parametrize(
    ("path", "collection_key", "resource_id"),
    [
        ("/conversations", "conversations", "conversation"),
        ("/files", "files", "file"),
        ("/rag/documents", "documents", "document"),
        ("/traces", "traces", "trace"),
        ("/traces?all_users=true", "traces", "trace"),
    ],
)
def test_user_b_lists_never_disclose_user_a_resources(
    authorization_matrix: AuthorizationMatrix,
    path: str,
    collection_key: str,
    resource_id: str,
):
    response = authorization_matrix.client.get(
        path,
        headers=authorization_matrix.headers["user_b"],
    )

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()[collection_key]}
    assert authorization_matrix.ids[resource_id] not in returned_ids


@pytest.mark.parametrize(
    ("path", "collection_key", "resource_id"),
    [
        ("/conversations", "conversations", "conversation"),
        ("/files", "files", "file"),
        ("/rag/documents", "documents", "document"),
        ("/traces", "traces", "trace"),
    ],
)
def test_user_a_can_read_own_resources(
    authorization_matrix: AuthorizationMatrix,
    path: str,
    collection_key: str,
    resource_id: str,
):
    response = authorization_matrix.client.get(
        path,
        headers=authorization_matrix.headers["user_a"],
    )

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()[collection_key]}
    assert authorization_matrix.ids[resource_id] in returned_ids


def test_user_a_created_conversation_remains_private_from_user_b(
    authorization_matrix: AuthorizationMatrix,
):
    created = authorization_matrix.client.post(
        "/conversations",
        headers=authorization_matrix.headers["user_a"],
        json={
            "title": "A created through API",
            "selected_model": get_settings().zhipu_chat_model,
        },
    )

    assert created.status_code == 201
    conversation_id = created.json()["id"]
    with authorization_matrix.session_factory() as db:
        assert (
            db.get(Conversation, conversation_id).user_id
            == (authorization_matrix.ids["user_a"])
        )

    denied = authorization_matrix.client.get(
        f"/conversations/{conversation_id}",
        headers=authorization_matrix.headers["user_b"],
    )
    assert denied.status_code == 404

    cleanup = authorization_matrix.client.delete(
        f"/conversations/{conversation_id}",
        headers=authorization_matrix.headers["user_a"],
    )
    assert cleanup.status_code == 200


def test_user_a_created_file_remains_private_from_user_b(
    authorization_matrix: AuthorizationMatrix,
):
    created = authorization_matrix.client.post(
        "/files",
        headers=authorization_matrix.headers["user_a"],
        data={"conversation_id": authorization_matrix.ids["conversation"]},
        files={
            "file": (
                "created-by-a.txt",
                b"private upload created by A",
                "text/plain",
            )
        },
    )

    assert created.status_code == 201
    file_id = created.json()["id"]
    with authorization_matrix.session_factory() as db:
        assert (
            db.get(StoredFile, file_id).user_id == (authorization_matrix.ids["user_a"])
        )

    denied = authorization_matrix.client.get(
        f"/files/{file_id}/download-url",
        headers=authorization_matrix.headers["user_b"],
    )
    assert denied.status_code == 404

    cleanup = authorization_matrix.client.delete(
        f"/files/{file_id}",
        headers=authorization_matrix.headers["user_a"],
    )
    assert cleanup.status_code == 200


def test_user_a_created_rag_document_remains_private_from_user_b(
    authorization_matrix: AuthorizationMatrix,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    monkeypatch.setattr(
        rag_service_module.settings,
        "rag_upload_dir",
        str(tmp_path / "rag"),
    )
    monkeypatch.setattr(
        rag_service_module.EmbeddingService,
        "embed_documents",
        lambda self, texts: [[0.0] * self.dimensions for _ in texts],
    )

    created = authorization_matrix.client.post(
        "/rag/documents",
        headers=authorization_matrix.headers["user_a"],
        files={
            "file": (
                "created-by-a.txt",
                b"private RAG content created by A",
                "text/plain",
            )
        },
    )

    assert created.status_code == 200
    document_id = created.json()["id"]
    with authorization_matrix.session_factory() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document.user_id == authorization_matrix.ids["user_a"]
        stored_file_id = document.stored_file_id

    denied = authorization_matrix.client.delete(
        f"/rag/documents/{document_id}",
        headers=authorization_matrix.headers["user_b"],
    )
    assert denied.status_code == 404

    cleanup = authorization_matrix.client.delete(
        f"/rag/documents/{document_id}",
        headers=authorization_matrix.headers["user_a"],
    )
    assert cleanup.status_code == 200
    with authorization_matrix.session_factory() as db:
        stored_file = db.get(StoredFile, stored_file_id)
        if stored_file:
            FileService(db).delete(stored_file)


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("GET", "/conversations/{conversation}", 404),
        ("GET", "/files/{file}/download-url", 404),
        ("DELETE", "/rag/documents/{document}", 404),
        ("GET", "/traces/{trace}", 200),
    ],
)
def test_admin_cross_user_access_matches_explicit_api_policy(
    authorization_matrix: AuthorizationMatrix,
    method: str,
    path: str,
    expected_status: int,
):
    response = authorization_matrix.client.request(
        method,
        path.format_map(authorization_matrix.ids),
        headers=authorization_matrix.headers["admin"],
    )

    assert response.status_code == expected_status


def test_only_admin_all_users_trace_query_discloses_user_a_trace(
    authorization_matrix: AuthorizationMatrix,
):
    default_response = authorization_matrix.client.get(
        "/traces",
        headers=authorization_matrix.headers["admin"],
    )
    all_users_response = authorization_matrix.client.get(
        "/traces?all_users=true",
        headers=authorization_matrix.headers["admin"],
    )

    assert default_response.status_code == 200
    assert authorization_matrix.ids["trace"] not in {
        item["id"] for item in default_response.json()["traces"]
    }
    assert all_users_response.status_code == 200
    assert authorization_matrix.ids["trace"] in {
        item["id"] for item in all_users_response.json()["traces"]
    }


class _CapturedRows:
    def all(self) -> list[object]:
        return []


class _CapturingRagSession:
    def __init__(self):
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return _CapturedRows()


@pytest.mark.parametrize("actor", ["user_b", "admin"])
def test_rag_search_always_combines_document_ids_with_actor_owner_scope(
    authorization_matrix: AuthorizationMatrix,
    monkeypatch: pytest.MonkeyPatch,
    actor: str,
):
    fake_db = _CapturingRagSession()
    actor_id = authorization_matrix.ids[actor]
    service = RagService(fake_db, user_id=actor_id)  # type: ignore[arg-type]
    service.embeddings.embed_query = lambda _query: (
        [0.0] * service.embeddings.dimensions
    )

    def run_uncached(_key, loader, **_kwargs):
        return SimpleNamespace(value=loader())

    monkeypatch.setattr(
        rag_service_module.cache,
        "get_or_set_json",
        run_uncached,
    )

    assert (
        service.search(
            query="try to retrieve A private RAG",
            document_ids=[authorization_matrix.ids["document"]],
        )
        == []
    )
    assert fake_db.statement is not None

    compiled = fake_db.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    parameter_values = list(compiled.params.values())
    assert "knowledge_documents.user_id" in sql
    assert actor_id in parameter_values
    assert [authorization_matrix.ids["document"]] in parameter_values


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["user_b", "admin"])
@pytest.mark.parametrize("operation", ["search", "read", "update", "delete", "run"])
async def test_langgraph_thread_operations_always_apply_actor_owner_scope(
    authorization_matrix: AuthorizationMatrix,
    isolated_langgraph_auth,
    operation: str,
    actor: str,
):
    payload = {
        "operation": operation,
        "thread_id": authorization_matrix.ids["thread"],
        "metadata": {"owner": authorization_matrix.ids["user_a"]},
    }
    context = SimpleNamespace(
        user=SimpleNamespace(identity=authorization_matrix.ids[actor])
    )

    owner_filter = await isolated_langgraph_auth.scope_threads(context, payload)

    assert owner_filter == {"owner": authorization_matrix.ids[actor]}
    assert payload["metadata"]["owner"] == authorization_matrix.ids[actor]


@pytest.mark.asyncio
async def test_langgraph_thread_create_and_store_namespace_reject_owner_spoofing(
    authorization_matrix: AuthorizationMatrix,
    isolated_langgraph_auth,
):
    owner_context = SimpleNamespace(
        user=SimpleNamespace(identity=authorization_matrix.ids["user_a"])
    )
    owner_payload: dict[str, object] = {}
    owner_filter = await isolated_langgraph_auth.create_thread(
        owner_context, owner_payload
    )

    attacker_context = SimpleNamespace(
        user=SimpleNamespace(identity=authorization_matrix.ids["user_b"])
    )

    create_payload = {
        "metadata": {"owner": authorization_matrix.ids["user_a"]},
    }
    attacker_filter = await isolated_langgraph_auth.create_thread(
        attacker_context, create_payload
    )
    store_payload = {
        "namespace": (
            authorization_matrix.ids["user_a"],
            "private-memory",
        )
    }
    await isolated_langgraph_auth.scope_store(attacker_context, store_payload)

    assert owner_filter == {"owner": authorization_matrix.ids["user_a"]}
    assert owner_payload["metadata"]["owner"] == authorization_matrix.ids["user_a"]
    assert attacker_filter == {"owner": authorization_matrix.ids["user_b"]}
    assert create_payload["metadata"]["owner"] == authorization_matrix.ids["user_b"]
    assert store_payload["namespace"] == (
        authorization_matrix.ids["user_b"],
        authorization_matrix.ids["user_a"],
        "private-memory",
    )


def test_long_term_memory_is_isolated_across_users_and_threads():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with testing_session() as db:
            db.add_all(
                [
                    UserMemory(
                        user_id="user-a",
                        memory_key="profile.name",
                        memory_value="Alice",
                        source_thread_id="thread-a-1",
                    ),
                    UserMemory(
                        user_id="user-b",
                        memory_key="profile.name",
                        memory_value="Bob",
                        source_thread_id="thread-b-1",
                    ),
                ]
            )
            db.commit()

            assert user_memory_map(db, "user-b") == {"profile.name": "Bob"}
            remember_from_messages(
                db,
                "user-b",
                [{"role": "user", "content": "忘记我的名字"}],
                source_thread_id="thread-b-2",
            )

            assert user_memory_map(db, "user-b") == {}
            assert user_memory_map(db, "user-a") == {"profile.name": "Alice"}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
