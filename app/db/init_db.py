from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import engine


MIGRATION_LOCK_ID = 202607190001


def init_db() -> None:
    """Apply pending Alembic migrations for the configured database."""

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": MIGRATION_LOCK_ID},
            )
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        return

    command.upgrade(config, "head")


if __name__ == "__main__":
    init_db()
