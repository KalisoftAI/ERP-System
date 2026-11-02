# ERP-V1 Detailed Changes — Code Specification

> Companion to `ROADMAP.md`. Branch: `feature/quote-pdf-vci-packaging-roadmap` (**local only, no push** — `master` is deployed).
>
> Guardrails: logo file is **read-only** (byte-for-byte copy for backend embedding, never edited); catalog files get **required changes only**; all new code follows existing FastAPI + SQLAlchemy 2.0 + React patterns.

---

# Change 1 — Quote PDF Document + Email

## 1.1 What exists today (relevant)

- `backend/app/services/email_service.py` — plain-text/HTML email only, **no attachment support**
- `backend/app/models.py` — `EmailLog` + `EmailType` (order_confirmation / dispatch_email), `Customer`, `Product`
- `backend/requirements.txt` — **reportlab 4.2.5 already present** (no new dep for PDF)
- Frontend: `api.js` has `downloadFile()` blob helper; email preview/send pattern exists in `orders.py` (`/email-preview/...`, `/send-confirmation`, `_log_email`)
- Logo: `frontend/public/kalika-logo.jpeg` (used by sidebar/login)

## 1.2 Logo asset for backend (read-only copy)

PDFs are generated server-side, so the backend needs the same logo bytes:

```powershell
# One-time, byte-for-byte copy — NEVER edit/recolor/crop the file
New-Item -ItemType Directory backend\app\assets -Force
Copy-Item frontend\public\kalika-logo.jpeg backend\app\assets\kalika-logo.jpeg
```

## 1.3 Models — `backend/app/models.py` (append)

```python
class QuoteStatus(str, enum.Enum):
    draft = "DRAFT"
    sent = "SENT"
    accepted = "ACCEPTED"
    rejected = "REJECTED"
    expired = "EXPIRED"


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # KE-Q-2026-0001
    quote_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    payment_terms: Mapped[str] = mapped_column(String(255), default="")
    delivery_terms: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    tax_total: Mapped[float] = mapped_column(Float, default=0.0)
    grand_total: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[QuoteStatus] = mapped_column(Enum(QuoteStatus), default=QuoteStatus.draft, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["QuotationLine"]] = relationship(back_populates="quotation",
                                                        cascade="all, delete-orphan")


class QuotationLine(Base):
    __tablename__ = "quotation_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    item_code: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hsn: Mapped[str] = mapped_column(String(20), default="")
    uom: Mapped[str] = mapped_column(String(30), default="Each")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    rate: Mapped[float] = mapped_column(Float, default=0.0)
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    gst_pct: Mapped[float] = mapped_column(Float, default=18.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # qty*rate*(1-disc/100)

    quotation: Mapped[Quotation] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()
```

Extend `EmailType` and `EmailLog` (edit existing classes):

```python
class EmailType(str, enum.Enum):
    order_confirmation = "Order Confirmation"
    dispatch_email = "Dispatch Email"
    quote_email = "Quote Email"            # NEW


class EmailLog(Base):
    # ... existing columns ...
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotations.id"), nullable=True, index=True)  # NEW
    quotation: Mapped[Quotation | None] = relationship()                                                    # NEW
```

## 1.4 Schemas — `backend/app/schemas.py` (append)

```python
# ---- Quotations ----
class QuoteLineIn(BaseModel):
    product_id: Optional[int] = None
    item_code: str = ""
    description: str = ""
    hsn: str = ""
    uom: str = "Each"
    quantity: float = Field(ge=0, default=0)
    rate: float = Field(ge=0, default=0)
    discount_pct: float = Field(ge=0, le=100, default=0)
    gst_pct: float = Field(ge=0, le=28, default=18)


class QuoteLineOut(QuoteLineIn, ORMModel):
    id: int
    amount: float


class QuoteCreate(BaseModel):
    customer_id: int
    quote_date: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    subject: str = ""
    payment_terms: str = ""
    delivery_terms: str = ""
    notes: str = ""
    lines: list[QuoteLineIn] = Field(min_length=1)


class QuoteUpdate(BaseModel):
    customer_id: Optional[int] = None
    valid_until: Optional[datetime] = None
    subject: Optional[str] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    lines: Optional[list[QuoteLineIn]] = None


class QuoteOut(ORMModel):
    id: int
    quote_no: str
    quote_date: datetime
    valid_until: Optional[datetime]
    customer_id: int
    customer_name: str = ""
    customer_email: str = ""
    subject: str
    payment_terms: str
    delivery_terms: str
    notes: str
    subtotal: float
    tax_total: float
    grand_total: float
    status: str
    created_at: datetime
    lines: list[QuoteLineOut] = []
```

