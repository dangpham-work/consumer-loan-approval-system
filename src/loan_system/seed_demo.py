"""Nạp dữ liệu mẫu để demo: nhân viên đủ vai trò, khách hàng và hồ sơ vay ở nhiều trạng thái.

Chạy sau `create_database`: `uv run python -m loan_system.seed_demo`
Dữ liệu đi qua chính REST API (trong tiến trình, qua TestClient) nên PII được mã hóa, nhật ký kiểm
toán và chữ ký HMAC đúng như dữ liệu thật. SMS, email, CIC và cổng thanh toán là bản giả lập.
Tài khoản và khóa TOTP được ghi vào var/demo_accounts.txt (không commit). Chỉ chạy được trên
database trống. Cần nhóm phụ thuộc dev (`uv sync` mặc định đã cài httpx).
"""

import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from loan_system.adapters.email import FakeEmailGateway
from loan_system.adapters.sms import FakeSmsGateway
from loan_system.config import Settings
from loan_system.main import create_app
from loan_system.security.totp import totp_code
from loan_system.services.staff_service import create_first_admin

STAFF_PASSWORD = "Demo@NhanVien2026"
CUSTOMER_PASSWORD = "Demo@KhachHang2026"
OUTPUT = Path("var/demo_accounts.txt")

JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 2048
PNG = b"\x89PNG\r\n\x1a\n" + b"\x02" * 2048
PDF = b"%PDF-1.7\n" + b"\x03" * 2048
DOCUMENTS = {
    "ID_FRONT": ("cccd-truoc.jpg", JPEG),
    "ID_BACK": ("cccd-sau.png", PNG),
    "INCOME_PROOF": ("sao-ke-luong.pdf", PDF),
    "UTILITY_BILL": ("hoa-don-dien.pdf", PDF + b"\x04"),
}


@dataclass
class Clock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


@dataclass
class Account:
    label: str
    username: str
    password: str
    totp_secret: str | None
    client: TestClient


@dataclass(frozen=True)
class Customer:
    full_name: str
    phone: str
    email: str
    birth: str
    # Chữ số cuối CCCD chọn kịch bản CIC giả lập: 1 = nợ nhóm 1, 7 = nhóm 2, 8 = nhóm 3, 6 = chưa có lịch sử.
    national_id: str
    occupation: str
    employer: str
    income: int
    debt: int
    amount: int
    term: int
    purpose: str


CUSTOMERS = [
    Customer("Nguyễn Văn An", "0901000001", "an.nguyen@example.com", "1995-04-12", "079095000011",
             "Kỹ sư phần mềm", "Công ty ABC", 25_000_000, 2_000_000, 30_000_000, 12, "CONSUMER_GOODS"),
    Customer("Trần Thị Bình", "0901000002", "binh.tran@example.com", "1992-09-03", "079092000021",
             "Kế toán", "Công ty Minh Phát", 18_000_000, 1_000_000, 20_000_000, 12, "CONSUMER_GOODS"),
    Customer("Lê Hoàng Chi", "0901000003", "chi.le@example.com", "1990-01-25", "079090000031",
             "Giáo viên", "Trường THPT Lê Quý Đôn", 15_000_000, 0, 15_000_000, 6, "CONSUMER_GOODS"),
    Customer("Phạm Quốc Dũng", "0901000004", "dung.pham@example.com", "1988-11-30", "079088000047",
             "Quản lý cửa hàng", "Siêu thị Bách Hóa", 22_000_000, 3_000_000, 25_000_000, 12, "CONSUMER_GOODS"),
    Customer("Võ Thanh Em", "0901000005", "em.vo@example.com", "1998-06-18", "079098000058",
             "Nhân viên bán hàng", "Cửa hàng Di Động Việt", 9_000_000, 4_000_000, 30_000_000, 12, "CONSUMER_GOODS"),
    Customer("Đặng Mai Phương", "0901000006", "phuong.dang@example.com", "1996-02-09", "079096000061",
             "Thiết kế đồ họa", "Studio Hoa Sen", 20_000_000, 1_500_000, 18_000_000, 9, "CONSUMER_GOODS"),
]


