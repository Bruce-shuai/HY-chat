from sqlalchemy import text

from app.db.session import Base, engine
from app.db import models  # noqa: F401  ensure models are imported


def init_db() -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    # create_all 不会给已有表补列；这些轻量、幂等语句用于从早期 HY-chat 数据库平滑升级。
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)")
        )
        connection.execute(
            text(
                "ALTER TABLE image_generations ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_generations "
                "ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(36)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_generations "
                "ADD COLUMN IF NOT EXISTS stored_file_id VARCHAR(36)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_generations "
                "ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(36)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_generations "
                "ADD COLUMN IF NOT EXISTS provider VARCHAR(32) DEFAULT 'zhipu'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_generations "
                "ADD COLUMN IF NOT EXISTS mode VARCHAR(32) DEFAULT 'text_to_image'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_generations "
                "ADD COLUMN IF NOT EXISTS quality VARCHAR(32) DEFAULT 'auto'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE knowledge_documents "
                "ADD COLUMN IF NOT EXISTS stored_file_id VARCHAR(36)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE knowledge_documents "
                "DROP CONSTRAINT IF EXISTS knowledge_documents_sha256_key"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_user_sha256 "
                "ON knowledge_documents (user_id, sha256)"
            )
        )
