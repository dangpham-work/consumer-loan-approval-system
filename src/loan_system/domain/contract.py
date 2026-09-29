"""Hợp đồng tín dụng điện tử dạng PDF (UC26 bước 5).

Chữ được bỏ dấu tiếng Việt vì phông chữ chuẩn của PDF không có đủ dấu (giống watermark ở M06).
File không nén và mang ngày giải ngân làm ngày tạo, nên cùng điều khoản luôn cho cùng một file:
mã băm SHA-256 lưu kèm hợp đồng nhờ vậy kiểm tra lại được.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from fpdf import FPDF

from loan_system.domain.calculations import ScheduledInstallment
from loan_system.domain.text import fold_diacritics, vnd

_COLUMNS = (("Ky", 12), ("Ngay den han", 32), ("Tien tra", 34), ("Goc", 34), ("Lai", 30),
            ("Du no con lai", 38))


@dataclass(frozen=True)
class ContractTerms:
    contract_no: str
    customer_name: str
    national_id: str  # đã che (SR07)
    address: str
    receiving_account: str  # đã che (SR07)
    principal: Decimal
    annual_rate: Decimal
    term_months: int
    monthly_payment: Decimal
    disbursed_on: date
    schedule: Sequence[ScheduledInstallment]


def render_contract(terms: ContractTerms) -> bytes:
    pdf = FPDF()
    pdf.set_compression(False)
    pdf.set_creation_date(datetime.combine(terms.disbursed_on, time(), tzinfo=UTC))
    pdf.set_title(terms.contract_no)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "HOP DONG TIN DUNG TIEU DUNG", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    rate = f"{terms.annual_rate * 100:.2f}".replace(".", ",")
    for line in (
        f"So hop dong: {terms.contract_no}",
        f"Ngay giai ngan: {terms.disbursed_on:%d/%m/%Y}",
        f"Ben vay: {fold_diacritics(terms.customer_name)} - CCCD {terms.national_id}",
        f"Dia chi: {fold_diacritics(terms.address)}",
        f"Tai khoan nhan tien: {terms.receiving_account}",
        f"So tien vay: {vnd(terms.principal)} dong",
        f"Lai suat: {rate}%/nam, tra gop deu (nien kim) tren du no giam dan",
        f"Ky han: {terms.term_months} thang - So tien tra moi ky: {vnd(terms.monthly_payment)} dong",
    ):
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "LICH TRA NO", new_x="LMARGIN", new_y="NEXT")
    for title, width in _COLUMNS:
        pdf.cell(width, 6, title, border=1, align="C")
    pdf.ln()
    pdf.set_font("Helvetica", size=9)
    for row in terms.schedule:
        values = (str(row.number), f"{row.due_date:%d/%m/%Y}", vnd(row.payment),
                  vnd(row.principal), vnd(row.interest), vnd(row.closing_balance))
        for (_, width), value in zip(_COLUMNS, values):
            pdf.cell(width, 6, value, border=1, align="R")
        pdf.ln()
    return bytes(pdf.output())
