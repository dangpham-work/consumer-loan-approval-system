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
    otp_max_attempts: int = 3  # UC09 4a
    terms_version: str = "2026.1"

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
