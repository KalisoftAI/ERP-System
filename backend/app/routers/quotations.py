"""Quotations API - Sales department pre-order documents."""
from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..auth import CurrentUser
from ..config import settings
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import (
    AuditLog, Customer, EmailLog, EmailType, Product, Quotation, QuotationLine,
    QuotationStatus, QuotationType, TermsTemplate, QUOTATION_COMPANY_NAMES,
)
from ..schemas import (
    QuotationCreate, QuotationEmailPreviewOut, QuotationEmailSendIn,
    QuotationEmailHistoryOut, QuotationHistoryOut, QuotationLineIn,
    QuotationListOut, QuotationOut, QuotationRevisionOut, QuotationStatusIn,
    QuotationUpdate, TermsTemplateCreate, TermsTemplateOut, TermsTemplateUpdate,
    UserMiniOut,
)
from ..services.customers import get_or_create_customer
from ..services.email_service import is_valid_email, mail_config_ok, send_email
from ..services.quotation_pdf import build_quotation_pdf_bytes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/quotations", tags=["quotations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _calc_line(line: QuotationLine | QuotationLineIn | dict) -> dict:
    """Compute line amount from quantity x price only. Tax % is stored but not added."""
    def _num(v):
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    qty = _num(getattr(line, "quantity", None) if hasattr(line, "quantity") else line.get("quantity"))
    price = _num(getattr(line, "price", None) if hasattr(line, "price") else line.get("price"))

    basic = round(qty * price, 2)
    return {
        "basic_amount": basic,
        "discount_amount": 0,
        "tax_amount": 0,
        "amount": basic,
    }


def _recalc(quotation: Quotation, lines_data: list[QuotationLineIn]) -> None:
    """Recalculate header totals from the supplied line inputs (tax is display-only)."""
    quotation.subtotal = 0
    quotation.discount_total = 0
    quotation.tax_total = 0
    quotation.total_amount = 0

    # Existing line instances are replaced, so clear them first.
    quotation.lines.clear()

    for ln_in in lines_data:
        computed = _calc_line(ln_in)
        line = QuotationLine(
            product_id=ln_in.product_id,
            item_code=ln_in.item_code or "",
            description=ln_in.description,
            hsn_code=ln_in.hsn_code or "",
            quantity=ln_in.quantity,
            uom=ln_in.uom or "",
            price=ln_in.price,
            lead_time=ln_in.lead_time or "",
            discount_percent=0,
            tax_percent=ln_in.tax_percent if ln_in.tax_percent is not None else None,
            basic_amount=computed["basic_amount"],
            discount_amount=0,
            tax_amount=0,
            amount=computed["amount"],
        )
        quotation.lines.append(line)
        quotation.subtotal += computed["basic_amount"]
        quotation.total_amount += computed["amount"]


def _next_quotation_no(db: Session) -> str:
    """Generate the next sequential quotation number for today."""
    prefix = f"QTN-{date.today():%Y%m%d}-"
    rows = db.execute(
        select(Quotation.quotation_no).where(Quotation.quotation_no.like(f"{prefix}%"))
    ).scalars().all()
    max_seq = 0
    for no in rows:
        suffix = no[len(prefix):]
        try:
            max_seq = max(max_seq, int(suffix))
        except ValueError:
            continue
    return f"{prefix}{max_seq + 1:03d}"


def _resolve_customer(db: Session, data: QuotationCreate | QuotationUpdate) -> Customer | None:
    """Link to an existing customer or create a new master record safely.

    If a customer_id is explicitly supplied, it must exist. An invalid id is
    rejected immediately instead of silently falling back to creating a new
    customer from the supplied name.
    """
    if data.customer_id is not None:
        customer = db.get(Customer, data.customer_id)
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Customer {data.customer_id} not found",
            )
        return customer
    if data.customer_name:
        return get_or_create_customer(
            db, data.customer_name, data.customer_contact or "", data.customer_email or ""
        )
    return None