## 1.5 PDF service — `backend/app/services/pdf_service.py` (NEW)

Uses reportlab (already a dependency). Logo is embedded **as-is** — only scaled for layout, file never altered.

```python
"""Server-side PDF generation for customer-facing documents (quotes, VCI slips).

Design language matches the sample quote (gs://kalika_enterprises/docs/DOC-20260910-WA0007.pdf):
branded header with the unchanged Kalika logo, line-items table, tax breakup, T&C, signatory.
"""
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "kalika-logo.jpeg"   # READ-ONLY — never modify

BRAND = colors.HexColor("#1F3864")            # Kalika standard blue
LIGHT = colors.HexColor("#EDF1F8")

COMPANY = {
    "name": "Kalika Enterprises",
    "address": "Gat No. 123, MIDC Industrial Area, Pune, Maharashtra 411026",
    "gstin": "27XXXXX0000X1Z5",
    "email": "kalikaenterprises@gmail.com",
    "phone": "+91-98XXXXXXXX",
    "bank": "Bank: HDFC Bank | A/c: 5020XXXXXXXX | IFSC: HDFC0000123 | Branch: Pune",
}

TERMS = [
    "Prices are in INR and exclusive of GST unless stated otherwise.",
    "Validity: As mentioned in the quote header.",
    "Delivery: As per delivery terms; transit insurance on buyer's account unless agreed.",
    "Payment: As per agreed payment terms.",
    "VCI packaging as per Kalika standard packing specification, where applicable.",
]


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=ss["Title"], fontSize=16, textColor=BRAND,
                                spaceAfter=2 * mm),
        "h": ParagraphStyle("h", parent=ss["Heading4"], textColor=BRAND, spaceBefore=3 * mm),
        "n": ParagraphStyle("n", parent=ss["Normal"], fontSize=9, leading=12),
        "small": ParagraphStyle("small", parent=ss["Normal"], fontSize=8, leading=10,
                                textColor=colors.HexColor("#444444")),
    }


def _header(story, st, doc_title, ref_no, ref_date, valid_until=None):
    logo = Image(str(LOGO_PATH), width=38 * mm, height=19 * mm)  # aspect kept; file untouched
    right = Paragraph(
        f"<b>{COMPANY['name']}</b><br/>{COMPANY['address']}<br/>"
        f"GSTIN: {COMPANY['gstin']}<br/>{COMPANY['email']} | {COMPANY['phone']}", st["n"])
    head = Table([[logo, right]], colWidths=[45 * mm, 135 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story += [head, Spacer(1, 2 * mm), Paragraph(doc_title, st["title"])]

    meta = [[f"{doc_title} No:", ref_no, "Date:", ref_date.strftime("%d-%b-%Y")]]
    if valid_until:
        meta.append(["Valid Until:", valid_until.strftime("%d-%b-%Y"), "", ""])
    t = Table(meta, colWidths=[30 * mm, 60 * mm, 20 * mm, 70 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica-Bold", 9),
                           ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                           ("BOX", (0, 0), (-1, -1), 0.5, BRAND)]))
    story += [t, Spacer(1, 2 * mm)]


def _party_block(story, st, customer):
    story.append(Paragraph("To,", st["h"]))
    story.append(Paragraph(
        f"<b>{customer.name}</b><br/>{customer.company}<br/>"
        f"{(customer.address or '').replace(chr(10), '<br/>')}<br/>"
        f"GSTIN: {customer.gstin or '-'}<br/>Email: {customer.email or '-'}", st["n"]))
    story.append(Spacer(1, 2 * mm))


def _money(v): return f"{v:,.2f}"


def generate_quote_pdf(q, customer) -> bytes:
    """q: Quotation (with .lines loaded), customer: Customer."""
    st = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=15 * mm,
                            title=f"Quotation {q.quote_no}")
    story = []
    _header(story, st, "QUOTATION", q.quote_no, q.quote_date, q.valid_until)
    _party_block(story, st, customer)
    if q.subject:
        story.append(Paragraph(f"<b>Subject:</b> {q.subject}", st["n"]))

    rows = [["#", "Item Code", "Description", "HSN", "Qty", "UOM",
             "Rate", "Disc%", "GST%", "Amount"]]
    for i, ln in enumerate(q.lines, 1):
        rows.append([str(i), ln.item_code or "-", Paragraph(ln.description or "-", st["small"]),
                     ln.hsn or "-", f"{ln.quantity:g}", ln.uom, _money(ln.rate),
                     f"{ln.discount_pct:g}", f"{ln.gst_pct:g}", _money(ln.amount)])
    tbl = Table(rows, colWidths=[8*mm, 22*mm, 52*mm, 16*mm, 12*mm, 13*mm, 18*mm, 13*mm, 13*mm, 20*mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9AA7C7")),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]))
    story += [Spacer(1, 2 * mm), tbl]

    totals = [["Subtotal", _money(q.subtotal)], ["GST", _money(q.tax_total)],
              ["Grand Total (INR)", _money(q.grand_total)]]
    tt = Table(totals, colWidths=[150 * mm, 30 * mm])
    tt.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("FONT", (0, 2), (-1, 2), "Helvetica-Bold", 9),
                            ("LINEABOVE", (0, 2), (-1, 2), 0.8, BRAND)]))
    story += [Spacer(1, 1.5 * mm), tt]

    story.append(Paragraph(f"<b>Payment Terms:</b> {q.payment_terms or '-'}", st["n"]))
    story.append(Paragraph(f"<b>Delivery Terms:</b> {q.delivery_terms or '-'}", st["n"]))
    if q.notes:
        story.append(Paragraph(f"<b>Notes:</b> {q.notes}", st["n"]))
    story.append(Paragraph("Terms & Conditions", st["h"]))
    for i, t_ in enumerate(TERMS, 1):
        story.append(Paragraph(f"{i}. {t_}", st["small"]))
    story.append(Paragraph(COMPANY["bank"], st["small"]))

    sign = Table([["For Kalika Enterprises", "", "Customer Acceptance"],
                  ["\n\nAuthorised Signatory", "", "Signature & Stamp"]],
                 colWidths=[70 * mm, 40 * mm, 70 * mm])
    sign.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                              ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story += [Spacer(1, 10 * mm), sign]

    doc.build(story)
    return buf.getvalue()
```

