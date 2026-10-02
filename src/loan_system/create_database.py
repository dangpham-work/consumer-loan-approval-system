"""Tạo database nếu chưa có, chạy migration, rồi tạo tài khoản ứng dụng và cấp quyền theo bảng.

Chạy bằng tài khoản quản trị (DATABASE_ADMIN_URL hoặc DB_ADMIN_USER, xem .env.example):
`uv run python -m loan_system.create_database`
"""

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text

from loan_system.config import Settings
from loan_system.repositories.models import (
    APPEND_ONLY_TABLES,
    DATABASE_CHARSET,
    DATABASE_COLLATION,
    Base,
)


def _identifier(value: str | None, kind: str) -> str:
    """Tên database, tên tài khoản được ghép thẳng vào câu lệnh DDL nên chỉ nhận chữ, số và _."""
    if not value or not value.replace("_", "").isalnum():
        raise SystemExit(f"Invalid {kind}: {value!r}")
    return value


def create_schema(conn: Connection, database: str) -> None:
    conn.execute(
        text(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            f"CHARACTER SET {DATABASE_CHARSET} COLLATE {DATABASE_COLLATION}"
        )
    )


def grant_app_privileges(conn: Connection, database: str, user: str, host: str) -> None:
    """Đặc quyền tối thiểu của tài khoản ứng dụng (4.1.2e): không có quyền DDL, và trên các bảng
    chỉ ghi thêm (nhật ký kiểm toán, quyết định phê duyệt) chỉ có SELECT, INSERT."""
    for table in Base.metadata.tables:
        rights = "SELECT, INSERT"
        if table not in APPEND_ONLY_TABLES:
            rights += ", UPDATE, DELETE"
        conn.execute(
            text(f"GRANT {rights} ON `{database}`.`{table}` TO :user@:host"),
            {"user": user, "host": host},
        )


def main() -> None:
    settings = Settings()
    app_url, admin_url = settings.sqlalchemy_url(), settings.admin_url()
    database = _identifier(app_url.database, "database name")

    # URL.set() bỏ qua giá trị None, nên phải dùng _replace để kết nối khi database chưa tồn tại.
    server = create_engine(admin_url._replace(database=None), isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        create_schema(conn, database)
    command.upgrade(Config("alembic.ini"), "head")

    if app_url.username == admin_url.username:
        print("No separate admin account configured: application runs with the admin account")
    else:
        user = _identifier(app_url.username, "application user")
        account = {"user": user, "host": settings.db_app_host, "password": app_url.password or ""}
        with server.connect() as conn:
            conn.execute(
                text("CREATE USER IF NOT EXISTS :user@:host IDENTIFIED BY :password"), account
            )
            conn.execute(text("ALTER USER :user@:host IDENTIFIED BY :password"), account)
            grant_app_privileges(conn, database, user, settings.db_app_host)
        print(f"Granted table privileges on {database} to {user}")
    server.dispose()


if __name__ == "__main__":
    main()
