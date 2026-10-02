# consumer-loan-approval-system

Hệ thống quản lý và xét duyệt vay tín dụng tiêu dùng, áp dụng OOAD và nguyên lý Security by Design: phân quyền RBAC, tách biệt nhiệm vụ (SoD), mã hóa dữ liệu cá nhân AES-GCM, nhật ký kiểm toán dạng chuỗi băm (hash-chain).

Công nghệ: Python 3.12, FastAPI, SQLAlchemy và Alembic, MySQL 8.0.16 trở lên (ADR 0004), giao diện Jinja2. Thuật ngữ nghiệp vụ xem [CONTEXT.md](CONTEXT.md).

## 1. Yêu cầu

- Python 3.12 và [uv](https://docs.astral.sh/uv/)
- MySQL 8.0.16 trở lên (hoặc Docker, xem mục 6)

## 2. Cài đặt nhanh

```bash
uv sync
cp .env.example .env
```

Mở `.env` và điền:

| Biến | Ý nghĩa |
|---|---|
| `SESSION_SECRET`, `DATA_ENC_KEY`, `HMAC_INTEGRITY_KEY`, `BLIND_INDEX_KEY` | Bốn khóa bí mật khác nhau, mỗi khóa tối thiểu 32 byte ngẫu nhiên |
| `DB_HOST`, `DB_PORT`, `DB_NAME` | Địa chỉ và tên database (mặc định `localhost`, `3306`, `loan_system`) |
| `DB_USER`, `DB_PASSWORD` | Tài khoản ứng dụng (quyền tối thiểu), do bước tạo database tự tạo |
| `DB_ADMIN_USER`, `DB_ADMIN_PASSWORD` | Tài khoản quản trị MySQL (thường là `root`), chỉ dùng khi tạo database |
| `DEV_ECHO_MESSAGES` | `true` để in SMS (OTP) và email (mật khẩu tạm) giả lập ra log máy chủ, chỉ dùng khi dev |

Sinh một khóa bí mật:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Không commit file `.env`.

## 3. Tạo database

Lệnh này tạo database, chạy migration, tạo tài khoản ứng dụng `DB_USER` và cấp quyền theo từng bảng. Hai bảng chỉ ghi thêm (`audit_logs`, `approval_decisions`) chỉ có quyền SELECT và INSERT.

Dùng PowerShell trên Windows:

```powershell
$env:DB_ADMIN_USER = "root"
$env:DB_ADMIN_PASSWORD = "<mật khẩu root>"
uv run python -m loan_system.create_database
```

Hoặc điền `DB_ADMIN_*` trong `.env` rồi chỉ cần chạy lệnh cuối. Chạy lại nhiều lần vẫn an toàn.

## 4. Chạy ứng dụng

```bash
uv run uvicorn loan_system.app:app --reload
```

- Giao diện web: <http://127.0.0.1:8000/app>
- Tài liệu API (Swagger): <http://127.0.0.1:8000/docs>

### Tạo Quản trị viên đầu tiên

```bash
uv run python -m loan_system.create_admin <username> <email> "<họ tên>"
```

Lệnh in mật khẩu tạm một lần. Lần đăng nhập đầu tiên phải đổi mật khẩu và đăng ký TOTP (ứng dụng xác thực như Google Authenticator). Sau đó Quản trị viên tạo các nhân viên khác trong trang quản trị.

## 5. Dữ liệu mẫu để chạy thử

Nạp sẵn nhân viên, khách hàng, hồ sơ ở nhiều trạng thái:

```bash
uv run python -m loan_system.seed_demo
```

Lệnh chỉ chạy trên database chưa có người dùng nào. Nó đi qua chính REST API nên dữ liệu mã hóa, chuỗi băm và chữ ký đều hợp lệ. Kết quả: 6 nhân viên, 6 khách hàng, 6 hồ sơ, 1 khoản vay.

Tài khoản và khóa TOTP được ghi vào `var/demo_accounts.txt` (file này bị git bỏ qua).

| Vai trò | Tên đăng nhập | Mật khẩu |
|---|---|---|
| Quản trị viên | `quantri` | `Demo@NhanVien2026` |
| Nhân viên tín dụng | `tindung1` | `Demo@NhanVien2026` |
| Thẩm định viên | `thamdinh1` | `Demo@NhanVien2026` |
| Quản lý phê duyệt | `pheduyet1` | `Demo@NhanVien2026` |
| Giải ngân | `giaingan1` | `Demo@NhanVien2026` |
| Kiểm soát viên | `kiemsoat1` | `Demo@NhanVien2026` |

Nhân viên đăng nhập bằng mật khẩu và mã TOTP 6 số. Nhập khóa TOTP trong `var/demo_accounts.txt` vào ứng dụng xác thực để lấy mã.

Khách hàng đăng nhập bằng số điện thoại, mật khẩu `Demo@KhachHang2026`:

| Số điện thoại | Trạng thái hồ sơ |
|---|---|
| 0901000001 | Đã giải ngân, đã trả kỳ 1 |
| 0901000002 | Đã nộp, chờ xác nhận hợp lệ |
| 0901000003 | Đang thẩm định |
| 0901000004 | Đã được phê duyệt, chờ giải ngân |
| 0901000005 | Bị hệ thống chấm điểm từ chối |
| 0901000006 | Bản nháp, chưa nộp |

Mật khẩu demo chỉ dành cho máy dev. Không dùng khi triển khai thật.

## 6. Chạy bằng Docker

```bash
docker compose up --build
```

Trong `.env` cần có thêm `MYSQL_ROOT_PASSWORD` và `DB_PASSWORD`, cùng bốn khóa bí mật. Ứng dụng nghe ở `127.0.0.1:8000`. MySQL không mở cổng ra ngoài, chỉ ứng dụng truy cập qua mạng nội bộ.

## 7. Tác vụ hằng đêm

Xử lý quá hạn, nhắc nợ, BR11 và chấm điểm lại. Cho bộ lập lịch (cron, Task Scheduler) gọi lúc 00:30. Chạy lại trong ngày không cộng dồn.

```bash
uv run python -m loan_system.run_nightly_job
```

## 8. Kiểm thử

```bash
uv run pytest                 # toàn bộ, cần MySQL thật
uv run pytest tests/domain    # chỉ tầng miền, không cần database
uv run mypy src tests         # kiểm tra kiểu (strict)
```

Test API (`tests/api`) dùng MySQL thật, mặc định `mysql+pymysql://root@localhost:3306`. Đổi bằng biến môi trường `LOAN_TEST_MYSQL_URL`, ví dụ `mysql+pymysql://root:matkhau@localhost:3306`. Tài khoản này cần toàn quyền (kèm GRANT OPTION) trên `loan_test_%` và quyền `CREATE USER`. Mỗi phiên test tự tạo và xóa database `loan_test_*`.

## 9. Cấu trúc thư mục

```
src/loan_system/
  api/            REST API (400/401/403/404/409/429 theo đề cương)
  web/            Giao diện HTML dưới /app
  services/       Nghiệp vụ, tự commit và ghi nhật ký kiểm toán
  domain/         Quy tắc nghiệp vụ thuần, không phụ thuộc database
  repositories/   Truy cập dữ liệu
  security/       Mã hóa, băm, TOTP, giới hạn tần suất
  adapters/       SMS, email, CIC, cổng thanh toán (có bản giả lập)
  scoring_models/ Mô hình chấm điểm
migrations/       Alembic
tests/            api (qua HTTP) và domain
docs/adr/         Các quyết định kiến trúc
```

## 10. Lưu ý

- SMS, email, CIC và cổng thanh toán hiện đều là bản giả lập. Với CIC giả lập, kịch bản kết quả phụ thuộc chữ số cuối của số CCCD.
- Tiền là `Decimal` (đồng), làm tròn nửa lên, không dùng float.
- Trên Windows, script CLI chỉ in ký tự ASCII vì console dùng cp1258.
- Nếu editor tự định dạng khi lưu, hãy kiểm tra lại các file Python sau khi lưu để chắc chắn không bị hỏng.

## Giấy phép

Xem [LICENSE](LICENSE).