## 1.6 Email attachments — `email_service.py` (add one function)

```python
from email.mime.application import MIMEApplication   # add import


def send_email_with_attachment(to: str, subject: str, body: str,
                               attachment: bytes, filename: str,
                               mime_subtype: str = "pdf") -> tuple[bool, str]:
    """Same SMTP path as send_email(), plus a binary attachment (quote PDF)."""
    if not is_valid_email(to):
        return False, f"Invalid recipient email address: {to}"
    ok, err = mail_config_ok()
    if not ok:
        return False, err

    sender = settings.MAIL_FROM or settings.MAIL_USERNAME
    sender_name = settings.MAIL_FROM_NAME or "Kalika Enterprises"

    msg = MIMEMultipart("mixed")
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = to.strip()
    msg["Subject"] = subject.strip()
    plain = body.strip()
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    part = MIMEApplication(attachment, _subtype=mime_subtype)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
            server.ehlo()
            if settings.SMTP_USE_TLS:
                server.starttls(); server.ehlo()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.sendmail(sender, [to.strip()], msg.as_string())
        logger.info("Email with attachment sent to %s (subject: %s)", to.strip(), subject.strip())
        return True, ""
    except smtplib.SMTPException as exc:
        logger.warning("SMTP error sending attachment email: %s", exc)
        return False, "Email server error. Please try again later."
```

## 1.7 Router — `backend/app/routers/quotes.py` (NEW)

Follows the same preview → send → log pattern as `orders.py`.

