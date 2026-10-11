# Kalika ERP — Recent Changes (September–October 2026)

## 1. Quotation Management Module (New)

### Overview
The **Quotation Management** module is a complete end-to-end feature for generating, managing, and delivering customer quotations. It was added across multiple commits (`a0990b5` through `ba5269a`) and includes:

- Full CRUD on quotations with revision support (duplicate, revise)
- Status workflow: **Draft → Sent → Accepted / Rejected / Expired**
- Two quotation types: **Manufacturing** and **Trading**
- Reusable **Terms & Conditions templates** (with default template flag)
- PDF generation via ReportLab (A4, Kalika logo + stamp, multi-page)
- Email integration via SMTP (Gmail), with preview, send, and history tracking
- Quotation number format: `QTN-YYYYMMDD-###` with unique `(quotation_no, revision)` constraint
- Frontend page at **`/quotations`** (React/TypeScript)

### Quotation Lifecycle Diagram
```
                        send               accept
  +---------+  --------->   +------+  --------->   +----------+
  |  DRAFT  |             | SENT |             | ACCEPTED |
  +---------+             +------+             +----------+
       ^                    |  |
       |                    |  +----- reject ---> +----------+
       |   revise           |                       | REJECTED |
       |  (revision + 1)    |  validity date passed +----------+
       |                    v
       |                +----------+
       +--------------  | EXPIRED  |
                       +----------+

  "Revise" is available from SENT / ACCEPTED / REJECTED / EXPIRED.
  It creates a new DRAFT keeping the same quotation_no and
  incrementing the revision number (unique constraint: quotation_no + revision).
```

### Quotation Numbering & Revision Diagram
```
  QTN-20261004-001  Rev 1  (Draft → Sent → …)
         |
         |  revise
         v
  QTN-20261004-001  Rev 2  (new Draft, revised_from → Rev 1)
         |
         |  revise
         v
  QTN-20261004-001  Rev 3  …
```

### Module Architecture Diagram
```
 +------------------------+      REST / JSON      +---------------------------+
 |  React Frontend        | ---------------------> |  FastAPI Backend          |
 |  /quotations page      |                        |  quotations router        |
 |  (Quotations.jsx)      | <--------------------- |  prefix: /quotations      |
 +------------------------+                        +--------------+------------+
                                                                 |
                            +------------------------------------+-----------------------------+
                            |                                    |                             |
                            v                                    v                             v
                 +---------------------+            +---------------------+         +---------------------+
                 |  PostgreSQL         |            |  quotation_pdf.py   |         |  email_service.py   |
                 |  quotations         |            |  ReportLab A4 PDF   |         |  SMTP (Gmail)       |
                 |  quotation_lines    |            |  Kalika logo+stamp  |         |  preview / send     |
                 |  terms_templates    |            |  multi-page layout  |         |  email history log  |
                 +---------------------+            +---------------------+         +---------------------+
```

### API Endpoints (Quotations Router)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/quotations` | List quotations (filter by customer, number, status, type) |
| `GET` | `/quotations/check-number` | Check availability of `quotation_no` + `revision` |
| `POST` | `/quotations` | Create a new quotation |
| `GET` | `/quotations/{id}` | Retrieve a quotation |
| `PUT` | `/quotations/{id}` | Update a quotation (keeps in Draft until sent) |
| `DELETE` | `/quotations/{id}` | Delete a quotation |
| `POST` | `/quotations/{id}/duplicate` | Duplicate to a new quotation |
| `POST` | `/quotations/{id}/revise` | Create a new revision |
| `POST` | `/quotations/{id}/status` | Change status (Draft → Sent → Accepted/Rejected/Expired) |
| `GET` | `/quotations/{id}/history` | Audit history of changes |
| `GET` | `/quotations/{id}/email-preview` | Preview email before sending |
| `POST` | `/quotations/{id}/send-email` | Send quotation as PDF via SMTP |
| `GET` | `/quotations/{id}/email-history` | Email send history log |
| `GET` | `/quotations/terms-templates` | List terms & conditions templates |
| `POST` | `/quotations/terms-templates` | Create a terms template |
| `PUT` | `/quotations/terms-templates/{id}` | Update a terms template |
| `DELETE` | `/quotations/terms-templates/{id}` | Delete a terms template |

### PDF & Email
- **PDF Builder** (`quotation_pdf.py`): ReportLab, A4 page, Kalika Enterprises logo + circular stamp, multi-page table layout, itemized lines with totals (basic, discount, tax, amount)
- **Email Service** (`email_service.py`): SMTP (Gmail by default), templated subject/body, PDF attachment, email history logged per quotation
- Email subject format: `Quotation {quotation_no} Rev. {q.revision} - Kalika Enterprises`

### Recent Fixes (quotation module stability)
- **Customer ID resolution** (`f57ab90`): Fixed customer ID problem on quotation creation
- **PDF download** (`1cec353` / `8717d66`): Fixed PDF generation and download flow
- **Refresh page issue** (`ba5269a`): Fixed state refresh after quotation actions

---

## 2. Purchase GST & Discount Calculations

### Line Total Formula
Each purchase order line total is computed as:

