from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# Set default font to Consolas for ASCII diagram alignment
style = doc.styles['Normal']
font = style.font
font.name = 'Consolas'
font.size = Pt(10)

# Title
title = doc.add_heading('Kalika ERP — Recent Changes (September–October 2026)', level=0)

# ============================================================
# 1. Quotation Management Module
# ============================================================
doc.add_heading('1. Quotation Management Module (New)', level=1)

p = doc.add_paragraph()
p.add_run('Overview:').bold = True
doc.add_paragraph(
    'The Quotation Management module is a complete end-to-end feature for generating, managing, '
    'and delivering customer quotations. Added across commits a0990b5 through ba5269a.'
)

p = doc.add_paragraph()
p.add_run('Quotation Lifecycle Diagram:').bold = True
diag1 = doc.add_paragraph()
diag1.paragraph_format.space_after = Pt(4)
run = diag1.add_run(
    '                        send               accept\n'
    '  +---------+  --------->   +------+  --------->   +----------+\n'
    '  |  DRAFT  |             | SENT |             | ACCEPTED |\n'
    '  +---------+             +------+             +----------+\n'
    '       ^                    |  |\n'
    '       |                    |  +----- reject ---> +----------+\n'
    '       |   revise           |                       | REJECTED |\n'
    '       |  (revision + 1)    |  validity date passed +----------+\n'
    '       |                    v\n'
    '       |                +----------+\n'
    '       +--------------  | EXPIRED  |\n'
    '                       +----------+'
)
run.font.name = 'Consolas'
run.font.size = Pt(9)

doc.add_paragraph(
    'Revise is available from SENT / ACCEPTED / REJECTED / EXPIRED. '
    'It creates a new DRAFT keeping the same quotation_no and '
    'incrementing the revision number (unique constraint: quotation_no + revision).'
)

p = doc.add_paragraph()
p.add_run('Quotation Numbering & Revision Diagram:').bold = True
diag2 = doc.add_paragraph()
run2 = diag2.add_run(
    '  QTN-20261004-001  Rev 1  (Draft -> Sent -> ...)\n'
    '         |\n'
    '         |  revise\n'
    '         v\n'
    '  QTN-20261004-001  Rev 2  (new Draft, revised_from -> Rev 1)\n'
    '         |\n'
    '         |  revise\n'
    '         v\n'
    '  QTN-20261004-001  Rev 3  ...'
)
run2.font.name = 'Consolas'
run2.font.size = Pt(9)

doc.add_paragraph(
    'Quotation number format: QTN-YYYYMMDD-### (e.g., QTN-20261004-001). '
    'Revision increment creates a new DRAFT with same quotation_no and revision + 1.'
)

p = doc.add_paragraph()
p.add_run('Module Architecture Diagram:').bold = True
diag3 = doc.add_paragraph()
run3 = diag3.add_run(
    ' +------------------------+      REST / JSON      +---------------------------+\n'
    ' |  React Frontend        | ---------------------> |  FastAPI Backend          |\n'
    ' |  /quotations page      | <--------------------- |  quotations router        |\n'
    ' |  (Quotations.jsx)      |                        +--------------+------------+\n'
    ' +------------------------+               |                                    |\n'
    '                                                                 v                                    v\n'
    '   +---------------------------------------------------+-----------------------------+\n'
    '   |                                         |                             |\n'
    '   v                                         v                             v\n'
    '   +---------------------+            +---------------------+         +---------------------+\n'
    '   |  PostgreSQL         |            |  quotation_pdf.py   |         |  email_service.py   |\n'
    '   |  quotations         |            |  ReportLab A4 PDF   |         |  SMTP (Gmail)       |\n'
    '   |  quotation_lines    |            |  Kalika logo+stamp  |         |  preview / send     |\n'
    '   |  terms_templates    |            |  multi-page layout  |         |  email history log  |\n'
    '   +---------------------+            +---------------------+         +---------------------+'
)
run3.font.name = 'Consolas'
run3.font.size = Pt(8)

doc.add_paragraph(
    'Frontend page at /quotations (Quotations.jsx). API at /quotations with 21 endpoints '
    '(list, check-number, create, get, update, delete, duplicate, revise, status, '
    'history, email-preview, send-email, email-history, terms-templates CRUD).'
)

p = doc.add_paragraph()
p.add_run('Recent Fixes (Quotation Module Stability):').bold = True
doc.add_paragraph('Customer ID resolution (f57ab90)')
doc.add_paragraph('PDF download fix (1cec353 / 8717d66)')
doc.add_paragraph('Refresh page issue (ba5269a)')

