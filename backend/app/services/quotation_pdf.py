"""Premium, multi-page PDF builder for customer quotations.

Reused by the reports router (download) and the quotations router (email
attachment). Keeps the visual design consistent across every channel.
"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ..assets.images import LOGO_PNG_B64
from ..config import BASE_DIR
from ..models import Quotation
from .gcs import get_stamp_bytes

logger = logging.getLogger(__name__)


def _b64_image_reader(b64_string: str) -> ImageReader:
    """Create a ReportLab ImageReader from a base64-encoded PNG."""
    return ImageReader(io.BytesIO(base64.b64decode(b64_string)))


def _asset_path(rel_path: str) -> Path | None:
    """Resolve a public asset. Backend-bundled assets are checked first so the
    PDF builder works even when frontend/dist is missing or in a different
    location in the deployed container."""
    module_dir = Path(__file__).resolve().parent
    candidates = [
        # Backend-bundled copy (most reliable in production).
        module_dir / "assets" / rel_path,
        module_dir / "assets" / Path(rel_path).name,
        # Frontend build / public folders (local dev and full-stack builds).
        BASE_DIR / "frontend" / "dist" / rel_path,
        BASE_DIR / "frontend" / "public" / rel_path,
        BASE_DIR / "frontend" / "dist" / "assets" / Path(rel_path).name,
        BASE_DIR / "frontend" / "public" / "assets" / Path(rel_path).name,
    ]
    for p in candidates:
        if p.exists():
            logger.info("PDF asset resolved: %s -> %s", rel_path, p)
            return p
    logger.warning("PDF asset not found: %s (tried: %s)", rel_path, [str(c) for c in candidates])
    return None


def _fmt_num(v) -> str:
    """Format a numeric value with two decimals; blank for None."""
    if v is None:
        return ""
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_tax(v) -> str:
    """Display the entered tax %; preserve blank when not set."""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):.2f}%"
    except (TypeError, ValueError):
        return str(v)


def _default_company_values(q: Quotation) -> dict:
    """Return company details, falling back to known Kalika defaults only when
    the quotation itself does not contain an override."""
    return {
        "name": q.company_name or "KALIKA ENTERPRISES",
        "address": q.company_address or "Plot No. M-59, MIDC, AHMEDNAGAR",
        "website": q.company_website or "www.kalikaindia.com",
        "phone": q.company_phone or "+91 9405536016",
        "email": q.contact_email or "info@kalikaindia.com",
    }


def _header_footer(canvas, doc, company: dict, q: Quotation):
    """Draw a compact corporate header on every page and a subtle footer."""
    canvas.saveState()
    width, height = A4

    # Logo: prefer embedded base64 asset so it works in any deployment.
    try:
        canvas.drawImage(
            _b64_image_reader(LOGO_PNG_B64), 16 * mm, height - 26 * mm,
            width=30 * mm, height=14 * mm, preserveAspectRatio=True, mask="auto",
        )
    except Exception as exc:
        logger.warning("Failed to draw embedded logo: %s", exc)
        logo_path = _asset_path("Kalika_logo.png")
        if logo_path:
            try:
                canvas.drawImage(
                    str(logo_path), 16 * mm, height - 26 * mm,
                    width=30 * mm, height=14 * mm, preserveAspectRatio=True, mask="auto",
                )
            except Exception as exc2:
                logger.warning("Failed to draw logo in PDF header: %s", exc2)

    # Company info block
    canvas.setFont("Helvetica-Bold", 12)
    canvas.setFillColor(colors.HexColor("#1e3a8a"))
    canvas.drawRightString(width - 16 * mm, height - 16 * mm, company["name"])

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#475569"))
    y = height - 20.5 * mm
    for line in [
        company["address"],
        f"Phone: {company['phone']}  |  Email: {company['email']}  |  Web: {company['website']}",
    ]:
        canvas.drawRightString(width - 16 * mm, y, line)
        y -= 4 * mm

    # Decorative accent line
    canvas.setStrokeColor(colors.HexColor("#f59e0b"))
    canvas.setLineWidth(1)
    canvas.line(16 * mm, height - 30 * mm, width - 16 * mm, height - 30 * mm)

    # Footer
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawCentredString(
        width / 2, 12 * mm,
        f"Quotation {q.quotation_no} Rev. {q.revision}  |  {company['name']}",
    )
    canvas.drawRightString(width - 16 * mm, 12 * mm, f"Page {doc.page}")

    canvas.restoreState()


def build_quotation_pdf_bytes(q: Quotation) -> bytes:
    """Generate a professional, print-ready, multi-page quotation PDF."""
    buf = io.BytesIO()
    usable_width = A4[0] - 32 * mm  # 16 mm margins on each side
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=34 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "QuotationTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1e3a8a"),
        spaceAfter=4,
        alignment=1,  # center
        leading=20,
    )
    style_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=colors.HexColor("#1e3a8a"),
        spaceAfter=3,
    )
    style_normal = ParagraphStyle(
        "QuotationNormal",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    style_small = ParagraphStyle(
        "QuotationSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#475569"),
    )
    style_wrap = ParagraphStyle(
        "WrapCell",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
        wordWrap="CJK",
    )
    style_sign = ParagraphStyle(
        "Signatory",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        alignment=1,  # center
        textColor=colors.HexColor("#1e293b"),
    )
    style_sign_small = ParagraphStyle(
        "SignatorySmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        alignment=1,  # center
        textColor=colors.HexColor("#475569"),
    )

    company = _default_company_values(q)
    story = []

    # Document title
    story.append(Paragraph("QUOTATION", style_title))

    # Metadata grid
    meta_data = [
        ["Quote No.", f"{q.quotation_no} Rev. {q.revision}", "Quote Date", str(q.quote_date or "—")],
        ["Valid Until", str(q.valid_until or "—"), "Customer ID", "167428"],
        ["Approved By", q.approved_by or "—", "Contact Email", company["email"]],
    ]
    meta_table = Table(meta_data, colWidths=[26 * mm, 63 * mm, 26 * mm, 63 * mm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#334155")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6))

    # Customer block
    story.append(Paragraph("Billed To", style_heading))
    customer_lines = [
        f"<b>{q.customer_name or '—'}</b>",
        q.customer_address or "",
        f"Contact: {q.customer_contact or '—'}",
        f"Email: {q.customer_email or '—'}",
    ]
    if q.customer_gstin:
        customer_lines.append(f"GSTIN: {q.customer_gstin}")
    story.append(Paragraph("<br/>".join(filter(None, customer_lines)), style_normal))
    story.append(Spacer(1, 8))

    # Line items
    story.append(Paragraph("Line Items", style_heading))
    headers = ["#", "Description", "HSN", "Qty", "UOM", "Price (INR)", "Lead Time", "Amount", "Tax"]
    rows = []
    for idx, ln in enumerate(q.lines, start=1):
        desc = Paragraph(ln.description or "—", style_wrap)
        rows.append([
            str(idx),
            desc,
            ln.hsn_code or "—",
            _fmt_num(ln.quantity),
            ln.uom or "—",
            _fmt_num(ln.price),
            ln.lead_time or "—",
            _fmt_num(ln.amount),
            _fmt_tax(ln.tax_percent),
        ])

    if rows:
        line_table = Table(
            [headers] + rows,
            repeatRows=1,
            colWidths=[
                8 * mm, 52 * mm, 17 * mm, 12 * mm, 12 * mm,
                24 * mm, 16 * mm, 24 * mm, 13 * mm,
            ],
        )
        line_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("FONTSIZE", (0, 1), (-1, -1), 7),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (2, -1), "LEFT"),
            ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.75, colors.HexColor("#94a3b8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        story.append(line_table)
    else:
        story.append(Paragraph("No line items.", style_normal))

    # Totals immediately after the line-item table. Tax % is display-only and
    # discount is not used, so only Subtotal and Total Amount are shown.
    story.append(Spacer(1, 6))
    total_value = float(q.total_amount or 0)
    subtotal = float(q.subtotal or 0)

    totals_data = [
        ["Subtotal", _fmt_num(subtotal)],
        ["Total Amount (INR)", _fmt_num(total_value)],
    ]
    totals_table = Table(totals_data, colWidths=[45 * mm, 30 * mm])
    totals_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (0, -1), (1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (1, -1), colors.HexColor("#1e3a8a")),
        ("TEXTCOLOR", (0, -1), (1, -1), colors.whitesmoke),
    ]))

    # Right-align the totals block so it sits cleanly at the end of the table
    totals_wrapper = Table([["", totals_table]], colWidths=[usable_width - 75 * mm, 75 * mm])
    totals_wrapper.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(totals_wrapper)

    # Terms & Conditions
    if q.terms:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Terms & Conditions", style_heading))
        story.append(Paragraph(q.terms.replace("\n", "<br/>"), style_small))

    # Authorized signatory block: stamp with text directly below it
    stamp_img = None
    stamp_bytes = get_stamp_bytes()
    if stamp_bytes:
        try:
            with PILImage.open(io.BytesIO(stamp_bytes)) as probe:
                img_w, img_h = probe.size
            # Fixed width, aspect-preserving height (never stretch the stamp).
            stamp_w = 32 * mm
            stamp_img = Image(io.BytesIO(stamp_bytes), width=stamp_w,
                              height=stamp_w * img_h / img_w)
        except Exception as exc:
            logger.warning("Failed to load company stamp for PDF: %s", exc)

    signatory_inner = Table(
        [
            [stamp_img or ""],
            [Paragraph("<b>Authorized Signatory</b>", style_sign)],
            [Paragraph(f"For {company['name']}", style_sign_small)],
        ],
        colWidths=[55 * mm],
    )
    signatory_inner.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    signatory_block = Table(
        [["", signatory_inner]],
        colWidths=[usable_width - 55 * mm, 55 * mm],
    )
    signatory_block.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))

    story.append(Spacer(1, 8))
    story.append(KeepTogether(signatory_block))

    # Contact note
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        f"If you have any questions about this price quote, please contact {company['email']}",
        style_small,
    ))

    doc.build(
        story,
        onFirstPage=lambda c, d: _header_footer(c, d, company, q),
        onLaterPages=lambda c, d: _header_footer(c, d, company, q),
    )
    pdf = buf.getvalue()
    buf.close()
    return pdf