```
basic_amount  = quantity × rate
discount_amount = round(basic_amount × discount_percent / 100, 2)
taxable_amount  = basic_amount - discount_amount
gst_amount      = round(taxable_amount × tax_percent / 100, 2)
line_total      = round(taxable_amount + gst_amount, 2)
```

### Flow Diagram
```
 +-----+     +------+         +----------------+  - discount %  +----------------+
 | qty |  x  | rate |   -->   |  basic amount  | ------------>  | taxable amount |
 +-----+     +------+         +----------------+                +----------------+
                                                                         |
                                                                 + GST % |
                                                                         v
                                                                  +------------+
                                                                  | line total |
                                                                  +------------+
                                                                         |
                                   PO total = SUM(line totals) <---------+
```

The `_line_total()` helper in `purchases.py` (commit `94c746b`) computes this on **create**, **update**, and **import** of purchase orders.

---

## 3. Production Automatic Status Change

### Status Flow Diagram
```
                   produced_qty > 0                          produced_qty >= schedule_qty
  +----------+                            +---------------+                                  +-----------+
  | PLANNED  | -------------------------- | IN PRODUCTION | ------------------------------ | COMPLETED |
  +----------+                      +---------------+                                  +-----------+
                                         ^    |
                                         |    |  each movement recalculates
                                         +----+  completion_pct & balance_qty;
                                              completion_date set on COMPLETED
```

### Behaviour
- **PLANNED** → **IN PRODUCTION**: when `produced_qty > 0` (first production entry)
- **IN PRODUCTION** → **COMPLETED**: when `produced_qty >= schedule_qty`
- On every production movement, `completion_pct = round(produced_qty / schedule_qty, 4)` and `balance_qty = schedule_qty - produced_qty` are recalculated
- `completion_date` is set to today's date when status becomes **COMPLETED**

---

## 4. Additional Updates

| Area | Change |
|------|--------|
| **Local Orders** | UI/backend updates (`98e37ed`, `432bb65`, `634bb80`): improved local order tracking, status workflow, and reporting |
| **Raw Material Opening Stock** | Fix (`46cfc12`): resolved opening stock initialization issue |
| **Supplier Service** | Enhancements (`98e37ed`): new service layer with additional fields and validation |
| **Kalika Branding** | Logo updates (`fa57ed2`, `94c746b`, `78ebc0c`): Kalika Enterprises branding throughout UI and PDFs |
| **Quotation Stability** | Customer ID resolution, PDF download fix, refresh page fix (commits `f57ab90`, `1cec353`, `ba5269a`) |

---

## 5. Sample Data Updates (New User Onboarding)

New users get a self-contained set of reference data so every screen has
something realistic to show before any production records exist.

| Sample set | File(s) | What it demonstrates |
|------------|---------|----------------------|
| Quote-processing pipeline (Jabil / Amber) | `quote_processing_pipeline_jabil_amber.md`, `.xlsx` | End-to-end RFQ → quote → follow-up stages for two real customers |
| Packaging & stretch-film leads | `packaging_business_leads_and_workflow.md` | 20 inbound leads, product/requirement summary, enquiry-to-completion workflow |
| GCS KPI data inventory | `gcs_data_inventory.xlsx` | Source objects, row counts and the packaging/KPI pipeline mapping |
| ERP workbook | `Kalika_ERP.xlsx` | Master module/field reference used by the UI |

Onboarding usage:
- New users start from the sample sets above; they are **read-only examples**,
  kept apart from real quotations and leads.
- The sample flows mirror the live module workflow (customer → quotation → PDF →
  email, and enquiry → quote → follow-up) so a new user can rehearse the process.
- Sample data can be cleared in one action once real records are entered.

---

## 6. Future Scope — UI for Latest Update Progress

A dedicated **"What's new / Update progress"** surface is planned so users can
see what shipped and what is coming without reading commit history.

```
 +------------------------------------------------------------------+
 |  Release Progress                          last synced: today     |
 +------------------------------------------------------------------+
 |  Shipped                                                          |
 |   [####------] Quotation Management      v  (draft->sent->accept)|
 |   [########--] Purchase GST & Discount   v                       |
 |   [######----] Production Auto-Status    v                       |
 |                                                                   |
 |  In progress                                                      |
 |   [###-------] Packaging KPI dashboard   ~ Q4 2026               |
 |   [##--------] GCS data pipeline         ~ Q4 2026               |
 |                                                                   |
 |  Planned                                                          |
 |   [----------] MCP polymer price calc    TBD                      |
 +------------------------------------------------------------------+
```

Planned capabilities:
- **Timeline view** of merged changes grouped by module, kept in sync with this
  changes document so the UI and the docs never drift.
- **Progress bars** per module driven by a small status file
  (shipped / in-progress / planned) instead of hard-coded values.
- **In-app changelog** with filters (module, date, author) and deep links to the
  affected page.
- **Read-only for all roles**; only maintainers can edit status entries.

---

*Documentation generated from git history analysis of commits between `dc36831` (project complete) and `ba5269a` (quotation refresh fix), September–October 2026. Updated with sample-data onboarding and update-progress UI scope.*