def _apply_customer_defaults(quotation: Quotation, customer: Customer | None) -> None:
    """Copy customer master fields into the quotation when not already provided."""
    if customer:
        if not quotation.customer_id:
            quotation.customer_id = customer.id
        if not quotation.customer_name:
            quotation.customer_name = customer.name
        if not quotation.customer_contact:
            quotation.customer_contact = customer.phone or ""
        if not quotation.customer_email:
            quotation.customer_email = customer.email or ""
        if not quotation.customer_address:
            quotation.customer_address = customer.address or ""
        if not quotation.customer_gstin:
            quotation.customer_gstin = customer.gstin or ""


DEFAULT_PAYMENT_DAYS = 30


def _default_terms(payment_days: int = DEFAULT_PAYMENT_DAYS) -> str:
    """Standard terms; the payment period is driven by the selected value."""
    return (
        "1. Customer will be billed after Confirm PO only\n"
        f"2. Payment will be {payment_days} days to delivery of service and goods\n"
        "3. Gst tax will be Extra\n"
        "4. Delivery will be free of cost"
    )


def _apply_company_defaults(quotation: Quotation) -> None:
    """Populate company information defaults for a new quotation."""
    if not quotation.company_name:
        quotation.company_name = QUOTATION_COMPANY_NAMES[0]
    if not quotation.company_address:
        quotation.company_address = "Plot No. M-59, MIDC, AHMEDNAGAR"
    if not quotation.company_website:
        quotation.company_website = "www.kalikaindia.com"
    if not quotation.company_phone:
        quotation.company_phone = "+91 9405536016"
    if not quotation.contact_email:
        quotation.contact_email = "info@kalikaindia.com"


def _load_quotation(db: Session, quotation_id: int) -> Quotation:
    """Eager-load a quotation with all relationships needed for detail view."""
    q = db.get(
        Quotation,
        quotation_id,
        options=[
            joinedload(Quotation.customer),
            joinedload(Quotation.created_by),
            joinedload(Quotation.lines).joinedload(QuotationLine.product),
        ],
    )
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Quotation {quotation_id} not found")
    return q


def _build_email_preview(q: Quotation) -> dict:
    """Build a default email preview for a quotation."""
    to = q.customer_email or ""
    company_name = q.company_name or QUOTATION_COMPANY_NAMES[0]
    subject = f"Quotation {q.quotation_no} Rev. {q.revision} - {company_name}"
    message = (
        f"Dear {q.customer_name or 'Customer'},\n\n"
        f"Please find attached our quotation {q.quotation_no} Rev. {q.revision}.\n\n"
        f"Quote Date: {q.quote_date}\n"
        f"Valid Until: {q.valid_until or '—'}\n"
        f"Total Amount: INR {float(q.total_amount or 0):,.2f}\n\n"
        f"Kindly review and confirm at your earliest convenience.\n\n"
        f"Best regards,\n{company_name}"
    )
    return {"to": to, "cc": "", "subject": subject, "message": message}


def _log_email(
    db: Session,
    email_type: EmailType,
    recipient: str,
    cc: str,
    subject: str,
    status_: str,
    error: str,
    quotation_id: int | None = None,
) -> None:
    log = EmailLog(
        email_type=email_type,
        quotation_id=quotation_id,
        recipient=recipient,
        cc=cc,
        subject=subject,
        status=status_,
        error_message=error,
    )
    db.add(log)
    db.flush()


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=list[QuotationListOut])
def list_quotations(
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    search: str = "",
    customer: str = "",
    quote_no: str = "",
    status: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
):
    """List quotations with search and filters. Lazy expiry is applied."""
    query = select(Quotation).options(joinedload(Quotation.customer))

    if search:
        term = f"%{search}%"
        query = query.where(
            (Quotation.customer_name.ilike(term)) | (Quotation.quotation_no.ilike(term))
        )
    if customer:
        query = query.where(Quotation.customer_name.ilike(f"%{customer}%"))
    if quote_no:
        query = query.where(Quotation.quotation_no.ilike(f"%{quote_no}%"))
    if status:
        try:
            query = query.where(Quotation.status == QuotationStatus(status))
        except ValueError:
            pass
    if date_from:
        query = query.where(Quotation.quote_date >= date_from)
    if date_to:
        query = query.where(Quotation.quote_date <= date_to)

    rows = db.scalars(query.order_by(Quotation.quote_date.desc(), Quotation.id.desc())).unique().all()
    expired_any = False
    for r in rows:
        if r.status == QuotationStatus.sent and r.valid_until and r.valid_until < date.today():
            r.status = QuotationStatus.expired
            write_audit(db, user, "STATUS", "quotation", r.id,
                        f"Status auto-changed to Expired (valid until {r.valid_until})")
            expired_any = True
    if expired_any:
        db.commit()
    return [QuotationListOut.model_validate(r).model_dump() for r in rows]


