"""Seam 2: quy tắc thuần của báo cáo thống kê (UC32, FR08.1, ticket #18)."""

from datetime import date
from decimal import Decimal

import pytest

from loan_system.domain.report import (
    CREDIT_GRADES,
    DEBT_GROUPS,
    DateRangeTooLong,
    InvalidDateRange,
    StatisticsReport,
    average_days,
    ensure_valid_range,
    rate,
    render_statistics_csv,
    render_statistics_pdf,
)


def test_same_day_range_is_valid() -> None:
    ensure_valid_range(date(2026, 1, 1), date(2026, 1, 1))  # không raise


def test_range_of_exactly_12_months_is_valid() -> None:
    ensure_valid_range(date(2026, 1, 1), date(2027, 1, 1))  # không raise


def test_range_over_12_months_is_rejected() -> None:
    with pytest.raises(DateRangeTooLong):
        ensure_valid_range(date(2026, 1, 1), date(2027, 1, 2))


def test_range_over_12_months_from_end_of_month_accounts_for_shorter_months() -> None:
    """31/01 + 12 tháng = 31/01 năm sau; 28/02 vẫn còn trong khoảng vì tháng 2 chỉ có 28 ngày."""
    with pytest.raises(DateRangeTooLong):
        ensure_valid_range(date(2026, 1, 31), date(2027, 2, 1))


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(InvalidDateRange):
        ensure_valid_range(date(2026, 2, 1), date(2026, 1, 1))


def test_rate_is_none_when_there_is_nothing_to_divide_by() -> None:
    assert rate(0, 0) is None


def test_rate_rounds_to_four_decimals_half_up() -> None:
    assert rate(1, 3) == Decimal("0.3333")


def test_average_days_is_none_when_there_are_no_spans() -> None:
    assert average_days([]) is None


def test_average_days_rounds_to_two_decimals_half_up() -> None:
    assert average_days([Decimal(1), Decimal(2)]) == Decimal("1.50")


def _report(**overrides: object) -> StatisticsReport:
    values: dict[str, object] = {
        "from_date": date(2026, 1, 1),
        "to_date": date(2026, 1, 31),
        "total_applications": 10,
        "applications_by_status": {"APPROVED": 6, "REJECTED": 4},
        "approved_count": 6,
        "rejected_count": 4,
        "approval_rate": Decimal("0.6000"),
        "avg_processing_days": Decimal("2.50"),
        "total_disbursed": Decimal(150_000_000),
        "total_loans": 6,
        "outstanding_principal": Decimal(140_000_000),
        "loans_by_debt_group": {1: 5, 2: 1, 3: 0, 4: 0, 5: 0},
        "overdue_loan_count": 1,
        "overdue_loan_rate": Decimal("0.1667"),
        "credit_grade_distribution": {"A": 3, "B": 3, "C": 0, "D": 0},
    }
    values.update(overrides)
    return StatisticsReport(**values)  # type: ignore[arg-type]


def test_csv_export_starts_with_a_utf8_bom_so_excel_reads_vietnamese_text() -> None:
    csv_text = render_statistics_csv(_report())
    assert csv_text.startswith("﻿")


def test_csv_export_contains_the_headline_figures_and_breakdowns() -> None:
    csv_text = render_statistics_csv(_report())
    assert "150.000.000" in csv_text  # tổng giải ngân, định dạng tiền Việt (domain/text.py)
    assert "60.00%" in csv_text  # tỷ lệ duyệt
    for group in DEBT_GROUPS:
        assert f"{group}," in csv_text
    for grade in CREDIT_GRADES:
        assert f"{grade}," in csv_text


def test_csv_export_blanks_rates_that_have_no_data_instead_of_zero() -> None:
    csv_text = render_statistics_csv(_report(approval_rate=None, overdue_loan_rate=None))
    assert "Tỷ lệ duyệt,\r\n" in csv_text or "Tỷ lệ duyệt,\n" in csv_text


def test_pdf_export_produces_a_non_empty_pdf_document() -> None:
    pdf_bytes = render_statistics_pdf(_report())
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 0