```python
"""Quotations: CRUD, branded PDF download, email with PDF attachment."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import AllStaff, CurrentUser, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import Customer, EmailLog, EmailType, Quotation, QuotationLine, QuoteStatus
from ..schemas import EmailSendIn, EmailPreviewOut, QuoteCreate, QuoteOut, QuoteUpdate
from ..services.email_service import (is_valid_email, mail_config_ok,
                                      send_email_with_attachment)
from ..services.pdf_service import generate_quote_pdf

router = APIRouter(prefix="/quotes", tags=["quotes"])


def _next_quote_no(db: Session) -> str:
    year = datetime.utcnow().year
    prefix = f"KE-Q-{year}-"
    last = db.scalar(select(Quotation.quote_no).where(Quotation.quote_no.like(f"{prefix}%"))
                     .order_by(Quotation.quote_no.desc()))
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def _compute_totals(lines: list[QuotationLine]) -> tuple[float, float, float]:
    subtotal = tax = 0.0
    for ln in lines:
        ln.amount = round(ln.quantity * ln.rate * (1 - ln.discount_pct / 100), 2)
        subtotal += ln.amount
        tax += ln.amount * ln.gst_pct / 100
    return round(subtotal, 2), round(tax, 2), round(subtotal + tax, 2)


def _out(db: Session, q: Quotation) -> dict:
    cust = db.get(Customer, q.customer_id)
    data = QuoteOut.model_validate(q).model_dump()
    data["customer_name"] = cust.name if cust else ""
    data["customer_email"] = cust.email if cust else ""
    return data


@router.get("", response_model=dict)
def list_quotes(db: Annotated[Session, Depends(get_db)], _: CurrentUser,
                search: str = "", status_filter: str = Query("", alias="status"),
                page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500)):
    stmt = select(Quotation).options(selectinload(Quotation.lines))
    if search:
        like = f"%{search}%"
        stmt = stmt.join(Customer, Quotation.customer_id == Customer.id).where(
            (Quotation.quote_no.ilike(like)) | (Customer.name.ilike(like)))
    if status_filter:
        stmt = stmt.where(Quotation.status == status_filter)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Quotation.quote_date.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_out(db, q) for q in rows], "total": total,
            "page": page, "page_size": page_size}


@router.post("", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def create_quote(body: QuoteCreate, db: Annotated[Session, Depends(get_db)],
                 user: AllStaff):
    get_or_404(db, Customer, body.customer_id)
    q = Quotation(quote_no=_next_quote_no(db),
                  quote_date=body.quote_date or datetime.utcnow(),
                  valid_until=body.valid_until, customer_id=body.customer_id,
                  subject=body.subject, payment_terms=body.payment_terms,
                  delivery_terms=body.delivery_terms, notes=body.notes,
                  created_by=user.id)
    q.lines = [QuotationLine(**ln.model_dump()) for ln in body.lines]
    q.subtotal, q.tax_total, q.grand_total = _compute_totals(q.lines)
    db.add(q); db.commit(); db.refresh(q)
    write_audit(db, user, "CREATE", "quotations", q.id, f"Created quotation {q.quote_no}")
    return _out(db, q)


@router.get("/{quote_id}", response_model=QuoteOut)
def get_quote(quote_id: int, db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    return _out(db, get_or_404(db, Quotation, quote_id))


@router.patch("/{quote_id}", response_model=QuoteOut)
def update_quote(quote_id: int, body: QuoteUpdate,
                 db: Annotated[Session, Depends(get_db)], user: AllStaff):
    q = get_or_404(db, Quotation, quote_id)
    data = body.model_dump(exclude_unset=True)
    lines = data.pop("lines", None)
    if "status" in data and data["status"] is not None:
        data["status"] = QuoteStatus(data["status"])
    if "customer_id" in data and data["customer_id"]:
        get_or_404(db, Customer, data["customer_id"])
    for k, v in data.items():
        setattr(q, k, v)
    if lines is not None:
        q.lines.clear(); db.flush()
        q.lines = [QuotationLine(**ln) for ln in lines]
    q.subtotal, q.tax_total, q.grand_total = _compute_totals(q.lines)
    db.commit(); db.refresh(q)
    write_audit(db, user, "UPDATE", "quotations", q.id, f"Updated quotation {q.quote_no}")
    return _out(db, q)


@router.delete("/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quote(quote_id: int, db: Annotated[Session, Depends(get_db)],
                 user: ManagerOrAdmin):
    q = get_or_404(db, Quotation, quote_id)
    if q.status == QuoteStatus.sent:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Cannot delete a sent quotation. Mark it rejected instead.")
    db.delete(q); db.commit()
    write_audit(db, user, "DELETE", "quotations", quote_id, f"Deleted quotation {q.quote_no}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{quote_id}/pdf")
def quote_pdf(quote_id: int, db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    q = get_or_404(db, Quotation, quote_id)
    customer = db.get(Customer, q.customer_id)
    pdf = generate_quote_pdf(q, customer)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Quotation_{q.quote_no}.pdf"'})


def _quote_email_body(q: Quotation, customer: Customer) -> str:
    return (f"Dear {customer.contact_person or customer.name},\n\n"
            f"Thank you for your enquiry. Please find attached our quotation {q.quote_no} "
            f"dated {q.quote_date:%d-%b-%Y}.\n\n"
            f"Quote Value: INR {q.grand_total:,.2f} (incl. GST)\n"
            f"Valid Until: {q.valid_until:%d-%b-%Y if q.valid_until else '-'}\n\n"
            f"We look forward to your valued order.\n\nRegards,\nKalika Enterprises")


@router.get("/{quote_id}/email-preview", response_model=EmailPreviewOut)
def preview_quote_email(quote_id: int, db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    q = get_or_404(db, Quotation, quote_id)
    customer = db.get(Customer, q.customer_id)
    return {"to": customer.email if customer else "",
            "subject": f"Quotation {q.quote_no} - Kalika Enterprises",
            "message": _quote_email_body(q, customer)}


@router.post("/{quote_id}/send-quote", response_model=dict)
def send_quote_email(quote_id: int, body: EmailSendIn,
                     db: Annotated[Session, Depends(get_db)], user: AllStaff):
    q = get_or_404(db, Quotation, quote_id)
    customer = db.get(Customer, q.customer_id)

    def _fail(detail: str, http_status: int):
        log = EmailLog(email_type=EmailType.quote_email, recipient=body.to.strip(),
                       subject=body.subject.strip(), status="failed",
                       error_message=detail, quote_id=q.id)
        db.add(log); db.commit()
        raise HTTPException(http_status, detail)

    if not is_valid_email(body.to):
        _fail(f"Invalid recipient email address: {body.to}", status.HTTP_400_BAD_REQUEST)
    ok, err = mail_config_ok()
    if not ok:
        _fail(err, status.HTTP_503_SERVICE_UNAVAILABLE)

    pdf = generate_quote_pdf(q, customer)
    success, error = send_email_with_attachment(
        body.to, body.subject, body.message, pdf, f"Quotation_{q.quote_no}.pdf")
    db.add(EmailLog(email_type=EmailType.quote_email, recipient=body.to.strip(),
                    subject=body.subject.strip(),
                    status="sent" if success else "failed",
                    error_message=error, quote_id=q.id))
    if success:
        q.status = QuoteStatus.sent
    db.commit()
    if not success:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, error)
    write_audit(db, user, "SEND_EMAIL", "quotations", q.id,
                f"Sent quotation {q.quote_no} PDF to {body.to}")
    db.commit()
    return {"success": True, "message": "Quotation emailed with PDF attachment."}
```

