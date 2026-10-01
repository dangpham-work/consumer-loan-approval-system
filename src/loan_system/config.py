from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    """Cấu hình đọc từ biến môi trường hoặc file .env (xem .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Cách 1: một chuỗi kết nối đầy đủ. Cách 2 (khi để trống): dựng từ các thành phần DB_*,
    # để mật khẩu chứa ký tự đặc biệt (@ # / :) không phải mã hóa URL thủ công.
    database_url: str = ""
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "loan_system"
    db_user: str = "loan_app"
    db_password: str = ""
    # Tài khoản quản trị chỉ dùng cho create_database và migration (ADR 0004): tạo database, tạo
    # tài khoản ứng dụng và cấp quyền theo từng bảng. Để trống cả hai cách thì dùng luôn tài khoản
    # ứng dụng (một tài khoản, không tách đặc quyền).
    database_admin_url: str = ""
    db_admin_user: str = ""
    db_admin_password: str = ""
    # Máy được phép kết nối bằng tài khoản ứng dụng ('%' = mọi máy, 'localhost' = chỉ máy CSDL).
    db_app_host: str = "%"

    # Bốn khóa bí mật tách biệt (mục 4.2.5 đề cương). Giá trị mặc định chỉ dùng cho môi trường dev.
    session_secret: str = "dev-only-session-secret-change-me"
    data_enc_key: str = "dev-only-data-enc-key-change-me"
    hmac_integrity_key: str = "dev-only-hmac-integrity-key-change-me"
    blind_index_key: str = "dev-only-blind-index-key-change-me"
    # Xoay khóa toàn vẹn (4.2.5): tăng phiên bản, chuyển khóa cũ vào danh sách khóa cũ (JSON, ví dụ
    # {"1": "..."}) để vẫn kiểm tra được snapshot của hồ sơ vay đã duyệt bằng khóa cũ.
    hmac_integrity_key_version: int = 1
    hmac_integrity_old_keys: dict[int, str] = {}

    # Chỉ cho môi trường dev: ghi SMS (mã OTP) và email (mật khẩu tạm) giả lập ra log máy chủ.
    dev_echo_messages: bool = False

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

    # SR09: số lần xem PII đầy đủ (VIEW_PII) mỗi người trong một cửa sổ, vượt thì cảnh báo CRITICAL
    # cho Kiểm soát viên thay vì chặn (nhân viên vẫn cần xem để làm việc).
    pii_view_alert_threshold: int = 20
    pii_view_alert_window_minutes: int = 60

    # Giấy tờ lưu ngoài thư mục web (UC13 bước 4).
    document_storage_dir: Path = Path("var/documents")
    # Thư mục chứa file mô hình chấm điểm; checksum từng file đăng ký trong bảng scoring_models.
    scoring_model_dir: Path = Path(__file__).parent / "scoring_models"
    cic_timeouts_seconds: tuple[float, ...] = (5, 10, 20)  # UC19 2a: 3 lần, chờ tăng dần
    cic_reuse_days: int = 30  # UC19 1a

    def sqlalchemy_url(self) -> URL:
        """Kết nối của ứng dụng lúc chạy: tài khoản quyền tối thiểu."""
        if self.database_url:
            return make_url(self.database_url)
        return self._component_url(self.db_user, self.db_password)

    def admin_url(self) -> URL:
        """Kết nối của create_database và migration; cùng database với ứng dụng."""
        if self.database_admin_url:
            return make_url(self.database_admin_url).set(database=self.sqlalchemy_url().database)
        if self.db_admin_user:
            return self._component_url(self.db_admin_user, self.db_admin_password).set(
                database=self.sqlalchemy_url().database
            )
        return self.sqlalchemy_url()

    def _component_url(self, user: str, password: str) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=user,
            password=password or None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )
