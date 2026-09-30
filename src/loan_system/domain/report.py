"""UC32 Xem báo cáo thống kê (FR08.1, màn hình M11): số liệu tổng hợp về hoạt động cho vay.

Chỉ tính toán và định dạng thuần (khoảng thời gian, tỷ lệ, kết xuất CSV/PDF); truy vấn CSDL nằm ở
`services/report_service.py`. Báo cáo chỉ chứa số liệu tổng hợp, không có dữ liệu định danh khách
hàng (SR07), nên không cần bỏ dấu tên riêng như hợp đồng ở `domain/contract.py`.
"""

import calendar
import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fpdf import FPDF

from loan_system.domain.applications import ApplicationStatus
from loan_system.domain.text import vnd

MAX_RANGE_MONTHS = 12  # UC32 2a: khoảng thời gian quá dài (> 12 tháng) thì yêu cầu thu hẹp

APPLICATION_STATUSES: tuple[str, ...] = tuple(s.value for s in ApplicationStatus)
DEBT_GROUPS: tuple[int, ...] = (1, 2, 3, 4, 5)
CREDIT_GRADES: tuple[str, ...] = ("A", "B", "C", "D")


class InvalidDateRange(Exception):
    """Khoảng thời gian không hợp lệ: ngày kết thúc phải sau ngày bắt đầu."""


class DateRangeTooLong(Exception):
    """UC32 2a: khoảng thời gian vượt quá 12 tháng, cần thu hẹp."""


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def ensure_valid_range(from_date: date, to_date: date) -> None:
    if to_date < from_date:
        raise InvalidDateRange
    if to_date > _add_months(from_date, MAX_RANGE_MONTHS):
        raise DateRangeTooLong


def round_rate(value: Decimal) -> Decimal:
    """Tỷ lệ dạng thập phân (0,5000 = 50%), làm tròn 4 chữ số như DTI (ADR 0001)."""
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def rate(part: int, whole: int) -> Decimal | None:
    """Tỷ lệ phần trên toàn thể; None khi toàn thể bằng 0 (không có dữ liệu để tính tỷ lệ)."""
    if whole == 0:
        return None
    return round_rate(Decimal(part) / Decimal(whole))


