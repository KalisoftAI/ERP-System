# Branch, Merge & Feature Register

> Snapshot: 2026-11-02
> Current branch: `docs/recent-updates`
> Merge commit: `2c647c7` — `Merge upstream/master into docs/recent-updates`
> Canonical source merged: `upstream/master` @ `a855fe3` (2026-11-01)

---

## 1. Merge summary

```
                       BEFORE                                      AFTER
                                                                 
 docs/recent-updates  cb1296c                     docs/recent-updates  2c647c7
        |                                                |
        | 6 docs/branding commits                        | merge commit
        |                                                +--> upstream/master a855fe3
        |                                                +--> prior docs commits
        v                                                v
 upstream/master      a855fe3  (49 commits)      upstream/master is fully contained
                                                (0 commits behind)
```

| Item | Value |
|------|-------|
| Target branch | `docs/recent-updates` |
| Source branch | `upstream/master` |
| Source tip | `a855fe3` — added changes in local order and dispatch departments |
| Merge commit | `2c647c7` |
| Files changed by merge | 84 staged files (including additions, modifications, one deletion) |
| Conflicts | 4 files |
| Post-merge state | Clean working tree; `upstream/master` fully merged |
| Local dependency install | `npm install` added 5 packages (`html2canvas` and deps) |

### Conflict resolution

| File | Resolution |
|------|------------|
| `backend/app/routers/bom.py` | Kept upstream audit logging (`write_audit`) and restored role guards from this branch: `AllStaff` for create/update, `ManagerOrAdmin` for delete |
| `backend/app/routers/production.py` | Took upstream version (production plan import, `cell_text`, `parse_date_value`, date/time helpers) |
| `frontend/src/components/Layout.jsx` | Took upstream branding (`/Kalika_logo.png`) and responsive sidebar/mobile header classes |
| `frontend/src/pages/Production.jsx` | Took upstream version (plan columns, monthly filter, mark-complete, flexible import preview) |

---

## 2. Local branches

| Branch | Tip | Last update | Ahead / behind HEAD | State | Purpose |
|--------|-----|-------------|---------------------|-------|---------|
| `docs/recent-updates` | `2c647c7` | 2026-11-02 | 0 / 0 | Current, merged with upstream | Documentation, branch register, weighing/printer roadmap |
| `master` | `75ce2b0` | 2026-09-20 | 56 / 0 | Contained in HEAD | Older master snapshot |
| `feature/quote-pdf-vci-packaging-roadmap` | `75ce2b0` | 2026-09-20 | 56 / 0 | Contained in HEAD | Quote PDF / VCI / SOP roadmap base |
| `deployed-master` | `ba5269a` | 2026-10-04 | 40 / 0 | Contained in HEAD | Deployed snapshot (quotation refresh fix) |
| `feat/orders-dept-enhancement` | `ab9c8e1` | 2026-09-19 | 59 / 0 | Contained in HEAD | Order department changes |
| `feat/tab-logo-v1` | `ab9c8e1` | 2026-09-19 | 59 / 0 | Contained in HEAD | Same tip as orders enhancement; branding experiment |
| `feat/production-plan-enhancement` | `adddf4d` | 2026-09-20 | 57 / 0 | Contained in HEAD | Production plan columns, monthly filter, import preview |

---

## 3. Remote branches

Legend: **A/B** = commits ahead / behind `docs/recent-updates` after the merge.

| Remote branch | Tip | Last update | A/B | State | Scope |
|---------------|-----|-------------|-----|-------|-------|
| `upstream/master` | `a855fe3` | 2026-11-01 | 10 / 0 | Merged | Canonical integration branch |
| `upstream/HR_Dev` | `3263913` | 2026-11-02 | 10 / 1 | **1 commit not merged** | Standard sheet update |
| `upstream/HR_Payroll` | `6c53ac2` | 2026-10-06 | 34 / 1 | **1 commit not merged** | HR/payroll requirements document |
| `origin/feat/barcode-v1` | `ddef0e2` | 2026-09-06 | 70 / 1 | **1 commit not merged** | Barcode scanning, label printing, product recognition, dispatch flow |
| `upstream/PO_Feat` | `76a88ff` | 2026-10-21 | 18 / 0 | Merged | PO type, supplier auto-fetch, local order updates |
| `upstream/PRN_Feat` | `7f7aa7b` | 2026-10-22 | 17 / 0 | Merged | PRN module and PRN PDF |
| `upstream/master_copy_12_10` | `e932940` | 2026-10-11 | 30 / 0 | Merged | Kalika Infotech quotation functionality |
| `origin/feat/orders-dept-enhancement` | `ab9c8e1` | 2026-09-19 | 59 / 0 | Merged | Order department changes |
| `origin/feat/production-plan-enhancement` | `adddf4d` | 2026-09-20 | 57 / 0 | Merged | Production plan enhancements |
| `origin/master` | `75ce2b0` | 2026-09-20 | 56 / 0 | Merged | Old canonical branch |
| `origin/dev2` / `upstream/dev2` | `df22a48` | 2026-09-19 | 60 / 0 | Merged | Local order + production department update |
| `origin/Autocode-16sep` / `upstream/Autocode-16sep` | `6cf4d17` | 2026-09-11 | 62 / 0 | Merged | README and earlier delivery |
| `origin/DEV` / `upstream/DEV` | `aafa2a5` | 2026-09-03 | 75 / 0 | Merged | Complete ERP baseline |
| `upstream/Dev_feat_V1` | `f25216a` | 2026-09-04 | 70 / 0 | Merged | DB credential URL encoding |
| `upstream/feat/barcode-v1` | `ddef0e2` | 2026-09-06 | 70 / 1 | **1 commit not merged** | Same barcode feature as origin |