Register in `backend/app/main.py` (after line 315):

```python
app.include_router(quotes.router)          # NEW — also add `quotes` to the router import
```

## 1.8 Migration — `backend/scripts/migrate_quotes.py` (NEW, idempotent)

```python
"""Create quotations tables + email_logs.quote_id. Safe to re-run."""
from sqlalchemy import inspect, text
from app.database import engine
from app.models import Base, Quotation, QuotationLine  # noqa: F401 (register tables)


def run():
    insp = inspect(engine)
    Base.metadata.create_all(engine, tables=[Quotation.__table__, QuotationLine.__table__])
    cols = {c["name"] for c in insp.get_columns("email_logs")}
    with engine.begin() as conn:
        if "quote_id" not in cols:
            conn.execute(text(
                "ALTER TABLE email_logs ADD COLUMN quote_id INTEGER REFERENCES quotations(id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_email_logs_quote_id "
                          "ON email_logs (quote_id)"))
    print("quotation migration done")


if __name__ == "__main__":
    run()
```

## 1.9 Frontend

**`frontend/src/pages/Quotes.jsx` (NEW)** — key excerpts (table + line editor + actions follow existing `Orders.jsx`/`Table.jsx` patterns):

```jsx
import { useEffect, useState } from 'react'
import api, { downloadFile } from '../lib/api'

export default function Quotes() {
  const [rows, setRows] = useState({ items: [], total: 0 })
  const [search, setSearch] = useState('')
  const [emailFor, setEmailFor] = useState(null)      // quote being emailed
  const [emailForm, setEmailForm] = useState({ to: '', subject: '', message: '' })

  const load = () =>
    api.get('/quotes', { params: { search } }).then(r => setRows(r.data))

  useEffect(() => { load() }, [search])

  const openEmail = async (q) => {
    const { data } = await api.get(`/quotes/${q.id}/email-preview`)
    setEmailFor(q); setEmailForm(data)
  }

  const sendEmail = async () => {
    await api.post(`/quotes/${emailFor.id}/send-quote`, emailForm)
    setEmailFor(null); load()
  }

  return (
    <div className="p-4">
      <div className="flex gap-2 mb-3">
        <input value={search} onChange={e => setSearch(e.target.value)}
               placeholder="Search quote no / customer" className="input" />
        {/* <QuoteEditor onSaved={load}/> — create/edit modal with line-items grid:
             customer select, subject, valid_until, terms, and rows of
             {item_code, description, hsn, qty, uom, rate, discount_pct, gst_pct} */}
      </div>

      <table className="w-full text-sm">
        <thead><tr>
          <th>Quote No</th><th>Date</th><th>Customer</th>
          <th className="text-right">Total (INR)</th><th>Status</th><th/>
        </tr></thead>
        <tbody>
          {rows.items.map(q => (
            <tr key={q.id} className="border-t">
              <td>{q.quote_no}</td>
              <td>{new Date(q.quote_date).toLocaleDateString('en-IN')}</td>
              <td>{q.customer_name}</td>
              <td className="text-right">{q.grand_total.toLocaleString('en-IN')}</td>
              <td>{q.status}</td>
              <td className="flex gap-2 justify-end">
                <button onClick={() => downloadFile(`/quotes/${q.id}/pdf`,
                          `Quotation_${q.quote_no}.pdf`)}>PDF</button>
                <button onClick={() => openEmail(q)}>Email</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {emailFor && (
        <div className="modal">{/* same modal chrome as Orders email dialog */}
          <h3>Email Quotation {emailFor.quote_no}</h3>
          <input value={emailForm.to}
                 onChange={e => setEmailForm({ ...emailForm, to: e.target.value })} />
          <input value={emailForm.subject}
                 onChange={e => setEmailForm({ ...emailForm, subject: e.target.value })} />
          <textarea rows={8} value={emailForm.message}
                    onChange={e => setEmailForm({ ...emailForm, message: e.target.value })} />
          <button onClick={sendEmail}>Send with PDF</button>
          <button onClick={() => setEmailFor(null)}>Cancel</button>
        </div>
      )}
    </div>
  )
}
```

