from alembic import context
from sqlalchemy import Connection, create_engine

from loan_system.config import Settings
from loan_system.repositories.models import Base

target_metadata = Base.metadata


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


# Test harness truyền sẵn kết nối; khi chạy lệnh `alembic` thì đọc cấu hình CSDL.
existing = context.config.attributes.get("connection")
if existing is not None:
    run(existing)
else:
    with create_engine(Settings().sqlalchemy_url()).connect() as connection:
        run(connection)
