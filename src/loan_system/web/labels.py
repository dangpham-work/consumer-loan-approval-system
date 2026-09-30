"""Nhãn tiếng Việt cho mã trạng thái, loại và trường dữ liệu hiển thị trên giao diện, cùng bộ lọc
định dạng số tiền và ngày giờ dùng trong template."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from loan_system.domain.text import vnd

# Giờ Việt Nam (UTC+7, không đổi giờ theo mùa); CSDL và đồng hồ hệ thống dùng UTC.
VIETNAM_TIME = timezone(timedelta(hours=7))

# Nhãn và sắc thái biểu tượng trạng thái (macro `badge`). Hồ sơ vay bị khóa đang được điều tra: khách
# hàng chỉ thấy "Đang xử lý", không được biết hồ sơ vay bị nghi ngờ (CONTEXT.md, Bị khóa).
APPLICATION_STATUS = {
    "DRAFT": ("Nháp", "neutral"),
    "SUBMITTED": ("Đã nộp", "neutral"),
    "NEED_INFO": ("Cần bổ sung", "warn"),
    "VERIFIED": ("Đã kiểm tra", "neutral"),
    "APPRAISING": ("Đang thẩm định", "neutral"),
    "PENDING_APPROVAL": ("Chờ phê duyệt", "neutral"),
    "APPROVED": ("Đã phê duyệt", "ok"),
    "REJECTED": ("Bị từ chối", "danger"),
    "CANCELLED": ("Đã hủy", "neutral"),
    "DISBURSED": ("Đã giải ngân", "ok"),
    "LOCKED": ("Đang xử lý", "neutral"),
}

LOAN_STATUS = {
    "ACTIVE": ("Đang vay", "ok"),
    "OVERDUE": ("Quá hạn", "danger"),
    "BAD_DEBT": ("Nợ xấu", "danger"),
    "SETTLED": ("Đã tất toán", "neutral"),
}

PURPOSES = {
    "CONSUMER_GOODS": "Mua sắm hàng tiêu dùng",
    "EDUCATION": "Học tập",
    "HEALTHCARE": "Chữa bệnh",
    "HOME_IMPROVEMENT": "Sửa chữa nhà",
    "TRAVEL": "Du lịch",
    "VEHICLE": "Mua xe",
    "OTHER": "Khác",
}

HOUSING_TYPES = {"OWN": "Nhà riêng", "FAMILY": "Ở cùng gia đình", "RENT": "Thuê nhà"}

DOCUMENT_TYPES = {
    "ID_FRONT": "CCCD mặt trước",
    "ID_BACK": "CCCD mặt sau",
    "INCOME_PROOF": "Chứng minh thu nhập",
    "UTILITY_BILL": "Hóa đơn điện, nước",
}

# Trường thông tin của M03 bước 2; cũng là tên mục trong danh sách còn thiếu và yêu cầu bổ sung.
FIELDS = {
    "national_id": "Số CCCD",
    "occupation": "Nghề nghiệp",
    "employer": "Nơi làm việc",
    "employment_years": "Số năm làm việc",
    "monthly_income": "Thu nhập hằng tháng",
    "existing_monthly_debt": "Tiền trả nợ hằng tháng hiện có",
    "housing_type": "Hình thức nhà ở",
    "address": "Địa chỉ",
    "receiving_account": "Số tài khoản nhận tiền",
}

ITEMS = {**FIELDS, **DOCUMENT_TYPES}


def money(amount: Decimal | int | None) -> str:
    return "" if amount is None else f"{vnd(Decimal(amount))} đ"


def day(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.astimezone(VIETNAM_TIME)
    return value.strftime("%d/%m/%Y")


def moment(value: datetime | None) -> str:
    return "" if value is None else value.astimezone(VIETNAM_TIME).strftime("%d/%m/%Y %H:%M")


GLOBALS = {
    "APPLICATION_STATUS": APPLICATION_STATUS,
    "LOAN_STATUS": LOAN_STATUS,
    "PURPOSES": PURPOSES,
    "HOUSING_TYPES": HOUSING_TYPES,
    "DOCUMENT_TYPES": DOCUMENT_TYPES,
    "FIELDS": FIELDS,
    "ITEMS": ITEMS,
}
FILTERS = {"money": money, "day": day, "moment": moment}