**Route** — `App.jsx`:

```jsx
import Quotes from './pages/Quotes'
// inside <Route path="/" ...>:
<Route path="quotes" element={<Quotes />} />
```

**Nav** — `components/Layout.jsx`, in the **Operations** section:

```jsx
{ to: '/quotes', label: 'Quotations', icon: FileText },  // import FileText from lucide-react
```

## 1.10 Test checklist

- `POST /api/quotes` creates quote with computed totals; `quote_no` increments per year
- `GET /api/quotes/{id}/pdf` → branded PDF, **logo unchanged**, opens in viewer
- `POST /api/quotes/{id}/send-quote` → mail with PDF attached; `email_logs` row (`quote_email`); status flips `DRAFT → SENT`
- Validation failures logged as `failed` with correct HTTP codes (400/503/502)

---

# Change 2 — VCI Packaging Document

Same design language as the quote (Kalika logo header, standard table styling) — **logo untouched**. Generated from dispatch/production context.

## 2.1 Model — `models.py` (append)

```python
class VCIPackingSlip(Base):
    __tablename__ = "vci_packing_slips"

    id: Mapped[int] = mapped_column(primary_key=True)
    slip_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # KE-VCI-2026-0001
    packing_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True)
    dispatch_id: Mapped[int | None] = mapped_column(ForeignKey("dispatches.id"), nullable=True)
    item_code: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    uom: Mapped[str] = mapped_column(String(30), default="Each")
    vci_type: Mapped[str] = mapped_column(String(60), default="VCI Film")  # Film/Bag/Emitter/Paper
    batch_no: Mapped[str] = mapped_column(String(80), default="")
    packed_by: Mapped[str] = mapped_column(String(120), default="")
    checked_by: Mapped[str] = mapped_column(String(120), default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer: Mapped[Customer | None] = relationship()
```