# ============================================================
# 2. Purchase GST & Discount Calculations
# ============================================================
doc.add_heading('2. Purchase GST & Discount Calculations', level=1)

p = doc.add_paragraph()
p.add_run('Line Total Formula:').bold = True
doc.add_paragraph(
    'basic_amount  = quantity x rate\n'
    'discount_amount = round(basic_amount x discount_percent / 100, 2)\n'
    'taxable_amount  = basic_amount - discount_amount\n'
    'gst_amount      = round(taxable_amount x tax_percent / 100, 2)\n'
    'line_total      = round(taxable_amount + gst_amount, 2)'
)

p = doc.add_paragraph()
p.add_run('Calculation Flow Diagram:').bold = True
diag4 = doc.add_paragraph()
run4 = diag4.add_run(
    ' +-----+     +------+         +----------------+  - discount %  +----------------+\n'
    ' | qty |  x  | rate |   -->   |  basic amount  | ------------>  | taxable amount |\n'
    ' +-----+     +------+         +----------------+                +----------------+\n'
    '                                                                         |\n'
    '                                                                 + GST % |\n'
    '                                                                         v\n'
    '                                                                  +------------+\n'
    '                                                                  | line total |\n'
    '                                                                  +------------+\n'
    '                                                                         |\n'
    '                                   PO total = SUM(line totals) <---------+'
)
run4.font.name = 'Consolas'
run4.font.size = Pt(8)

doc.add_paragraph(
    'The _line_total() helper in backend/app/routers/purchases.py (commit 94c746b) '
    'computes this on create, update, and import of purchase orders.'
)

# ============================================================
# 3. Production Automatic Status Change
# ============================================================
doc.add_heading('3. Production Automatic Status Change', level=1)

p = doc.add_paragraph()
p.add_run('Status Flow Diagram:').bold = True
diag5 = doc.add_paragraph()
run5 = diag5.add_run(
    '                   produced_qty > 0                          produced_qty >= schedule_qty\n'
    '  +----------+                            +---------------+                                  +-----------+\n'
    '  | PLANNED  | -------------------------- | IN PRODUCTION | ------------------------------ | COMPLETED |\n'
    '  +----------+                      +---------------+                                  +-----------+\n'
    '                                         ^    |\n'
    '                                         |    |  each movement recalculates\n'
    '                                         +----+  completion_pct & balance_qty;\n'
    '                                              completion_date set on COMPLETED'
)
run5.font.name = 'Consolas'
run5.font.size = Pt(8)

doc.add_paragraph(
    'PLANNED -> IN PRODUCTION when produced_qty > 0 (first production entry). '
    'IN PRODUCTION -> COMPLETED when produced_qty >= schedule_qty. '
    'On every movement: completion_pct = round(produced_qty / schedule_qty, 4), '
    'balance_qty = schedule_qty - produced_qty. completion_date set on COMPLETED.'
)

# ============================================================
# 4. Additional Updates
# ============================================================
doc.add_heading('4. Additional Updates', level=1)

update_table = doc.add_table(rows=7, cols=2)
update_table.style = 'Light Grid Accent 1'
updates = [
    ('Local Orders', 'UI/backend updates (commits 98e37ed, 432bb65, 634bb80): improved tracking, status workflow, reporting'),
    ('Raw Material Opening Stock', 'Fix (commit 46cfc12): resolved opening stock initialization issue'),
    ('Supplier Service', 'Enhancements (commit 98e37ed): new service layer with additional fields and validation'),
    ('Kalika Branding', 'Logo updates (commits fa57ed2, 94c746b, 78ebc0c): Kalika Enterprises branding throughout UI and PDFs'),
    ('Quotation Stability', 'Customer ID resolution, PDF download fix, refresh page fix (commits f57ab90, 1cec353, ba5269a)'),
    ('Production Module', 'Auto-status change mode (commits 7b0eab9, 78ebc0c, dc36831): planned -> in_production -> completed'),
    ('Reports & PDF', 'Quotation PDF generation via ReportLab, integrated with email service for email attachments'),
]
for i, (area, desc) in enumerate(updates):
    update_table.rows[i].cells[0].text = area
    update_table.rows[i].cells[1].text = desc

# ============================================================
# Final note
# ============================================================
doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
run = p.add_run('* Documentation generated from git history analysis of commits between dc36831 and ba5269a, September-October 2026.')
run.font.name = 'Consolas'
run.font.size = Pt(9)
run.font.color.rgb = RGBColor(128, 128, 128)

# Save
output_path = r'D:\KaliSoftAI\ERP-System\backend\docs\Kalika_ERP_Recent_Changes.docx'
doc.save(output_path)
print(f'Word doc saved to {output_path}')