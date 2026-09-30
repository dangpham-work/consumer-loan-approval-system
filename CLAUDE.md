# consumer-loan-approval-system

Đồ án OOAD + ATBMHTTT: hệ thống quản lý và xét duyệt vay tín dụng tiêu dùng. Python 3.12, FastAPI, SQLAlchemy/Alembic, SQL Server (ADR 0003). Thuật ngữ theo `CONTEXT.md`.

## Lệnh

- Cài đặt: `uv sync`
- Test toàn bộ: `uv run pytest`
- Chỉ tầng miền (không cần CSDL): `uv run pytest tests/domain`
- Kiểm tra kiểu: `uv run mypy src tests` (strict)
- Tạo database + migration: `uv run python -m loan_system.create_database` (đọc `DATABASE_URL`, xem `.env.example`)
- Chạy ứng dụng: `uv run uvicorn loan_system.app:app --reload`
- Tạo Quản trị viên đầu tiên: `uv run python -m loan_system.create_admin <username> <email> "<họ tên>"` (in mật khẩu tạm; lần đầu đăng nhập phải đổi mật khẩu và đăng ký TOTP)
- Tác vụ hằng đêm (quá hạn, nhắc nợ, BR11, chấm lại): `uv run python -m loan_system.run_nightly_job` (bộ lập lịch gọi lúc 00:30; chạy lại không cộng dồn)

Test API (`tests/api`) cần một SQL Server thật: mặc định `localhost\MSSQLSERVER02` qua Windows Authentication, ODBC Driver 17. Đổi bằng biến môi trường `LOAN_TEST_SQLSERVER` và `LOAN_TEST_ODBC_DRIVER`. Mỗi phiên test tự tạo và xóa database `loan_test_*`.

## Quy ước

- Hai seam kiểm thử: REST API (`tests/api`, qua TestClient) và giao diện công khai của tầng miền (`tests/domain`). Không kiểm tra qua truy vấn thẳng CSDL; chỉ giả lập hệ thống ngoài (SMS, CIC, cổng thanh toán) và đồng hồ.
- Tiền là `Decimal` (đồng), làm tròn nửa lên; không dùng float.
- Tầng nghiệp vụ tự `commit`; mọi thao tác quan trọng ghi `AuditService.log` trong cùng giao dịch.
- Lỗi API theo mục 4.2.4 đề cương (400/401/403/404/409/429), không lộ chi tiết kỹ thuật.
- Không in chuỗi tiếng Việt ra console trong script CLI (console Windows dùng cp1258).

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues on this repo, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
