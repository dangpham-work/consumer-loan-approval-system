from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: URL) -> Engine:
    # READ COMMITTED: sau khi chờ được khóa dòng, giao dịch đọc lại thấy dữ liệu giao dịch trước
    # vừa commit. Mặc định REPEATABLE READ của MySQL giữ ảnh chụp cũ nên kiểm tra sau khóa sẽ sai.
    return create_engine(database_url, pool_pre_ping=True, isolation_level="READ COMMITTED")


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Một phiên CSDL cho mỗi yêu cầu HTTP.

    Tầng nghiệp vụ tự commit khi thao tác thành công; phần chưa commit bị hoàn tác khi đóng phiên.
    """
    with factory() as session:
        yield session