def average_days(spans: Sequence[Decimal]) -> Decimal | None:
    """Số ngày xử lý trung bình; None khi không có hồ sơ vay nào đã có quyết định trong kỳ."""
    if not spans:
        return None
    return (sum(spans, Decimal(0)) / len(spans)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class StatisticsReport:
    """Chỉ tiêu tổng hợp cho khoảng [from_date, to_date] (UC32 bước 2, M11).

    Hồ sơ vay được tính theo `submitted_at` trong kỳ; Khoản vay (dư nợ, nhóm nợ) được tính theo các
    khoản giải ngân trong kỳ, vì hệ thống không lưu lịch sử dư nợ theo thời điểm để dựng lại đúng số
    dư tại `to_date` của các khoản vay giải ngân từ trước.
    """

    from_date: date
    to_date: date
    total_applications: int
    applications_by_status: dict[str, int]
    approved_count: int
    rejected_count: int
    approval_rate: Decimal | None
    avg_processing_days: Decimal | None
    total_disbursed: Decimal
    total_loans: int
    outstanding_principal: Decimal
    loans_by_debt_group: dict[int, int]
    overdue_loan_count: int
    overdue_loan_rate: Decimal | None
    credit_grade_distribution: dict[str, int]


def _percent(value: Decimal | None, *, blank: str) -> str:
    if value is None:
        return blank
    return f"{(value * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def render_statistics_csv(report: StatisticsReport) -> str:
    """UC32 3a: xuất Excel, mở được ngay bằng Excel (cùng cách làm CSV của ticket #15).

    BOM UTF-8 ở đầu file để Excel trên Windows nhận đúng mã hóa tiếng Việt thay vì mặc định theo
    bảng mã hệ thống.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Báo cáo thống kê", f"{report.from_date.isoformat()} đến {report.to_date.isoformat()}"])
    writer.writerow([])
    writer.writerow(["Chỉ tiêu", "Giá trị"])
    writer.writerow(["Tổng số hồ sơ vay đã nộp", report.total_applications])
    writer.writerow(["Số hồ sơ vay được duyệt", report.approved_count])
    writer.writerow(["Số hồ sơ vay bị từ chối", report.rejected_count])
    writer.writerow(["Tỷ lệ duyệt", _percent(report.approval_rate, blank="")])
    writer.writerow([
        "Thời gian xử lý trung bình (ngày)",
        report.avg_processing_days if report.avg_processing_days is not None else "",
    ])
    writer.writerow(["Tổng số tiền đã giải ngân (đồng)", vnd(report.total_disbursed)])
    writer.writerow(["Số khoản vay đã giải ngân", report.total_loans])
    writer.writerow(["Dư nợ gốc (đồng)", vnd(report.outstanding_principal)])
    writer.writerow(["Số khoản vay quá hạn", report.overdue_loan_count])
    writer.writerow(["Tỷ lệ quá hạn", _percent(report.overdue_loan_rate, blank="")])
    writer.writerow([])
    writer.writerow(["Trạng thái hồ sơ vay", "Số lượng"])
    for status in APPLICATION_STATUSES:
        writer.writerow([status, report.applications_by_status.get(status, 0)])
    writer.writerow([])
    writer.writerow(["Nhóm nợ", "Số khoản vay"])
    for group in DEBT_GROUPS:
        writer.writerow([group, report.loans_by_debt_group.get(group, 0)])
    writer.writerow([])
    writer.writerow(["Hạng tín dụng", "Số hồ sơ vay"])
    for grade in CREDIT_GRADES:
        writer.writerow([grade, report.credit_grade_distribution.get(grade, 0)])
    return "﻿" + buffer.getvalue()


def _pdf_table(pdf: FPDF, title: str, rows: Sequence[tuple[str, str]]) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    for label, value in rows:
        pdf.cell(70, 6, label, border=1)
        pdf.cell(0, 6, value, border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def render_statistics_pdf(report: StatisticsReport) -> bytes:
    """UC32 3a: xuất PDF; chữ bỏ dấu vì phông chuẩn của PDF không đủ dấu (như hợp đồng, ticket #10).

    Không có tên riêng động (chỉ số liệu tổng hợp, SR07) nên không cần `fold_diacritics`.
    """
    pdf = FPDF()
    pdf.set_compression(False)
    pdf.set_title("Bao cao thong ke")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "BAO CAO THONG KE HOAT DONG CHO VAY", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(
        0, 6, f"Ky bao cao: {report.from_date:%d/%m/%Y} - {report.to_date:%d/%m/%Y}",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(4)
    _pdf_table(pdf, "CHI TIEU TONG HOP", [
        ("Tong so ho so vay da nop", str(report.total_applications)),
        ("So ho so vay duoc duyet", str(report.approved_count)),
        ("So ho so vay bi tu choi", str(report.rejected_count)),
        ("Ty le duyet", _percent(report.approval_rate, blank="-")),
        (
            "Thoi gian xu ly trung binh (ngay)",
            str(report.avg_processing_days) if report.avg_processing_days is not None else "-",
        ),
        ("Tong so tien da giai ngan (dong)", vnd(report.total_disbursed)),
        ("So khoan vay da giai ngan", str(report.total_loans)),
        ("Du no goc (dong)", vnd(report.outstanding_principal)),
        ("So khoan vay qua han", str(report.overdue_loan_count)),
        ("Ty le qua han", _percent(report.overdue_loan_rate, blank="-")),
    ])
    _pdf_table(
        pdf, "HO SO VAY THEO TRANG THAI",
        [(status, str(report.applications_by_status.get(status, 0))) for status in APPLICATION_STATUSES],
    )
    _pdf_table(
        pdf, "KHOAN VAY THEO NHOM NO",
        [(str(group), str(report.loans_by_debt_group.get(group, 0))) for group in DEBT_GROUPS],
    )
    _pdf_table(
        pdf, "HO SO VAY THEO HANG TIN DUNG",
        [(grade, str(report.credit_grade_distribution.get(grade, 0))) for grade in CREDIT_GRADES],
    )
    return bytes(pdf.output())
