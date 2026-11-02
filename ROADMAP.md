# ERP-V1 Changes Roadmap — Kalika Enterprises

> Branch: `feature/quote-pdf-vci-packaging-roadmap` (local only — **do NOT push**; `master` is deployed)
>
> Detailed code specification: see **[ROADMAP-DETAILS.md](./ROADMAP-DETAILS.md)**

---

## 1. References & Assets

| Item | Location / Path | Notes |
|------|-----------------|-------|
| **Kalika Logo** | `gs://kalika_enterprises/docs/kalika logo.jpeg` | Official logo — **strictly no change** in any generated document |
| **Quote Path (sample)** | `gs://kalika_enterprises/docs/DOC-20260910-WA0007.pdf` | Reference quote document for layout/design |
| **Sample Data** | `kalika_enterprises/ERP-V1` | ERP-V1 dataset used for context and testing |

---

## 2. Context (Data Process and Update Prompts)

Read the ERP-V1 directory, get full context, and build the required features:

1. Generate a **PDF format quotation document** that will be sent over **email** to the customer — with proper **designing/branding**.
   - **Strictly no change in the logo** (`kalika logo.jpeg`).
   - **Catalog files** may have required changes only.
2. **VCI packaging** document with Kalika's logo and standard designing, with features derived from the same documents' contexts.
3. **SOPs of other processes** — to be **reviewed by a human** before finalization.

---

## 3. Changes Roadmap

### 3.1 Quote PDF Generation (Email-Ready)

- [ ] Design quote PDF template matching the sample (`DOC-20260910-WA0007.pdf`)
  - Company header with **unchanged Kalika logo**
  - Company details, quote number, date, validity
  - Customer / billing / shipping details section
  - Line items table: SKU, description, HSN, qty, UOM, rate, discount, tax (GST), amount
  - Totals: subtotal, freight/other charges, tax breakup (CGST/SGST/IGST), grand total
  - Terms & conditions, bank details, authorized signatory block
- [ ] Backend: quote-to-PDF service (server-side render, downloadable + attachable)
- [ ] Email integration: send quote PDF as attachment (SMTP / provider API)
  - Configurable subject/body template with customer name and quote number
- [ ] Frontend: "Generate Quote PDF" + "Email Quote" actions on Quote screen
- [ ] Catalog files: apply **required changes only** (no restructuring)
- [ ] Logo usage: embed from asset store, **no modification** (size/format only)

### 3.2 VCI Packaging Document

- [ ] VCI packaging slip/document template with **Kalika's logo** (unchanged) and standard designing
- [ ] Fields derived from ERP-V1 documents context (item, VCI type, quantity, batch/lot, packing date, inspector)
- [ ] Backend: VCI packaging PDF generation service
- [ ] Frontend: VCI packaging section linked to dispatch/production flow
- [ ] Print-friendly layout (A4 / label formats as applicable)

### 3.3 SOPs — Other Processes (Human Review)

- [ ] Draft SOP documents for remaining processes (Sales, Purchase, Inventory, Production, Dispatch, Quality)
- [ ] Mark each SOP as **DRAFT — pending human review**
- [ ] Review workflow: human approver signs off before publishing to ERP docs

---

## 4. Guardrails

- **No push** of this branch — `master` is deployed; merge only via reviewed PR later.
- **Logo is locked**: never edit, recolor, crop, or replace `kalika logo.jpeg`.
- Catalog files: **required changes only** — keep structure and existing content intact.
- All new documents must follow the same standard design language as the sample quote PDF.

---

## 5. Progress Tracker

| # | Feature | Status | Owner |
|---|---------|--------|-------|
| 1 | Quote PDF + Email | ☐ Not started | — |
| 2 | VCI Packaging Doc | ☐ Not started | — |
| 3 | SOPs (human review) | ☐ Not started | — |