---

## 4. High-level feature register

| Domain | Feature | What changed | Key files | Branch / origin |
|--------|---------|--------------|-----------|-----------------|
| Quotations | Quote lifecycle, revisions, terms, PDF + email | Quote CRUD, numbering/revision, PDF generation, email attachment, Kalika Infotech template, customer-ID fixes | `backend/app/routers/quotations.py`, `backend/app/services/quotation_pdf.py`, `backend/app/models.py`, `frontend/src/pages/Quotations.jsx` | `upstream/master`, `upstream/master_copy_12_10` |
| PRN | Purchase Requisition Note | CRUD, approval workflow, PDF, stock override without changing inventory, fulfilment | `backend/app/routers/prns.py`, `services/prn_pdf.py`, `services/prn_fulfilment.py`, `frontend/src/pages/PurchaseRequisitions.jsx`, `PrnDetail.jsx`, `PrnEditorModal.jsx` | `upstream/PRN_Feat` |
| Packaging list | Box/row packing document | Box rows, row/box numbering, auto cursor movement, unsaved-change guard, print/PDF optimization | `backend/app/routers/packaging_lists.py`, `backend/app/models.py`, `frontend/src/pages/PackagingList.jsx` | `upstream/PRN_Feat`, `upstream/master` |
| Employees / HR | Employee master | Employee CRUD, PF/UAN/ESIC details, table filters, employee PDF export | `backend/app/routers/employees.py`, `services/employee_pdf.py`, `frontend/src/pages/Employees.jsx` | `upstream/HR_Dev`, `upstream/master` |
| Activity log | Audit/activity feed | Read-side activity log router and UI | `backend/app/routers/activity_log.py`, `frontend/src/pages/ActivityLog.jsx`, `backend/tests/test_activity_log.py` | `upstream/master` |
| Purchases / suppliers | PO type + supplier automation | Auto supplier fetch, PO type migration, import PO form, supplier service | `backend/app/migrate_po_type.py`, `services/suppliers.py`, `frontend/src/components/ImportPOForm.jsx` | `upstream/PO_Feat`, `upstream/master` |
| Local orders | Local order department | Header/meta/table styling, local order ↔ production completion sync | `backend/app/services/local_orders.py`, `frontend/src/pages/LocalOrders.jsx` | `upstream/master`, `feat/orders-dept-enhancement` |
| Dispatch | Dispatch calculation | Dispatch calculation service, dispatch stock and fulfilment updates | `backend/app/services/dispatch_calc.py`, `backend/app/routers/dispatch.py`, `frontend/src/pages/Dispatch.jsx` | `upstream/master` |
| Production | Status + plan workflow | Automatic status change, plan table columns, monthly schedule filter, mark-complete, flexible CSV/Excel import with preview | `backend/app/routers/production.py`, `frontend/src/pages/Production.jsx` | `feat/production-plan-enhancement`, `upstream/master` |
| Branding | Logo and stamp | Backend/frontend Kalika logo and stamp assets; sidebar/login branding | `backend/app/assets/`, `frontend/public/Kalika_logo.png`, `frontend/public/assets/stamp.png`, `frontend/src/components/Layout.jsx` | `upstream/master`, docs branch |
| Security | RBAC + deployment review | BOM/alerts role guards, JWT secret and SPA path-traversal findings documented | `backend/app/routers/bom.py`, `backend/app/routers/alerts.py`, `SECURITY-REVIEW.md` | docs branch, `upstream/master` |
| Weighing + labels | Scale/printer integration | TSC TTP-244 Pro, 100 mm gap labels, RS232 capture, TSPL template, data model and phased rollout | `WEIGHING-PRINTER-INTEGRATION.md` | docs branch |
| Deployment | Cloud Run deployment | Deploy script, guide, Cloud Build config, non-root container fixes | `deploy.sh`, `deploy_guide.md`, `cloudbuild.yaml`, `Dockerfile` | `upstream/master` |
| HR / payroll | Requirements | HR and payroll requirement notes | `Requirements-HR-Payroll-and-Packaging-List.md` | `upstream/HR_Payroll` |
| Barcode | Barcode + label printing | Barcode scan, label printing, product recognition, dispatch flow | Not merged; see `origin/feat/barcode-v1` | `feat/barcode-v1` |

