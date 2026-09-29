from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: URL) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Một phiên CSDL cho mỗi yêu cầu HTTP.

    Tầng nghiệp vụ tự commit khi thao tác thành công; phần chưa commit bị hoàn tác khi đóng phiên.
    """
    with factory() as session:
        yield session
