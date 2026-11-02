"""Multi-page PDF builder for employee list exports.

Deliberately small: a titled table with a repeating header row, a generation
date and page numbers. Cells wrap so long names/emails stay readable. Reuses
the same ReportLab stack the quotation PDF uses.
"""
from __future__ import annotations

import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


def build_employees_pdf_bytes(
    header_labels: list[str],
    rows: list[list],
    *,
    title: str = "Employee List",
    subtitle: str = "",
    generated_on: date | None = None,
) -> bytes:
    buf = io.BytesIO()
    page = landscape(A4)
    generated_on = generated_on or date.today()
    doc = SimpleDocTemplate(
        buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=16 * mm, bottomMargin=14 * mm, title=title,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "EmpTitle", parent=styles["Heading1"], fontSize=15,
        textColor=colors.HexColor("#1e3a8a"), alignment=0, spaceAfter=2, leading=18,
    )
    style_meta = ParagraphStyle(
        "EmpMeta", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor("#475569"), spaceAfter=1,
    )
    style_cell = ParagraphStyle(
        "EmpCell", parent=styles["Normal"], fontSize=7, leading=8.5,
        textColor=colors.HexColor("#334155"), wordWrap="CJK",
    )
    style_head = ParagraphStyle(
        "EmpHead", parent=styles["Normal"], fontSize=7.5, leading=9,
        textColor=colors.whitesmoke, fontName="Helvetica-Bold",
    )

    story = [Paragraph(escape(title), style_title)]
    if subtitle:
        story.append(Paragraph(escape(subtitle), style_meta))
    story.append(Paragraph(f"Generated on {generated_on.isoformat()}", style_meta))
    story.append(Spacer(1, 6))

    usable = page[0] - 24 * mm
    ncol = max(len(header_labels), 1)
    col_widths = [usable / ncol] * ncol

    def _wrap(v) -> Paragraph:
        return Paragraph(escape("" if v is None else str(v)), style_cell)

    data = [[Paragraph(escape(h), style_head) for h in header_labels]]
    for row in rows:
        data.append([_wrap(c) for c in row])

    if len(data) == 1:
        data.append([_wrap("No records")] + [""] * (ncol - 1))

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(table)

    def _footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        w, _ = page
        canvas.drawRightString(w - 12 * mm, 8 * mm, f"Page {d.page}")
        canvas.drawString(12 * mm, 8 * mm, f"Generated {generated_on.isoformat()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def build_employee_detail_pdf_bytes(
    data: dict,
    *,
    generated_on: date | None = None,
) -> bytes:
    """Single-employee detail sheet: a title block plus labelled sections.

    `data` is a serialized employee dict (already masked for non-admins by the
    router), so this builder never needs to know about roles.
    """
    buf = io.BytesIO()
    page = A4
    generated_on = generated_on or date.today()
    doc = SimpleDocTemplate(
        buf, pagesize=page, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=14 * mm, title="Employee Details",
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "EmpDetailTitle", parent=styles["Heading1"], fontSize=17,
        textColor=colors.HexColor("#1e3a8a"), spaceAfter=2, leading=21,
    )
    style_meta = ParagraphStyle(
        "EmpDetailMeta", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor("#475569"), spaceAfter=1,
    )
    style_section = ParagraphStyle(
        "EmpDetailSection", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#1e3a8a"), fontName="Helvetica-Bold",
        spaceBefore=8, spaceAfter=4,
    )
    style_label = ParagraphStyle(
        "EmpDetailLabel", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor("#64748b"),
    )
    style_value = ParagraphStyle(
        "EmpDetailValue", parent=styles["Normal"], fontSize=9.5,
        textColor=colors.HexColor("#0f172a"), wordWrap="CJK",
    )

    def _value(v) -> Paragraph:
        text = "" if v is None or v == "" else str(v)
        return Paragraph(escape(text or "—"), style_value)

    def _label(text: str) -> Paragraph:
        return Paragraph(escape(text), style_label)

    def _section_table(rows) -> Table:
        data_rows = [[_label(label), _value(value)] for label, value in rows]
        label_w = 42 * mm
        table = Table(data_rows, colWidths=[label_w, page[0] - 36 * mm - label_w])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#eef2f7")),
        ]))
        return table

    story = [Paragraph(escape(str(data.get("name") or "Employee")), style_title)]
    story.append(Paragraph(
        f"Employee Code: {escape(str(data.get('employee_code') or '-'))}", style_meta))
    story.append(Paragraph(f"Generated on {generated_on.isoformat()}", style_meta))
    story.append(Spacer(1, 6))

    sections = [
        ("Employment", [
            ("Employee ID", data.get("employee_code")),
            ("Employee Name", data.get("name")),
            ("Department", data.get("department")),
            ("Designation", data.get("designation")),
            ("Joining Date", data.get("joining_date")),
            ("Employment Status", data.get("status")),
            ("Job Leave Date", data.get("job_leave_date")),
        ]),
        ("Contact", [
            ("Mobile Number", data.get("mobile")),
            ("Email", data.get("email")),
        ]),
        ("Personal & Bank Details", [
            ("Aadhaar Number", data.get("aadhaar_number")),
            ("PAN Number", data.get("pan_number")),
            ("Bank Account Number", data.get("bank_account_number")),
            ("IFSC Code", data.get("ifsc_code")),
            ("Bank Name", data.get("bank_name")),
            ("Branch Name", data.get("branch_name")),
        ]),
        ("PF / UAN Details", [
            ("PF Applicable", data.get("pf_applicable")),
            ("UAN", data.get("uan")),
            ("PF Member ID", data.get("pf_member_id")),
            ("PF Joining Date", data.get("pf_joining_date")),
            ("PF Exit Date", data.get("pf_exit_date")),
            ("Previous PF Membership", data.get("previous_pf_membership")),
        ]),
        ("ESIC Details", [
            ("ESIC Applicable", data.get("esic_applicable")),
            ("ESIC IP Number", data.get("esic_ip_number")),
            ("ESIC Joining Date", data.get("esic_joining_date")),
            ("ESIC Exit Date", data.get("esic_exit_date")),
            ("Registration Status", data.get("esic_registration_status")),
        ]),
        ("Verification & Record", [
            ("Verification Status", data.get("verification_status")),
            ("Verified By", data.get("verified_by")),
            ("Verification Date", data.get("verification_date")),
            ("Remarks", data.get("remarks")),
            ("Supporting Document Reference", data.get("supporting_document_ref")),
        ]),
    ]
    for title, rows in sections:
        story.append(Paragraph(escape(title), style_section))
        story.append(_section_table(rows))

    def _footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        w, _ = page
        canvas.drawRightString(w - 18 * mm, 8 * mm, f"Page {d.page}")
        canvas.drawString(18 * mm, 8 * mm, "Employee Details")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    pdf = buf.getvalue()
    buf.close()
    return pdf
