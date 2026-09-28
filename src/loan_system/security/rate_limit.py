"""Giới hạn tần suất theo cửa sổ trượt (SR12).

Bộ đếm nằm trong bộ nhớ tiến trình: đủ cho một tiến trình uvicorn. Chạy nhiều worker thì cần
một bản cài đặt dùng chung (ví dụ Redis) theo cùng giao diện `hit`.
"""

import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta

from loan_system.clock import Clock
from loan_system.config import Settings


class SlidingWindowLimiter:
    def __init__(self, clock: Clock, limit: int, window: timedelta) -> None:
        self._clock = clock
        self._limit = limit
        self._window = window
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Ghi nhận một lượt; trả về False nếu lượt này vượt giới hạn."""
        now = self._clock.now().timestamp()
        oldest_allowed = now - self._window.total_seconds()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= oldest_allowed:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True


@dataclass(frozen=True)
class RateLimits:
    """Các giới hạn tần suất của SR12: đăng nhập, xác thực OTP, nộp hồ sơ vay và tải giấy tờ."""

    login: SlidingWindowLimiter  # theo địa chỉ IP
    otp: SlidingWindowLimiter  # theo địa chỉ IP
    application_write: SlidingWindowLimiter  # theo người dùng

    @classmethod
    def from_settings(cls, settings: Settings, clock: Clock) -> "RateLimits":
        window = timedelta(seconds=settings.rate_window_seconds)
        return cls(
            login=SlidingWindowLimiter(clock, settings.login_rate_limit, window),
            otp=SlidingWindowLimiter(clock, settings.otp_rate_limit, window),
            application_write=SlidingWindowLimiter(
                clock, settings.application_write_rate_limit, window
            ),
        )
