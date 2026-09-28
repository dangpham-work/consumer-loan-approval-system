from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    """Cấu hình đọc từ biến môi trường hoặc file .env (xem .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Cách 1: một chuỗi kết nối đầy đủ. Cách 2 (khi để trống): dựng từ các thành phần DB_*,
    # để mật khẩu chứa ký tự đặc biệt (@ # / :) không phải mã hóa URL thủ công.
    database_url: str = ""
    db_host: str = "localhost\\MSSQLSERVER02"
    db_name: str = "loan_system"
    db_user: str = ""  # để trống = Windows Authentication
    db_password: str = ""
    odbc_driver: str = "ODBC Driver 17 for SQL Server"
    db_trust_server_certificate: bool = True

    # Bốn khóa bí mật tách biệt (mục 4.2.5 đề cương). Giá trị mặc định chỉ dùng cho môi trường dev.
    session_secret: str = "dev-only-session-secret-change-me"
    data_enc_key: str = "dev-only-data-enc-key-change-me"
    hmac_integrity_key: str = "dev-only-hmac-integrity-key-change-me"
    blind_index_key: str = "dev-only-blind-index-key-change-me"

    session_idle_minutes: int = 15  # SR11
    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 3  # UC09 4a, UC02 3b
    terms_version: str = "2026.1"
    data_processing_terms_version: str = "2026.1"  # điều khoản xử lý dữ liệu cá nhân (SR14)

    login_max_failures: int = 5  # SR01, UC01 3c
    lockout_minutes: int = 15
    # SR12: số lượt tối đa trong một cửa sổ thời gian
    rate_window_seconds: int = 60
    login_rate_limit: int = 10  # mỗi địa chỉ IP
    otp_rate_limit: int = 10  # mỗi địa chỉ IP
    application_write_rate_limit: int = 30  # nộp hồ sơ vay, tải giấy tờ: mỗi người dùng

    # Giấy tờ lưu ngoài thư mục web (UC13 bước 4).
    document_storage_dir: Path = Path("var/documents")

    def sqlalchemy_url(self) -> URL:
        if self.database_url:
            return make_url(self.database_url)
        query = {
            "driver": self.odbc_driver,
            "Encrypt": "yes",
            "TrustServerCertificate": "yes" if self.db_trust_server_certificate else "no",
        }
        if not self.db_user:
            query["trusted_connection"] = "yes"
        return URL.create(
            "mssql+pyodbc",
            username=self.db_user or None,
            password=self.db_password or None,
            host=self.db_host,
            database=self.db_name,
            query=query,
        )