class Seeder:
    def __init__(self) -> None:
        self.clock = Clock(datetime.now(UTC) - timedelta(days=2))
        self.sms = FakeSmsGateway()
        self.email = FakeEmailGateway()
        app = create_app(Settings(), clock=self.clock, sms=self.sms, email=self.email)
        self.app = app
        self.http = TestClient(app, base_url="https://testserver")
        self.http.__enter__()
        self.accounts: list[Account] = []

    def browser(self) -> TestClient:
        return TestClient(self.app, base_url="https://testserver")

    def otp(self, secret: str) -> str:
        self.clock.advance(seconds=30)  # mỗi mã TOTP chỉ dùng được một lần
        return totp_code(secret, self.clock.now())

    def first_login(self, username: str, temp_password: str, label: str) -> Account:
        client = self.browser()
        client.post("/auth/login", json={"username": username, "password": temp_password}).raise_for_status()
        client.post(
            "/auth/setup/password",
            json={"current_password": temp_password, "new_password": STAFF_PASSWORD},
        ).raise_for_status()
        secret: str = client.post("/auth/setup/totp").json()["secret"]
        client.post("/auth/setup/totp/confirm", json={"code": self.otp(secret)}).raise_for_status()
        account = Account(label, username, STAFF_PASSWORD, secret, client)
        self.accounts.append(account)
        return account

    def create_admin(self) -> Account:
        ctx = self.app.state.ctx
        with ctx.session_factory() as db:
            temp = create_first_admin(
                db, ctx.clock, username="quantri", full_name="Quản Trị Viên", email="quantri@cty.vn"
            )
        return self.first_login("quantri", temp, "Quan tri vien (ADMIN)")

    def hire(self, admin: Account, username: str, full_name: str, role: str, label: str) -> Account:
        assert admin.totp_secret
        created = admin.client.post(
            "/admin/users",
            json={
                "username": username,
                "full_name": full_name,
                "email": f"{username}@cty.vn",
                "branch": "Hà Nội",
                "roles": [role],
                "otp": self.otp(admin.totp_secret),
            },
        )
        created.raise_for_status()
        match = re.search(r"Mật khẩu tạm: (\S+)", self.email.last_to(f"{username}@cty.vn").body)
        assert match, "email phải chứa mật khẩu tạm"
        return self.first_login(username, match.group(1), label)

    def register(self, c: Customer) -> TestClient:
        started = self.http.post(
            "/customers/register",
            json={
                "full_name": c.full_name, "date_of_birth": c.birth, "phone": c.phone,
                "email": c.email, "password": CUSTOMER_PASSWORD, "accept_terms": True,
            },
        )
        started.raise_for_status()
        code = re.search(r"\b(\d{6})\b", self.sms.last_to(c.phone).message)
        assert code, "SMS phải chứa mã OTP"
        self.http.post(
            "/customers/register/verify",
            json={"registration_id": started.json()["registration_id"], "otp": code.group(1)},
        ).raise_for_status()
        browser = self.browser()
        browser.post("/auth/login", json={"username": c.phone, "password": CUSTOMER_PASSWORD}).raise_for_status()
        return browser

    def draft(self, browser: TestClient, c: Customer) -> str:
        created = browser.post(
            "/applications",
            json={"requested_amount": c.amount, "term_months": c.term, "purpose": c.purpose},
        )
        created.raise_for_status()
        app_id: str = created.json()["id"]
        finances: dict[str, Any] = {
            "national_id": c.national_id, "occupation": c.occupation, "employer": c.employer,
            "employment_years": 4, "monthly_income": c.income, "existing_monthly_debt": c.debt,
            "housing_type": "RENT", "address": "12 Lê Lợi, Quận 1, TP.HCM",
            "receiving_account": "0123456789",
        }
        browser.patch(f"/applications/{app_id}", json=finances).raise_for_status()
        for doc_type, (filename, content) in DOCUMENTS.items():
            browser.post(
                f"/applications/{app_id}/documents",
                data={"doc_type": doc_type},
                files={"file": (filename, content, "application/octet-stream")},
            ).raise_for_status()
        return app_id

    def submit(self, browser: TestClient, app_id: str) -> None:
        browser.post(
            f"/applications/{app_id}/submit", json={"accept_data_processing": True}
        ).raise_for_status()

    def verify(self, officer: Account, app_id: str) -> None:
        client = officer.client
        client.post(f"/applications/{app_id}/claim").raise_for_status()
        for doc in client.get(f"/applications/{app_id}").json()["documents"]:
            client.put(
                f"/applications/{app_id}/documents/{doc['id']}/review", json={"verdict": "PASS"}
            ).raise_for_status()
        client.post(f"/applications/{app_id}/verify").raise_for_status()

    def appraise(self, appraiser: Account, app_id: str, amount: int, term: int) -> None:
        client = appraiser.client
        client.post(f"/applications/{app_id}/appraisal/open").raise_for_status()
        client.post(
            f"/applications/{app_id}/appraisal",
            json={
                "recommendation": "APPROVE", "proposed_amount": amount, "proposed_term": term,
                "fraud_suspected": False,
                "comment": "Thu nhập ổn định, lịch sử tín dụng chấp nhận được, đề xuất duyệt.",
            },
        ).raise_for_status()

    def decide(self, approver: Account, app_id: str, action: str, **body: Any) -> None:
        client = approver.client
        version = client.get(f"/applications/{app_id}/approval").json()["version"]
        client.post(f"/applications/{app_id}/{action}", json={"version": version, **body}).raise_for_status()

    def disburse(self, disburser: Account, app_id: str) -> str:
        assert disburser.totp_secret
        response = disburser.client.post(
            f"/applications/{app_id}/disburse", json={"otp": self.otp(disburser.totp_secret)}
        )
        response.raise_for_status()
        loan_id: str = response.json()["loan"]["id"]
        return loan_id


