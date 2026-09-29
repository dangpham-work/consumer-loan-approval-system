"""Tạo Quản trị viên đầu tiên sau khi triển khai (UC04 cần một Quản trị viên để bắt đầu).

Chạy: `uv run python -m loan_system.create_admin <username> <email> "<họ tên>"`
Mật khẩu tạm được in ra một lần; lần đăng nhập đầu phải đổi mật khẩu và đăng ký TOTP.
"""

import sys

from loan_system.clock import SystemClock
from loan_system.config import Settings
from loan_system.db import make_engine, make_session_factory
from loan_system.services.staff_service import DuplicateAccount, create_first_admin


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        raise SystemExit('Usage: python -m loan_system.create_admin <username> <email> "<full name>"')
    username, email, full_name = argv
    factory = make_session_factory(make_engine(Settings().sqlalchemy_url()))
    with factory() as db:
        try:
            password = create_first_admin(
                db, SystemClock(), username=username, full_name=full_name, email=email
            )
        except DuplicateAccount:
            raise SystemExit("Username or email already exists") from None
    # Console Windows dùng cp1258: chỉ in ký tự ASCII.
    print(f"Created admin {username}. Temporary password: {password}")


if __name__ == "__main__":
    main(sys.argv[1:])