## 2.2 PDF — add to `pdf_service.py`

```python
def generate_vci_packing_pdf(slip, customer) -> bytes:
    st = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=15 * mm,
                            title=f"VCI Packing Slip {slip.slip_no}")
    story = []
    _header(story, st, "VCI PACKING SLIP", slip.slip_no, slip.packing_date)
    if customer:
        _party_block(story, st, customer)

    rows = [["Item Code", "Description", "Qty", "UOM", "VCI Type", "Batch No"],
            [slip.item_code or "-", Paragraph(slip.description or "-", st["small"]),
             f"{slip.quantity:g}", slip.uom, slip.vci_type, slip.batch_no or "-"]]
    t = Table(rows, colWidths=[25*mm, 65*mm, 15*mm, 15*mm, 30*mm, 30*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9AA7C7")),
    ]))
    story += [t, Spacer(1, 3 * mm)]

    story.append(Paragraph("VCI Packing Standard", st["h"]))
    for i, s in enumerate([
        "Parts cleaned, dried and free of corrosion before packing.",
        "VCI material kept in direct/close proximity to metal surfaces; pack sealed air-tight.",
        "Do not open pack until point of use; re-seal immediately if opened.",
        "Shelf life of VCI protection: 12 months in sealed condition.",
    ], 1):
        story.append(Paragraph(f"{i}. {s}", st["small"]))
    if slip.remarks:
        story.append(Paragraph(f"<b>Remarks:</b> {slip.remarks}", st["n"]))

    sign = Table([["Packed By", "Checked By (QC)"],
                  [f"\n\n{slip.packed_by or '____________'}",
                   f"\n\n{slip.checked_by or '____________'}"]],
                 colWidths=[90 * mm, 90 * mm])
    sign.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                              ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story += [Spacer(1, 10 * mm), sign]
    doc.build(story)
    return buf.getvalue()
```

## 2.3 Router — `backend/app/routers/vci.py` (NEW)

```python
"""VCI packing slips: create from dispatch/order context, branded PDF download."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import AllStaff, CurrentUser
from ..crud import get_or_404, write_audit
from ..database import get_db
from ..models import Customer, VCIPackingSlip
from ..schemas import VCISlipCreate, VCISlipOut
from ..services.pdf_service import generate_vci_packing_pdf

router = APIRouter(prefix="/vci-slips", tags=["vci"])


def _next_slip_no(db: Session) -> str:
    prefix = f"KE-VCI-{datetime.utcnow().year}-"
    last = db.scalar(select(VCIPackingSlip.slip_no)
                     .where(VCIPackingSlip.slip_no.like(f"{prefix}%"))
                     .order_by(VCIPackingSlip.slip_no.desc()))
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


@router.get("", response_model=dict)
def list_slips(db: Annotated[Session, Depends(get_db)], _: CurrentUser,
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500)):
    stmt = select(VCIPackingSlip)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(VCIPackingSlip.packing_date.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [VCISlipOut.model_validate(r).model_dump() for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=VCISlipOut, status_code=status.HTTP_201_CREATED)
def create_slip(body: VCISlipCreate, db: Annotated[Session, Depends(get_db)], user: AllStaff):
    if body.customer_id:
        get_or_404(db, Customer, body.customer_id)
    slip = VCIPackingSlip(slip_no=_next_slip_no(db), **body.model_dump())
    db.add(slip); db.commit(); db.refresh(slip)
    write_audit(db, user, "CREATE", "vci_packing_slips", slip.id,
                f"Created VCI slip {slip.slip_no}")
    return slip


@router.get("/{slip_id}/pdf")
def slip_pdf(slip_id: int, db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    slip = get_or_404(db, VCIPackingSlip, slip_id)
    customer = db.get(Customer, slip.customer_id) if slip.customer_id else None
    pdf = generate_vci_packing_pdf(slip, customer)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="VCI_Slip_{slip.slip_no}.pdf"'})
```

Schemas (append to `schemas.py`):

```python
class VCISlipCreate(BaseModel):
    customer_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    dispatch_id: Optional[int] = None
    item_code: str = ""
    description: str = ""
    quantity: float = Field(ge=0, default=0)
    uom: str = "Each"
    vci_type: str = "VCI Film"
    batch_no: str = ""
    packed_by: str = ""
    checked_by: str = ""
    remarks: str = ""


class VCISlipOut(VCISlipCreate, ORMModel):
    id: int
    slip_no: str
    packing_date: datetime
    created_at: datetime
```