@router.get("/check-number")
def check_quotation_number(
    no: str,
    revision: int = 1,
    exclude_id: int | None = None,
    db: Annotated[Session, Depends(get_db)] = ...,  # noqa: B008
    _: CurrentUser = ...,  # noqa: B008
):
    """Check whether a quotation number + revision is already in use."""
    query = select(Quotation).where(
        (Quotation.quotation_no == no) & (Quotation.revision == revision)
    )
    if exclude_id:
        query = query.where(Quotation.id != exclude_id)
    existing = db.scalar(query)
    return {"available": existing is None}


# ---------------------------------------------------------------------------
# Terms & Conditions templates
# ---------------------------------------------------------------------------
@router.get("/terms-templates", response_model=list[TermsTemplateOut])
def list_terms_templates(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """List all Terms & Conditions templates."""
    rows = db.scalars(select(TermsTemplate).order_by(TermsTemplate.name)).all()
    return [TermsTemplateOut.model_validate(r).model_dump() for r in rows]


@router.post("/terms-templates", response_model=TermsTemplateOut, status_code=status.HTTP_201_CREATED)
def create_terms_template(
    data: TermsTemplateCreate,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Create a reusable Terms & Conditions template."""
    if data.is_default:
        for t in db.scalars(select(TermsTemplate).where(TermsTemplate.is_default == True)).all():
            t.is_default = False
    tmpl = TermsTemplate(name=data.name, content=data.content, is_default=data.is_default)
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return TermsTemplateOut.model_validate(tmpl).model_dump()


@router.put("/terms-templates/{template_id}", response_model=TermsTemplateOut)
def update_terms_template(
    template_id: int,
    data: TermsTemplateUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Update a Terms & Conditions template."""
    tmpl = get_or_404(db, TermsTemplate, template_id)
    if data.is_default:
        for t in db.scalars(select(TermsTemplate).where(TermsTemplate.is_default == True)).all():
            t.is_default = False
    apply_updates(tmpl, data)
    db.commit()
    db.refresh(tmpl)
    return TermsTemplateOut.model_validate(tmpl).model_dump()


@router.delete("/terms-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_terms_template(
    template_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Delete a Terms & Conditions template."""
    tmpl = get_or_404(db, TermsTemplate, template_id)
    db.delete(tmpl)
    db.commit()
    return None


@router.post("", response_model=QuotationOut, status_code=status.HTTP_201_CREATED)
def create_quotation(
    data: QuotationCreate,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Create a new quotation. Defaults to Draft."""
    customer = _resolve_customer(db, data)
    payment_days = data.payment_days or DEFAULT_PAYMENT_DAYS

    q = Quotation(
        quotation_no=data.quotation_no or _next_quotation_no(db),
        revision=1,
        quotation_type=data.quotation_type,
        status=data.status or QuotationStatus.draft,
        quote_date=data.quote_date,
        valid_until=data.valid_until,
        approved_by=data.approved_by,
        terms=data.terms or _default_terms(payment_days),
        payment_days=payment_days,
        created_by_id=user.id,
    )

    # Copy header fields
    for field in [
        "customer_id", "customer_name", "customer_contact", "customer_email",
        "customer_address", "customer_gstin", "company_name", "company_address",
        "company_website", "company_phone", "contact_email",
    ]:
        setattr(q, field, getattr(data, field) or "")

    _apply_customer_defaults(q, customer)
    _apply_company_defaults(q)
    _recalc(q, data.lines)

    db.add(q)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_quotation_no_revision" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="A quotation with this number and revision already exists.",
            )
        logger.warning("Quotation create failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Database error: {exc.orig}")
    db.refresh(q)
    write_audit(db, user, "CREATE", "quotation", q.id,
                f"Created {q.quotation_no} Rev. {q.revision}")
    if q.status == QuotationStatus.sent and q.valid_until and q.valid_until < date.today():
        q.status = QuotationStatus.expired
        write_audit(db, user, "STATUS", "quotation", q.id,
                    f"Status auto-changed to Expired (valid until {q.valid_until})")
        db.commit()
        db.refresh(q)
    return QuotationOut.model_validate(q).model_dump()


@router.get("/{quotation_id}", response_model=QuotationOut)
def get_quotation(
    quotation_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Fetch a single quotation with all lines and lazy expiry applied."""
    q = _load_quotation(db, quotation_id)
    if q.status == QuotationStatus.sent and q.valid_until and q.valid_until < date.today():
        q.status = QuotationStatus.expired
        write_audit(db, user, "STATUS", "quotation", q.id,
                    f"Status auto-changed to Expired (valid until {q.valid_until})")
        db.commit()
        db.refresh(q)
    return QuotationOut.model_validate(q).model_dump()


@router.put("/{quotation_id}", response_model=QuotationOut)
def update_quotation(
    quotation_id: int,
    data: QuotationUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Update a quotation. Drafts are edited in place; Sent/Accepted create a revision."""
    q = _load_quotation(db, quotation_id)

    if q.status in (QuotationStatus.sent, QuotationStatus.accepted):
        # Revision flow: preserve the original and create a new draft revision.
        max_rev = db.scalar(
            select(func.coalesce(func.max(Quotation.revision), 0))
            .where(Quotation.quotation_no == q.quotation_no)
        ) or 0

        new_q = Quotation(
            quotation_no=q.quotation_no,
            revision=max_rev + 1,
            revised_from_id=q.id,
            quotation_type=data.quotation_type,
            status=QuotationStatus.draft,
            quote_date=data.quote_date,
            valid_until=data.valid_until,
            approved_by=data.approved_by,
            terms=data.terms,
            payment_days=data.payment_days if data.payment_days is not None else q.payment_days,
            created_by_id=user.id,
        )
        for field in [
            "customer_id", "customer_name", "customer_contact", "customer_email",
            "customer_address", "customer_gstin", "company_name", "company_address",
            "company_website", "company_phone", "contact_email",
        ]:
            setattr(new_q, field, getattr(data, field) or "")

        _recalc(new_q, data.lines)
        db.add(new_q)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if "uq_quotation_no_revision" in str(exc):
                raise HTTPException(status_code=409, detail="Revision conflict. Please retry.")
            logger.warning("Quotation revision failed: %s", exc)
            raise HTTPException(status_code=400, detail=f"Database error: {exc.orig}")
        db.refresh(new_q)
        write_audit(db, user, "REVISION", "quotation", new_q.id,
                    f"Revision {new_q.revision} created from {q.quotation_no} Rev. {q.revision}")
        return QuotationOut.model_validate(new_q).model_dump()

    # Draft / Rejected / Expired: update in place.
    changes = apply_updates(q, data, exclude={"lines"})

    customer = _resolve_customer(db, data)
    _apply_customer_defaults(q, customer)
    _apply_company_defaults(q)
    _recalc(q, data.lines)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_quotation_no_revision" in str(exc):
            raise HTTPException(status_code=409, detail="Duplicate quotation number and revision.")
        logger.warning("Quotation update failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Database error: {exc.orig}")
    db.refresh(q)
    write_audit(db, user, "UPDATE", "quotation", q.id,
                f"Updated {q.quotation_no} Rev. {q.revision}", changes=changes)
    return QuotationOut.model_validate(q).model_dump()


@router.delete("/{quotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quotation(
    quotation_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Delete a quotation if it has not been converted to an order."""
    q = _load_quotation(db, quotation_id)
    db.delete(q)
    db.commit()
    write_audit(db, user, "DELETE", "quotation", quotation_id,
                f"Deleted {q.quotation_no} Rev. {q.revision}")
    return None


@router.post("/{quotation_id}/duplicate", response_model=QuotationOut)
def duplicate_quotation(
    quotation_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Create a copy of the quotation with a new number and revision 1."""
    q = _load_quotation(db, quotation_id)

    new_q = Quotation(
        quotation_no=_next_quotation_no(db),
        revision=1,
        quotation_type=q.quotation_type,
        status=QuotationStatus.draft,
        customer_id=q.customer_id,
        customer_name=q.customer_name,
        customer_contact=q.customer_contact,
        customer_email=q.customer_email,
        customer_address=q.customer_address,
        customer_gstin=q.customer_gstin,
        company_name=q.company_name,
        company_address=q.company_address,
        company_website=q.company_website,
        company_phone=q.company_phone,
        contact_email=q.contact_email,
        quote_date=date.today(),
        valid_until=q.valid_until,
        approved_by=q.approved_by,
        terms=q.terms,
        payment_days=q.payment_days,
        created_by_id=user.id,
    )
    for ln in q.lines:
        new_q.lines.append(QuotationLine(
            product_id=ln.product_id,
            item_code=ln.item_code,
            description=ln.description,
            hsn_code=ln.hsn_code,
            quantity=ln.quantity,
            uom=ln.uom,
            price=float(ln.price),
            lead_time=ln.lead_time,
            discount_percent=0,
            tax_percent=ln.tax_percent,
            basic_amount=float(ln.basic_amount),
            discount_amount=0,
            tax_amount=0,
            amount=float(ln.amount),
        ))
    new_q.subtotal = float(q.subtotal)
    new_q.discount_total = 0
    new_q.tax_total = 0
    new_q.total_amount = float(q.total_amount)

    db.add(new_q)
    db.commit()
    db.refresh(new_q)
    write_audit(db, user, "DUPLICATE", "quotation", new_q.id,
                f"Duplicated from {q.quotation_no} Rev. {q.revision}")
    return QuotationOut.model_validate(new_q).model_dump()


@router.post("/{quotation_id}/revise", response_model=QuotationOut)
def revise_quotation(
    quotation_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Explicitly create a new revision of an existing quotation."""
    q = _load_quotation(db, quotation_id)
    max_rev = db.scalar(
        select(func.coalesce(func.max(Quotation.revision), 0))
        .where(Quotation.quotation_no == q.quotation_no)
    ) or 0

    new_q = Quotation(
        quotation_no=q.quotation_no,
        revision=max_rev + 1,
        revised_from_id=q.id,
        quotation_type=q.quotation_type,
        status=QuotationStatus.draft,
        customer_id=q.customer_id,
        customer_name=q.customer_name,
        customer_contact=q.customer_contact,
        customer_email=q.customer_email,
        customer_address=q.customer_address,
        customer_gstin=q.customer_gstin,
        company_name=q.company_name,
        company_address=q.company_address,
        company_website=q.company_website,
        company_phone=q.company_phone,
        contact_email=q.contact_email,
        quote_date=q.quote_date,
        valid_until=q.valid_until,
        approved_by=q.approved_by,
        terms=q.terms,
        payment_days=q.payment_days,
        created_by_id=user.id,
    )
    for ln in q.lines:
        new_q.lines.append(QuotationLine(
            product_id=ln.product_id,
            item_code=ln.item_code,
            description=ln.description,
            hsn_code=ln.hsn_code,
            quantity=ln.quantity,
            uom=ln.uom,
            price=float(ln.price),
            lead_time=ln.lead_time,
            discount_percent=0,
            tax_percent=ln.tax_percent,
            basic_amount=float(ln.basic_amount),
            discount_amount=0,
            tax_amount=0,
            amount=float(ln.amount),
        ))
    new_q.subtotal = float(q.subtotal)
    new_q.discount_total = 0
    new_q.tax_total = 0
    new_q.total_amount = float(q.total_amount)

    db.add(new_q)
    db.commit()
    db.refresh(new_q)
    write_audit(db, user, "REVISION", "quotation", new_q.id,
                f"Revision {new_q.revision} created from {q.quotation_no} Rev. {q.revision}")
    return QuotationOut.model_validate(new_q).model_dump()


@router.post("/{quotation_id}/status", response_model=QuotationOut)
def change_status(
    quotation_id: int,
    body: QuotationStatusIn,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Manually change quotation status (e.g. Mark Sent / Accepted / Rejected)."""
    q = _load_quotation(db, quotation_id)
    old = q.status.value if q.status else ""
    q.status = body.status
    db.commit()
    db.refresh(q)
    write_audit(db, user, "STATUS", "quotation", q.id,
                f"Status changed from {old} to {q.status.value}",
                changes={"status": {"old": old, "new": q.status.value}})
    return QuotationOut.model_validate(q).model_dump()


@router.get("/{quotation_id}/history", response_model=QuotationHistoryOut)
def quotation_history(
    quotation_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Return the full revision chain plus audit events for a quotation."""
    q = _load_quotation(db, quotation_id)
    chain = db.scalars(
        select(Quotation)
        .where(Quotation.quotation_no == q.quotation_no)
        .options(joinedload(Quotation.created_by))
        .order_by(Quotation.revision.asc())
    ).unique().all()

    revisions = [
        QuotationRevisionOut(
            id=r.id,
            quotation_no=r.quotation_no,
            revision=r.revision,
            status=r.status,
            quote_date=r.quote_date,
            total_amount=float(r.total_amount),
            created_at=r.created_at,
            created_by=UserMiniOut.model_validate(r.created_by).model_dump() if r.created_by else None,
        ).model_dump()
        for r in chain
    ]

    audit_rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity == "quotation")
        .where(AuditLog.entity_id.in_([r.id for r in chain]))
        .order_by(AuditLog.created_at.desc())
    ).all()

    audit = [
        {
            "id": a.id,
            "action": a.action,
            "entity_id": a.entity_id,
            "details": a.details,
            "created_at": a.created_at,
            "created_by": a.user_id,
        }
        for a in audit_rows
    ]

    return {"revisions": revisions, "audit": audit}


# ---------------------------------------------------------------------------
# Email endpoints
# ---------------------------------------------------------------------------
@router.get("/{quotation_id}/email-preview", response_model=QuotationEmailPreviewOut)
def email_preview(
    quotation_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Return a default email subject/body for the quotation."""
    q = _load_quotation(db, quotation_id)
    return QuotationEmailPreviewOut(**_build_email_preview(q)).model_dump()


@router.post("/{quotation_id}/send-email", response_model=dict)
def send_quotation_email(
    quotation_id: int,
    body: QuotationEmailSendIn,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
):
    """Send the quotation PDF by email with an editable message."""
    q = _load_quotation(db, quotation_id)

    if not is_valid_email(body.to):
        raise HTTPException(status_code=400, detail="Invalid recipient email address.")

    ok, err = mail_config_ok()
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    attachments = []
    if body.attach_pdf:
        pdf_bytes = build_quotation_pdf_bytes(q)
        safe_no = "".join(c for c in q.quotation_no if c.isalnum() or c in "-_").strip() or str(q.id)
        attachments.append((f"Quotation_{safe_no}_Rev{q.revision}.pdf", pdf_bytes, "application/pdf"))

    success, error = send_email(
        to=body.to,
        subject=body.subject,
        body=body.message,
        cc=body.cc or None,
        attachments=attachments,
    )

    status_ = "sent" if success else "failed"
    _log_email(db, EmailType.quotation, body.to, body.cc or "", body.subject,
               status_, error, quotation_id=q.id)
    db.commit()

    if not success:
        raise HTTPException(status_code=502, detail=error or "Email delivery failed")

    write_audit(db, user, "SEND_EMAIL", "quotation", q.id,
                f"Email sent to {body.to} (subject: {body.subject})")
    return {"success": True, "message": "Email sent successfully"}


@router.get("/{quotation_id}/email-history", response_model=list[QuotationEmailHistoryOut])
def email_history(
    quotation_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Return the email send history for a quotation."""
    rows = db.scalars(
        select(EmailLog)
        .where(EmailLog.quotation_id == quotation_id)
        .where(EmailLog.email_type == EmailType.quotation)
        .order_by(EmailLog.sent_at.desc())
    ).all()
    return [QuotationEmailHistoryOut.model_validate(r).model_dump() for r in rows]


