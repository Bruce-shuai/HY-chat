from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import get_settings

settings = get_settings()


def _database_engine_options(database_url: str) -> dict[str, object]:
    options: dict[str, object] = {"pool_pre_ping": True}
    if make_url(database_url).get_backend_name() != "postgresql":
        return options

    options.update(
        {
            "pool_timeout": settings.database_pool_timeout_seconds,
            "connect_args": {
                "connect_timeout": settings.database_connect_timeout_seconds,
                "options": (
                    f"-c statement_timeout={settings.database_statement_timeout_ms}"
                ),
                "tcp_user_timeout": settings.database_tcp_user_timeout_ms,
            },
        }
    )
    return options


# 数据库连接的“发动机”或者“连接入口”
engine = create_engine(
    settings.database_url,
    **_database_engine_options(settings.database_url),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
