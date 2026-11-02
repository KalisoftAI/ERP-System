"""Professional, print-ready PDF builder for Purchase Requisition Notes.

Mirrors the design conventions of ``quotation_pdf`` (A4, navy-blue corporate
header, bilingual-safe wrapping, repeat table headers, page numbers). Every
value comes from the PRN record — nothing is hard-coded sample data. The PRN's
inventory stock snapshot and any PRN-specific stock override are shown as two
distinct figures so a printed sheet can never be mistaken for a stock movement.
"""
from __future__ import annotations

import base64
import io
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ..assets.images import LOGO_PNG_B64
from ..models import PRN

logger = logging.getLogger(__name__)

# Verified company details already configured in the project (see
# quotation_pdf._default_company_values). Used only when the PRN has no
# company_name of its own. No details are invented here.
_COMPANY = {
    "name": "KALIKA ENTERPRISES",
    "address": "Plot No. M-59, MIDC, AHMEDNAGAR",
    "website": "www.kalikaindia.com",
    "phone": "+91 9405536016",
    "email": "info@kalikaindia.com",
}
_NAVY = colors.HexColor("#1e3a8a")
_SLATE = colors.HexColor("#334155")
_GRID = colors.HexColor("#94a3b8")


def _logo_reader() -> ImageReader | None:
    try:
        return ImageReader(io.BytesIO(base64.b64decode(LOGO_PNG_B64)))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load embedded PRN logo: %s", exc)
        return None


def _fmt_num(v) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _stock_text(ln) -> str:
    """Single Stock cell: override takes precedence, labelled; a blank
    snapshot is shown as 'Unknown' (never assumed to be zero). The inventory
    location is shown where the stock snapshot was read from."""
    loc = ln.plant.name if ln.plant else ("Main Store" if ln.material_id else "")
    if ln.stock_override is not None:
        return f"{_fmt_num(ln.stock_override)}<br/><font size=6 color='#b45309'>PRN override</font>"
    if ln.available_stock is not None:
        label = f"Inv. stock{(' · ' + loc) if loc else ''}"
        return f"{_fmt_num(ln.available_stock)}<br/><font size=6 color='#64748b'>{label}</font>"
    return f"Unknown{(' (' + loc + ')') if loc else ''}"


def _header_footer(canvas, doc, company: dict, prn: PRN):
    canvas.saveState()
    width, height = A4

    logo = _logo_reader()
    if logo is not None:
        try:
            canvas.drawImage(logo, 16 * mm, height - 26 * mm,
                             width=30 * mm, height=14 * mm,
                             preserveAspectRatio=True, mask="auto")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to draw PRN logo: %s", exc)

    canvas.setFont("Helvetica-Bold", 12)
    canvas.setFillColor(_NAVY)
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

    canvas.setStrokeColor(colors.HexColor("#f59e0b"))
    canvas.setLineWidth(1)
    canvas.line(16 * mm, height - 30 * mm, width - 16 * mm, height - 30 * mm)

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawCentredString(width / 2, 12 * mm,
                             f"{prn.prn_number or 'PRN'}  |  {company['name']}  |  Page {doc.page}")
    canvas.restoreState()


