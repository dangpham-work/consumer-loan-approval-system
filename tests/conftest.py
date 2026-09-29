"""Test harness cho Seam 1: REST API chạy trên SQL Server thật.

Mỗi phiên test tạo một database tạm `loan_test_<hex>` trên instance cấu hình bởi biến môi trường
LOAN_TEST_SQLSERVER (mặc định `localhost\\MSSQLSERVER02`, Windows Authentication), chạy migration,
và xóa database khi kết thúc. Mỗi test bắt đầu với dữ liệu trống.
"""

import os
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.payment import FakePaymentGateway
from loan_system.adapters.sms import FakeSmsGateway
from loan_system.config import Settings
from loan_system.main import create_app

SERVER = os.environ.get("LOAN_TEST_SQLSERVER", r"localhost\MSSQLSERVER02")
ODBC_DRIVER = os.environ.get("LOAN_TEST_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
# Xóa theo thứ tự khóa ngoại.
# Không xóa roles, permissions, role_permissions: dữ liệu gốc do migration tạo sẵn theo ma trận RBAC.
TABLES = [
    "sessions",
    "audit_logs",
    "notifications",
    "otp_challenges",
    "application_status_history",
    "payment_reminders",
    "payment_allocations",
    "payments",
    "loan_contracts",
    "installments",
    "disbursements",
    "loans",
    "approval_decisions",
    "appraisal_reports",
    "credit_scores",
    "cic_reports",
    "user_roles",
    "application_documents",
    "loan_applications",
    "users",
    "customers",
    "employees",
    "registration_requests",
]


def server_url(database: str) -> URL:
    return URL.create(
        "mssql+pyodbc",
        host=SERVER,
        database=database,
        query={
            "driver": ODBC_DRIVER,
            "trusted_connection": "yes",
            "Encrypt": "yes",
            "TrustServerCertificate": "yes",
        },
    )


@pytest.fixture(scope="session")
def database_url() -> Iterator[URL]:
    name = f"loan_test_{uuid.uuid4().hex[:12]}"
    master = create_engine(server_url("master"), isolation_level="AUTOCOMMIT")
    with master.connect() as conn:
        conn.execute(text(f"CREATE DATABASE [{name}] COLLATE Vietnamese_100_CI_AS"))
    url = server_url(name)
    try:
        engine = create_engine(url)
        with engine.begin() as conn:
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        engine.dispose()
        yield url
    finally:
        with master.connect() as conn:
            conn.execute(text(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"))
            conn.execute(text(f"DROP DATABASE [{name}]"))
        master.dispose()


@pytest.fixture(scope="session")
def engine(database_url: URL) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 9, 28, 9, 0, tzinfo=UTC))


@pytest.fixture
def sms() -> FakeSmsGateway:
    return FakeSmsGateway()


@pytest.fixture
def email() -> FakeEmailGateway:
    return FakeEmailGateway()


@pytest.fixture
def cic() -> FakeCicGateway:
    return FakeCicGateway()


@pytest.fixture
def payments() -> FakePaymentGateway:
    return FakePaymentGateway()


@pytest.fixture
def scoring_model_dir(tmp_path: Path) -> Path:
    """Bản sao thư mục mô hình chấm điểm cho từng test, để ST09 thay được file mô hình."""
    target = tmp_path / "scoring_models"
    shutil.copytree(Settings.model_fields["scoring_model_dir"].default, target)
    return target


@pytest.fixture
def client(
    database_url: URL,
    engine: Engine,
    clock: FakeClock,
    sms: FakeSmsGateway,
    email: FakeEmailGateway,
    cic: FakeCicGateway,
    payments: FakePaymentGateway,
    scoring_model_dir: Path,
    tmp_path: Path,
) -> Iterator[TestClient]:
    with engine.begin() as conn:
        for table in TABLES:
            conn.execute(text(f"DELETE FROM {table}"))
    settings = Settings(
        database_url=database_url.render_as_string(hide_password=False),
        document_storage_dir=tmp_path / "documents",
        scoring_model_dir=scoring_model_dir,
    )
    app = create_app(settings, clock=clock, sms=sms, email=email, cic=cic, payments=payments)
    # https để cookie Secure (SR11) được gửi lại như trên trình duyệt thật.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