---

## 5. Data model additions

| Domain | Tables |
|--------|--------|
| Identity / audit | `users`, `audit_logs`, `email_logs` |
| Masters | `customers`, `customer_aliases`, `salespersons`, `suppliers`, `products`, `product_aliases`, `plants`, `employees` |
| Reporting / import | `reporting_periods`, `import_batches`, `migration_logs` |
| Materials / BOM | `raw_material_balances`, `boms`, `bill_of_materials` |
| Procurement | `purchase_orders`, `purchase_order_lines`, `prns`, `prn_lines`, `purchase_requirements` |
| Inventory | `inventory`, `stock_movements`, `stock_transfers`, `stock_transfer_lines` |
| Sales / dispatch | `sales_orders`, `sales_order_lines`, `dispatches`, `dispatch_lines`, `customer_dispatches`, `customer_dispatch_lines` |
| Packaging | `packaging_lists`, `packaging_list_lines` |
| Production | `production_orders`, `production_movements`, `plans` |
| Quotes | `quotations`, `quotation_lines`, `terms_templates` |
| Alerts | `alerts` |

---

## 6. `.gitignore` policy

| Pattern | Purpose |
|---------|---------|
| `.env`, `.env.*` | Secrets and local environment (example files still allowed) |
| `__pycache__/`, `*.py[cod]`, `.venv/`, `venv/` | Python runtime/cache |
| `node_modules/`, `frontend/dist/`, `frontend/.vite/` | Node dependencies and build output |
| `docs/`, `**/docs/`, `frontend/docs/` | Documentation folders kept local |
| `data/`, `**/data/`, `backend/data/backups/` | Data folders and DB backups kept local |
| `*.db`, `*.sqlite3`, `*.dump`, `*.sql`, `dump*.sql` | Database artifacts |
| `reports/`, `export_*.csv`, `export_*.xlsx` | Generated reports and exports |
| `*.log` | Log files |
| `.vscode/`, `.idea/`, `.DS_Store`, `Thumbs.db` | IDE/OS files |
| `backend/docs/*` specific entries | Branch-only sample docs kept local |

Note: already-tracked files in `backend/docs/` remain tracked even though `**/docs/` is ignored. Use `git rm --cached <file>` if they should leave the repository.

---

## 7. Checks performed

| Check | Command | Result |
|-------|---------|--------|
| Merge conflicts | `git status` / conflict-marker scan | None remaining |
| Whitespace errors | `git diff --check` | Pass (`exit 0`) |
| Python syntax | `python -m compileall -q backend/app` | Pass (`exit 0`) |
| Node dependencies | `npm install` (in `frontend/`) | Added 5 packages; 4 high-severity advisories reported |
| Frontend build | `npm run build` (in `frontend/`) | Pass; bundle warning: 1.46 MB main chunk (>500 kB) |
| Frontend lint | `npm run lint` (in `frontend/`) | Pass with warnings; no errors |
| Branch containment | `git rev-list --left-right --count HEAD...<branch>` | `upstream/master` fully contained |
| Backend tests | `python tests/test_*.py` (in `backend/`) | Not runnable here: missing `passlib` and `DATABASE_URL` |
| Working tree | `git status --short` | Clean after merge commit |

Lint warnings are predominantly unused imports/variables and `react-hooks/exhaustive-deps`; they are non-blocking and pre-existing in several modules.

---

## 8. Unmerged work and open items

| Branch | Unmerged commit | Action |
|--------|-----------------|--------|
| `upstream/HR_Dev` | `3263913` — Standard Sheet update | Review and merge separately |
| `upstream/HR_Payroll` | `6c53ac2` — HR/payroll requirements | Review requirements; merge when implementation starts |
| `origin/feat/barcode-v1` / `upstream/feat/barcode-v1` | `ddef0e2` — barcode scanning, label printing, product recognition, dispatch flow | Review against `WEIGHING-PRINTER-INTEGRATION.md`; likely relates to the TSC label work |

Open operational items from `WEIGHING-PRINTER-INTEGRATION.md`:

- Indicator make/model, capacity, division, platform size and power are still **NA**.
- Label height/gap, barcode content and indicator serial protocol must be confirmed.
- TSC printer uses TSPL-EZ, not ZPL.
- Weight capture must be frozen at PRINT time and stored before printing.

---

## 9. Verification commands (repeatable)

```powershell
# branch state
git fetch --all --prune
git rev-list --left-right --count HEAD...upstream/master
git status --short

# backend syntax
python -m compileall -q backend/app
git diff --check

# frontend
cd frontend
npm install
npm run build
npm run lint
```

```powershell
# optional backend tests (requires passlib + DATABASE_URL)
cd backend
python tests/test_activity_log.py
python tests/test_employee_advanced.py
python tests/test_import_po_supplier.py
python tests/test_prn_override.py
```