def ensure_empty(seeder: Seeder) -> None:
    ctx = seeder.app.state.ctx
    with ctx.session_factory() as db:
        count = db.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
    if count:
        raise SystemExit("Database already has users; seed_demo only runs on an empty database")


def main() -> None:
    seeder = Seeder()
    ensure_empty(seeder)
    admin = seeder.create_admin()
    officer = seeder.hire(admin, "tindung1", "Nguyễn Thị Hoa", "CREDIT_OFFICER", "NV tin dung (CREDIT_OFFICER)")
    appraiser = seeder.hire(admin, "thamdinh1", "Trần Minh Khoa", "APPRAISER", "Tham dinh (APPRAISER)")
    approver = seeder.hire(admin, "pheduyet1", "Lê Quốc Bảo", "APPROVER", "Quan ly phe duyet (APPROVER)")
    disburser = seeder.hire(admin, "giaingan1", "Phạm Thu Hà", "DISBURSER", "Giai ngan (DISBURSER)")
    seeder.hire(admin, "kiemsoat1", "Hoàng Văn Tùng", "AUDITOR", "Kiem soat vien (AUDITOR)")

    customer_accounts: list[tuple[str, str]] = []
    states = [
        "da giai ngan, da tra ky 1",
        "da nop, cho xac nhan hop le",
        "dang tham dinh",
        "da duoc phe duyet, cho giai ngan",
        "bi he thong cham diem tu choi",
        "ban nhap, chua nop",
    ]
    for i, c in enumerate(CUSTOMERS):
        browser = seeder.register(c)
        customer_accounts.append((c.phone, states[i]))
        app_id = seeder.draft(browser, c)
        if i == 5:
            continue
        seeder.submit(browser, app_id)
        if i == 1:
            continue
        seeder.verify(officer, app_id)
        if i == 2:
            continue
        if i == 4:
            continue  # chấm điểm tín dụng tự từ chối ngay sau khi xác nhận hợp lệ
        seeder.appraise(appraiser, app_id, c.amount, c.term)
        seeder.decide(approver, app_id, "approve")
        if i == 3:
            continue
        loan_id = seeder.disburse(disburser, app_id)
        schedule = browser.get(f"/loans/{loan_id}/schedule").json()
        first = schedule["installments"][0]
        due = str(Decimal(first["principal_due"]) + Decimal(first["interest_due"]))
        browser.post(f"/loans/{loan_id}/payments", json={"amount": due}).raise_for_status()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["TAI KHOAN DEMO (khong commit file nay)", ""]
    lines.append(f"Nhan vien - mat khau: {STAFF_PASSWORD}")
    for a in seeder.accounts:
        lines.append(f"  {a.username:<12} {a.label:<32} TOTP secret: {a.totp_secret}")
    lines += ["", f"Khach hang - mat khau: {CUSTOMER_PASSWORD}"]
    lines += [f"  {phone}  ({state})" for phone, state in customer_accounts]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Seeded {len(seeder.accounts)} staff and {len(CUSTOMERS)} customers. Accounts: {OUTPUT}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
