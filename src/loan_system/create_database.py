"""Tạo database trong DATABASE_URL nếu chưa có (collation tiếng Việt), rồi chạy migration.

Chạy: `uv run python -m loan_system.create_database`
"""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from loan_system.config import Settings


def main() -> None:
    url = Settings().sqlalchemy_url()
    name = url.database
    if not name or not name.replace("_", "").isalnum():
        raise SystemExit(f"Tên database không hợp lệ: {name!r}")
    master = create_engine(url.set(database="master"), isolation_level="AUTOCOMMIT")
    with master.connect() as conn:
        exists = conn.execute(text("SELECT DB_ID(:name)"), {"name": name}).scalar()
        if exists is None:
            conn.execute(text(f"CREATE DATABASE [{name}] COLLATE Vietnamese_100_CI_AS"))
            print(f"Created database {name}")
    master.dispose()
    command.upgrade(Config("alembic.ini"), "head")


if __name__ == "__main__":
    main()
