"""Tác vụ hằng đêm (AD06a): Bộ lập lịch (cron, Task Scheduler) gọi lúc 00:30 mỗi ngày.

Chạy: `uv run python -m loan_system.run_nightly_job`. Chạy lại trong cùng ngày không cộng dồn.
"""

from loan_system.adapters.cic import FakeCicGateway
from loan_system.adapters.sms import FakeSmsGateway
from loan_system.clock import SystemClock
from loan_system.config import Settings
from loan_system.db import make_engine, make_session_factory
from loan_system.services.nightly_job import NightlyJob


def main() -> None:
    settings = Settings()
    job = NightlyJob(
        make_session_factory(make_engine(settings.sqlalchemy_url())),
        SystemClock(),
        settings,
        # SMS và CIC đều là giả lập, như ứng dụng web (main.create_app).
        FakeSmsGateway(),
        FakeCicGateway(),
    )
    report = job.run()
    # Console Windows dùng cp1258: chỉ in ký tự ASCII.
    print(f"Nightly job done: {report.summary()}")


if __name__ == "__main__":
    main()