Register in `main.py`: `app.include_router(vci.router)` (add import).
Migration: extend `scripts/migrate_quotes.py` `create_all` tables list with `VCIPackingSlip.__table__` (or rename script `migrate_phase7.py`).

## 2.4 Frontend

Add a **"VCI Slip"** action on the Dispatch page row (dispatch context pre-fills customer/item/qty) and/or a standalone `pages/VCI.jsx` using the same patterns as `Quotes.jsx`:

```jsx
// inside Dispatch.jsx row actions:
<button onClick={() => createVciSlip(d)}>VCI Slip</button>

const createVciSlip = async (d) => {
  const { data: slip } = await api.post('/vci-slips', {
    customer_id: d.customer_id, dispatch_id: d.id,
    item_code: d.item_code, description: d.description, quantity: d.quantity,
  })
  downloadFile(`/vci-slips/${slip.id}/pdf`, `VCI_Slip_${slip.slip_no}.pdf`)
}
```

## 2.5 Test checklist

- Slip number sequence per year; PDF carries unchanged logo + standard design
- Creating from dispatch pre-fills correctly; PDF downloads with correct filename

---

# Change 3 — SOPs of Other Processes (Human Review)

Keep it stupidly simple: SOPs are versioned markdown in the repo, reviewed by a human **before** use — no DB needed.

## 3.1 Structure

```
frontend/docs/sops/
  README.md                 <- review tracker (status table)
  sales-process.md
  purchase-process.md
  inventory-process.md
  production-process.md
  dispatch-process.md
  quality-vci-packing.md
```

## 3.2 SOP template (each file starts with this frontmatter)

```markdown
---
sop_id: SOP-DISPATCH-001
title: Dispatch Process
version: 0.1.0
status: DRAFT            # DRAFT -> IN_REVIEW -> APPROVED
owner: <process owner>
reviewer: <human reviewer name>   # REQUIRED before APPROVED
last_reviewed: null
---

# Dispatch Process

## 1. Purpose
...
## 2. Scope
...
## 3. Steps
...
## 4. Records (ERP screens / documents)
...
```

## 3.3 Review tracker — `frontend/docs/sops/README.md`

```markdown
# SOP Review Tracker

| SOP ID | Title | Version | Status | Reviewer | Reviewed On |
|--------|-------|---------|--------|----------|-------------|
| SOP-SALES-001 | Sales Process | 0.1.0 | DRAFT | — | — |
| SOP-PURCH-001 | Purchase Process | 0.1.0 | DRAFT | — | — |
| SOP-INV-001 | Inventory Process | 0.1.0 | DRAFT | — | — |
| SOP-PROD-001 | Production Process | 0.1.0 | DRAFT | — | — |
| SOP-DISP-001 | Dispatch Process | 0.1.0 | DRAFT | — | — |
| SOP-QA-VCI-001 | VCI Packing | 0.1.0 | DRAFT | — | — |

**Rule:** a SOP moves `DRAFT -> IN_REVIEW -> APPROVED` only with a named human
reviewer and a review date. No SOP is published for use while in DRAFT.
```

## 3.4 Optional UI (only if wanted later)

A read-only "SOPs" page that lists `frontend/docs/sops/*.md` and badges the
status from frontmatter — purely cosmetic, no backend change. **Not required** for v1.

---

# Implementation Order

| Step | Work item | Files touched |
|------|-----------|---------------|
| 1 | Logo asset copy (read-only) | `backend/app/assets/kalika-logo.jpeg` |
| 2 | Models + schemas | `models.py`, `schemas.py` |
| 3 | PDF service | `services/pdf_service.py` (new) |
| 4 | Email attachment support | `services/email_service.py` |
| 5 | Quotes router + register | `routers/quotes.py` (new), `main.py` |
| 6 | VCI router + register | `routers/vci.py` (new), `main.py` |
| 7 | Migration script | `scripts/migrate_quotes.py` (new) |
| 8 | Quotes UI + route + nav | `pages/Quotes.jsx` (new), `App.jsx`, `Layout.jsx` |
| 9 | VCI action in Dispatch | `pages/Dispatch.jsx` |
| 10 | SOP docs + tracker | `frontend/docs/sops/*` (new) |
