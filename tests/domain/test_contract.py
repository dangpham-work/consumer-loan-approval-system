"""Seam 2: hợp đồng tín dụng điện tử dạng PDF (UC26 bước 5)."""

from datetime import date
from decimal import Decimal

from loan_system.domain.calculations import generate_schedule
from loan_system.domain.contract import ContractTerms, render_contract
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
