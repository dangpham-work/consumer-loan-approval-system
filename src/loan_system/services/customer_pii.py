"""Ngữ cảnh mã hóa (associated data AES-GCM, SR06) cho các trường PII của Customer.

Dùng chung giữa application_service.py (sửa qua bước lập hồ sơ vay, UC12) và customer_service.py
(khách hàng tự sửa hồ sơ cá nhân, UC11): chuỗi ngữ cảnh phải khớp hệt giữa lúc mã hóa và lúc giải
mã, nên chỉ định nghĩa một nơi duy nhất — định nghĩa trùng ở hai nơi mà lệch nhau sẽ làm giải mã
thất bại một cách âm thầm (DecryptionFailed), khó dò ra nguyên nhân.
"""

import uuid


def national_id_context(customer_id: uuid.UUID) -> str:
    return f"customers.national_id:{customer_id}"


def income_context(customer_id: uuid.UUID) -> str:
    return f"customers.monthly_income:{customer_id}"
