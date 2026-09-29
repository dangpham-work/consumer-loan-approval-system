"""Seam 2: hợp đồng tín dụng điện tử dạng PDF (UC26 bước 5) và lịch trả nợ tải về (UC27 3a)."""

from datetime import date
from decimal import Decimal

from loan_system.domain.calculations import generate_schedule
from loan_system.domain.contract import (
    ContractTerms,
    ScheduleRow,
    ScheduleTerms,
    render_contract,
    render_schedule,
)
from loan_system.domain.text import fold_diacritics

SCHEDULE = generate_schedule(Decimal(30_000_000), Decimal("0.24"), 12, date(2026, 9, 28))
TERMS = ContractTerms(
    contract_no="HD-HS2026000001",
    customer_name="Nguyễn Văn Đức",
    national_id="079******234",
    address="12 Lê Lợi, Quận 1, TP.HCM",
    receiving_account="012****789",
    principal=Decimal(30_000_000),
    annual_rate=Decimal("0.2400"),
    term_months=12,
    monthly_payment=Decimal(2_836_788),
    disbursed_on=date(2026, 9, 28),
    schedule=SCHEDULE,
)


def test_vietnamese_text_is_folded_to_plain_letters() -> None:
    assert fold_diacritics("Nguyễn Văn Đức, Quận 1") == "Nguyen Van Duc, Quan 1"


def test_contract_is_a_pdf_with_the_loan_terms_and_every_installment() -> None:
    pdf = render_contract(TERMS)

    assert pdf.startswith(b"%PDF-")
    text = pdf.decode("latin-1")
    for expected in (
        "HD-HS2026000001",
        "Nguyen Van Duc",
        "079******234",
        "012****789",
        "30.000.000",
        "24,00%/nam",
        "2.836.788",
        "28/09/2026",
        # Kỳ 12 (28/09/2027): trả 2.836.786, dư nợ về 0 (mục 1.2.8a).
        "28/09/2027",
        "2.836.786",
    ):
        assert expected in text, expected


def test_the_same_terms_always_give_the_same_contract() -> None:
    # Mã băm SHA-256 lưu kèm hợp đồng (UC26 bước 5) chỉ có ý nghĩa khi file sinh ra ổn định.
    assert render_contract(TERMS) == render_contract(TERMS)


def test_schedule_pdf_shows_every_installment_with_its_paid_amount_and_status() -> None:
    schedule = ScheduleTerms(
        loan_code="HS2026000001",
        customer_name="Nguyễn Văn Đức",
        principal=Decimal(30_000_000),
        annual_rate=Decimal("0.2400"),
        term_months=12,
        outstanding_principal=Decimal(27_218_212),
        generated_on=date(2026, 10, 28),
        rows=[
            ScheduleRow(1, date(2026, 10, 28), Decimal(2_236_788), Decimal(600_000), Decimal(0),
                        Decimal(2_836_788), "PAID"),
            ScheduleRow(2, date(2026, 11, 28), Decimal(2_281_163), Decimal(555_625), Decimal(0),
                        Decimal(1_000_000), "PARTIAL"),
            ScheduleRow(3, date(2026, 12, 28), Decimal(2_326_632), Decimal(510_156), Decimal(0),
                        Decimal(0), "UPCOMING"),
        ],
    )

    pdf = render_schedule(schedule)

    assert pdf.startswith(b"%PDF-")
    text = pdf.decode("latin-1")
    for expected in (
        "HS2026000001", "Nguyen Van Duc", "24,00%/nam", "27.218.212",
        "2.836.788", "Da tra", "1.000.000", "Tra mot phan", "Chua den han",
    ):
        assert expected in text, expected