def build_prn_pdf_bytes(prn: PRN) -> bytes:
    buf = io.BytesIO()
    usable_width = A4[0] - 32 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=34 * mm, bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "PrnTitle", parent=styles["Heading1"], fontSize=15, leading=19,
        textColor=_NAVY, spaceAfter=2, alignment=1,
    )
    style_title_sub = ParagraphStyle(
        "PrnTitleSub", parent=styles["Normal"], fontSize=9, leading=11,
        textColor=colors.HexColor("#475569"), alignment=1, spaceAfter=6,
    )
    style_heading = ParagraphStyle(
        "PrnHeading", parent=styles["Heading3"], fontName="Helvetica-Bold",
        fontSize=10, textColor=_NAVY, spaceAfter=3, spaceBefore=6,
    )
    style_normal = ParagraphStyle(
        "PrnNormal", parent=styles["Normal"], fontSize=9, leading=12, textColor=_SLATE,
    )
    style_small = ParagraphStyle(
        "PrnSmall", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=colors.HexColor("#475569"),
    )
    style_wrap = ParagraphStyle(
        "PrnWrap", parent=styles["Normal"], fontSize=7, leading=9, wordWrap="CJK",
    )
    style_cell = ParagraphStyle(
        "PrnCell", parent=styles["Normal"], fontSize=7, leading=9, wordWrap="CJK",
    )
    style_sign = ParagraphStyle(
        "PrnSign", parent=styles["Normal"], fontSize=8, leading=11,
        alignment=1, textColor=colors.HexColor("#1e293b"),
    )

    company = dict(_COMPANY)
    if prn.company_name:
        company["name"] = prn.company_name

    story = []
    story.append(Paragraph("PURCHASE REQUISITION NOTE (PRN)", style_title))
    story.append(Paragraph(
        f"PRN No. {prn.prn_number or '—'}  ·  Date: {prn.prn_date or '—'}",
        style_title_sub,
    ))

    # --- Section 1: request information ------------------------------------
    story.append(Paragraph("Request Information", style_heading))
    meta_data = [
        ["Department", prn.department or "—", "Requested By", prn.requested_by_name or "—"],
        ["Required By Date", str(prn.required_by_date or "—"),
         "Requirement Type", prn.requirement_type or "—"],
        ["Priority", prn.priority or "—", "Department Head", prn.department_head or "—"],
    ]
    meta_table = Table(meta_data, colWidths=[30 * mm, 59 * mm, 32 * mm, 57 * mm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, -1), _SLATE),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 4))

    # --- Section 2: material requirement table -----------------------------
    story.append(Paragraph("Material Requirements", style_heading))
    style_th = ParagraphStyle(
        "PrnTh", parent=styles["Normal"], fontSize=7.5, leading=9,
        fontName="Helvetica-Bold", textColor=colors.whitesmoke, wordWrap="CJK",
    )
    style_qty = ParagraphStyle(
        "PrnQty", parent=styles["Normal"], fontSize=7.5, leading=9, alignment=2,
    )
    headers = [
        Paragraph("Sr.<br/>No.", style_th),
        Paragraph("Item Code", style_th),
        Paragraph("Material Description", style_th),
        Paragraph("UOM", style_th),
        Paragraph("Required<br/>Quantity", style_th),
        Paragraph("Stock", style_th),
        Paragraph("Purpose / Remarks", style_th),
    ]
    rows = []
    for idx, ln in enumerate(prn.lines, start=1):
        desc = (ln.description or "—").replace("\n", "<br/>")
        rows.append([
            Paragraph(str(idx), style_cell),
            Paragraph((ln.material_code or "—").replace("\n", "<br/>"), style_cell),
            Paragraph(desc, style_wrap),
            Paragraph(ln.uom or "—", style_cell),
            Paragraph(_fmt_num(ln.quantity) or "—", style_qty),
            Paragraph(_stock_text(ln), style_cell),
            Paragraph((ln.remarks or "—").replace("\n", "<br/>"), style_wrap),
        ])
    if rows:
        line_table = Table(
            [headers] + rows, repeatRows=1,
            colWidths=[9 * mm, 22 * mm, 70 * mm, 12 * mm, 18 * mm, 23 * mm, 24 * mm],
        )
        line_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("ALIGN", (4, 0), (4, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.75, _GRID),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        story.append(line_table)
    else:
        story.append(Paragraph("No material lines.", style_normal))

    # --- Section 3: purpose ------------------------------------------------
    if prn.purpose:
        story.append(Spacer(1, 5))
        story.append(Paragraph("Purpose of Requisition", style_heading))
        story.append(Paragraph(prn.purpose.replace("\n", "<br/>"), style_normal))

    # --- attachments -------------------------------------------------------
    attachments = [ln for ln in prn.lines if ln.attachment_name]
    if attachments:
        story.append(Spacer(1, 5))
        story.append(Paragraph("Attachments", style_heading))
        for ln in attachments:
            label = ln.material_code or ln.description or "Line"
            story.append(Paragraph(f"• {label}: {ln.attachment_name}", style_small))

    # --- Section 4: verification and approval ------------------------------
    # Actual names/dates only; blank lines are signature space, never invented.
    def sign_cell(role: str, name: str = "") -> Paragraph:
        body = f"<b>{role}</b>"
        if name:
            body += f"<br/><font size=7 color='#475569'>{name}</font>"
        return Paragraph(body, style_sign)

    sign_data = [[
        sign_cell("Requested By", prn.requested_by_name or ""),
        sign_cell("Checked By (Store)", prn.checked_by_name or ""),
        sign_cell("Department Head", prn.department_head or ""),
        sign_cell("Approved By", prn.approved_by_name or ""),
    ], [
        Paragraph("<br/><br/>Date: ____________", style_sign),
        Paragraph("<br/><br/>Date: ____________", style_sign),
        Paragraph("<br/><br/>Date: ____________", style_sign),
        Paragraph(f"<br/><br/>Date: {prn.approved_at.strftime('%d-%m-%Y') if prn.approved_at else '____________'}", style_sign),
    ]]
    sign_table = Table(sign_data, colWidths=[usable_width / 4] * 4)
    sign_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Verification and Approval", style_heading))
    story.append(KeepTogether(sign_table))

    # --- Section 5: purchase department remarks ----------------------------
    story.append(Spacer(1, 5))
    story.append(Paragraph("Purchase Department Remarks", style_heading))
    remarks_body = prn.purchase_remarks.replace("\n", "<br/>") if prn.purchase_remarks else "&nbsp;"
    remarks_table = Table([[Paragraph(remarks_body, style_normal)]],
                          colWidths=[usable_width], rowHeights=[14 * mm])
    remarks_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(remarks_table)

    doc.build(
        story,
        onFirstPage=lambda c, d: _header_footer(c, d, company, prn),
        onLaterPages=lambda c, d: _header_footer(c, d, company, prn),
    )
    pdf = buf.getvalue()
    buf.close()
    return pdf
