"""Reports & export endpoints (CSV / Excel / PDF)."""
import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..config import settings
from ..database import get_db
from ..models import (
    Customer, Dispatch, DispatchLine, Inventory, OrderType, Plant, Product, ProductionMovement,
    ProductionOrder, PurchaseOrder, RawMaterialBalance, SalesOrder, SalesOrderLine,
    StockMovement, Supplier,
)
from datetime import date

router = APIRouter(prefix="/reports", tags=["reports"])

EXPORT_DIR = settings.report_dir
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def _csv_response(headers, rows, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/inventory/csv")
def inventory_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(Inventory).order_by(Inventory.product_id)).all()
    headers = ["Product", "Item Code", "Category", "Plant", "Opening", "Received", "Issued", "Current Stock", "Min Level", "Status"]
    data = []
    for i in rows:
        status = "OK"
        if i.min_level is not None and i.current_stock <= 0:
            status = "OUT_OF_STOCK"
        elif i.min_level is not None and i.current_stock < i.min_level:
            status = "LOW"
        data.append([i.product.model if i.product else "", i.product.item_code if i.product else "",
                     i.product.category.value if i.product else "", i.plant.name if i.plant else "Main Store",
                     i.opening_stock, i.received_qty, i.issued_qty, i.current_stock, i.min_level or "", status])
    return _csv_response(headers, data, "inventory.csv")


@router.get("/movements/csv")
def movements_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(StockMovement).order_by(StockMovement.transaction_date.desc())).all()
    headers = ["Date", "Product", "Type", "Qty", "Plant", "Ref", "Remarks"]
    data = [[m.transaction_date, m.product.model if m.product else "", m.movement_type.value, m.quantity,
             m.plant.name if m.plant else "", m.ref_type or "", m.remarks or ""] for m in rows]
    return _csv_response(headers, data, "stock_movements.csv")


@router.get("/raw-materials/csv")
def raw_materials_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(RawMaterialBalance).order_by(RawMaterialBalance.report_date)).all()
    headers = ["Date", "Material", "Item Code", "Schedule", "Ask Till", "Inward", "% Comp", "Balance", "Opening"]
    data = [[b.report_date, b.product.model if b.product else "", b.product.item_code if b.product else "",
             b.schedule_qty, b.ask_till_date, b.inward_qty, b.completion_pct, b.balance_qty, b.opening_stock] for b in rows]
    return _csv_response(headers, data, "raw_materials.csv")


@router.get("/production/csv")
def production_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(ProductionOrder).order_by(ProductionOrder.report_date.desc())).all()
    headers = ["Order No", "Product", "Section", "Schedule", "Produced", "% Comp", "Balance", "Status", "Report Date"]
    data = [[o.order_no, o.product.model if o.product else "", o.section or "", o.schedule_qty, o.produced_qty,
             o.completion_pct, o.balance_qty, o.status.value, o.report_date] for o in rows]
    return _csv_response(headers, data, "production.csv")


# ---------------------------------------------------------------------------
# Monthly Production Report (Phase: Production Department)
# Totals are derived from ACTUAL production movements (date-wise output records),
# never from plans — a plan is a target, actual output is the record.
# ---------------------------------------------------------------------------
def _monthly_production_rows(db: Session, month: str):
    """Daily actual production movements for the month 'YYYY-MM' (or '' = all)."""
    stmt = select(ProductionMovement).where(ProductionMovement.production_date.is_not(None))
    if month:
        y, m = int(month[:4]), int(month[5:7])
        d0 = date(y, m, 1)
        d1 = date(y + (1 if m == 12 else 0), (1 if m == 12 else m + 1), 1)
        stmt = stmt.where(ProductionMovement.production_date >= d0,
                          ProductionMovement.production_date < d1)
    rows = db.scalars(stmt.order_by(ProductionMovement.production_date, ProductionMovement.id)).all()
    items = []
    for m in rows:
        po = m.production_order
        p = po.product if po else None
        cust = po.customer if po else None
        items.append({
            "id": m.id,
            "production_order_id": m.production_order_id,
            "production_date": m.production_date.isoformat(),
            "product_id": p.id if p else (po.product_id if po else None),
            "model": p.model if p else None,
            "item_code": p.item_code if p else None,
            "customer_id": cust.id if cust else (po.customer_id if po else None),
            "customer": cust.name if cust else None,
            "quantity": float(m.quantity or 0),
            "ref": po.order_no if po else "",
        })
    return items


@router.get("/production/monthly")
def monthly_production_report(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    month: str = "",
):
    """Monthly production report built from actual daily production movements.

    `month` is 'YYYY-MM' (empty = all time). Returns the daily ledger plus
    per-product and per-date rollups and month totals — all DB-driven.
    """
    items = _monthly_production_rows(db, month)

    by_product = {}
    by_date = {}
    total_qty = 0.0
    for i in items:
        total_qty += i["quantity"]
        d = i["production_date"]
        e = by_date.setdefault(d, {"production_date": d, "quantity": 0.0, "movements": 0})
        e["quantity"] += i["quantity"]
        e["movements"] += 1
        pk = i["product_id"]
        e2 = by_product.setdefault(pk, {"product_id": pk, "model": i["model"],
                                        "item_code": i["item_code"], "quantity": 0.0,
                                        "days": set(), "movements": 0})
        e2["quantity"] += i["quantity"]
        e2["days"].add(d)
        e2["movements"] += 1

    def finalize(e):
        e["days"] = len(e["days"])
        return e

    by_product = [finalize(e) for e in by_product.values()]
    by_product.sort(key=lambda x: -(x["quantity"] or 0))
    by_date = sorted(by_date.values(), key=lambda x: x["production_date"], reverse=True)
    return {
        "month": month,
        "items": items,
        "by_product": by_product,
        "by_date": by_date,
        "totals": {
            "quantity": round(total_qty, 4),
            "days": len(by_date),
            "products": len(by_product),
            "movements": len(items),
        },
    }


@router.get("/production/monthly/csv")
def monthly_production_csv(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    month: str = "",
):
    items = _monthly_production_rows(db, month)
    headers = ["Date", "Product", "Item Code", "Customer", "Quantity", "Production Order"]
    data = [[i["production_date"], i["model"] or "", i["item_code"] or "", i["customer"] or "",
             i["quantity"], i["ref"]] for i in items]
    fname = f"monthly_production_{month}_{date.today().isoformat()}.csv"
    return _csv_response(headers, data, fname)


@router.get("/dispatch/csv")
def dispatch_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(Dispatch).order_by(Dispatch.report_date.desc())).all()
    headers = ["Dispatch No", "Customer", "Plant", "Sales Person", "Schedule", "Dispatched", "% Comp", "Balance",
               "Status", "Report Date"]
    data = [[d.dispatch_no, d.customer.name if d.customer else "", d.plant.name if d.plant else "",
             d.sales_person or "", d.schedule_qty, d.dispatched_qty, d.completion_pct, d.balance_qty,
             d.status.value, d.report_date] for d in rows]
    return _csv_response(headers, data, "dispatch.csv")


@router.get("/orders/csv")
def orders_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(SalesOrder).order_by(SalesOrder.order_date.desc())).all()
    headers = ["Order No", "Customer", "Order Date", "Required Date", "Status", "Total Value", "Remarks"]
    data = [[o.order_no, o.customer.name if o.customer else "", o.order_date, o.required_delivery_date or "",
             o.status.value, o.total_value, o.remarks or ""] for o in rows]
    return _csv_response(headers, data, "orders.csv")


@router.get("/purchases/csv")
def purchases_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.order_date.desc())).all()
    headers = ["PO No", "Supplier", "Order Date", "Status", "Total Amount", "Notes"]
    data = [[p.po_number, p.supplier.name if p.supplier else "", p.order_date, p.status.value,
             p.total_amount, p.notes or ""] for p in rows]
    return _csv_response(headers, data, "purchases.csv")


@router.get("/customers/csv")
def customers_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(Customer).order_by(Customer.name)).all()
    headers = ["Name", "Code", "Plant?", "Contact", "Email", "Address"]
    data = [[c.name, c.code or "", "Yes" if c.is_plant else "No", c.contact_person or "",
             c.email or "", c.address or ""] for c in rows]
    return _csv_response(headers, data, "customers.csv")


@router.get("/suppliers/csv")
def suppliers_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    headers = ["Name", "Code", "Contact", "Email", "Address"]
    data = [[s.name, s.code or "", s.contact_person or "", s.email or "", s.address or ""] for s in rows]
    return _csv_response(headers, data, "suppliers.csv")


@router.get("/products/csv")
def products_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(Product).order_by(Product.category, Product.model)).all()
    headers = ["Item Code", "Model", "Name", "Category", "UOM"]
    data = [[p.item_code or "", p.model or "", p.name or "", p.category.value, p.uom or ""] for p in rows]
    return _csv_response(headers, data, "products.csv")


def _excel_response(fname, sheet, headers, rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.get("/excel")
def excel_report(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    """Combined Excel workbook with all modules."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    hdr_fill = PatternFill("solid", fgColor="4472C4")
    hdr_font = Font(color="FFFFFF", bold=True)

    def add_sheet(name, headers, rows):
        ws = wb.create_sheet(name[:31])
        ws.append(headers)
        for c in ws[1]:
            c.fill = hdr_fill
            c.font = hdr_font
        for r in rows:
            ws.append(r)
        for i, _ in enumerate(headers, 1):
            ws.column_dimensions[chr(64 + i)].width = 18
        return ws

    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    inv = db.scalars(select(Inventory).order_by(Inventory.product_id)).all()
    add_sheet("Inventory", ["Product", "Item Code", "Category", "Plant", "Opening", "Received", "Issued",
                            "Current Stock", "Min Level", "Status"],
              [[i.product.model if i.product else "", i.product.item_code if i.product else "",
                i.product.category.value if i.product else "", i.plant.name if i.plant else "Main Store",
                i.opening_stock, i.received_qty, i.issued_qty, i.current_stock, i.min_level or ""] for i in inv])

    prod = db.scalars(select(ProductionOrder).order_by(ProductionOrder.report_date)).all()
    add_sheet("Production", ["Order No", "Product", "Section", "Schedule", "Produced", "% Comp", "Balance",
                             "Status", "Report Date"],
              [[o.order_no, o.product.model if o.product else "", o.section or "", o.schedule_qty,
                o.produced_qty, o.completion_pct, o.balance_qty, o.status.value, o.report_date] for o in prod])

    disp = db.scalars(select(Dispatch).order_by(Dispatch.report_date)).all()
    add_sheet("Dispatch", ["Dispatch No", "Customer", "Plant", "Sales Person", "Schedule", "Dispatched",
                           "% Comp", "Balance", "Status", "Report Date"],
              [[d.dispatch_no, d.customer.name if d.customer else "", d.plant.name if d.plant else "",
                d.sales_person or "", d.schedule_qty, d.dispatched_qty, d.completion_pct, d.balance_qty,
                d.status.value, d.report_date] for d in disp])

    rm = db.scalars(select(RawMaterialBalance).order_by(RawMaterialBalance.report_date)).all()
    add_sheet("Raw Materials", ["Date", "Material", "Item Code", "Schedule", "Ask Till", "Inward", "% Comp",
                                "Balance", "Opening"],
              [[b.report_date, b.product.model if b.product else "", b.product.item_code if b.product else "",
                b.schedule_qty, b.ask_till_date, b.inward_qty, b.completion_pct, b.balance_qty,
                b.opening_stock] for b in rm])

    ords = db.scalars(select(SalesOrder).order_by(SalesOrder.order_date)).all()
    add_sheet("Orders", ["Order No", "Customer", "Order Date", "Required Date", "Status", "Total Value"],
              [[o.order_no, o.customer.name if o.customer else "", o.order_date, o.required_delivery_date or "",
                o.status.value, o.total_value] for o in ords])

    bos = db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.order_date)).all()
    add_sheet("Purchases", ["PO No", "Supplier", "Order Date", "Status", "Total Amount"],
              [[p.po_number, p.supplier.name if p.supplier else "", p.order_date, p.status.value,
                p.total_amount] for p in bos])

    cust = db.scalars(select(Customer).order_by(Customer.name)).all()
    add_sheet("Customers", ["Name", "Code", "Plant?", "Contact", "Email", "Address"],
              [[c.name, c.code or "", "Yes" if c.is_plant else "No", c.contact_person or "",
                c.email or "", c.address or ""] for c in cust])

    supp = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    add_sheet("Suppliers", ["Name", "Code", "Contact", "Email", "Address"],
              [[s.name, s.code or "", s.contact_person or "", s.email or "", s.address or ""] for s in supp])

    plants = db.scalars(select(Plant).order_by(Plant.name)).all()
    add_sheet("Plants", ["Code", "Name"],
              [[p.code or "", p.name] for p in plants])

    prods = db.scalars(select(Product).order_by(Product.category, Product.model)).all()
    add_sheet("Products", ["Item Code", "Model", "Name", "Category", "UOM"],
              [[p.item_code or "", p.model or "", p.name or "", p.category.value, p.uom or ""] for p in prods])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"kalika_report_{date.today().isoformat()}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ---------------------------------------------------------------------------
# Delivery Report (Phase 6K): Completed / Partially Dispatched / Not Dispatched
# ---------------------------------------------------------------------------
def _delivery_rows(db: Session, customer_id: int | None = None,
                   date_from: str = "", date_to: str = ""):
    """Per order-line delivery ledger with rollup-ready fields (C4).

    Attribution model (no random guessing):
      * a DispatchLine linked to a sales order line (`sales_order_line_id`) is
        attributed EXACTLY to that order line;
      * a DispatchLine with NO line link is pooled per (order, product). It is
        attributed to an order line ONLY when the order has a single line for
        that product (provable by identity); otherwise it stays UNALLOCATED and
        is surfaced as such instead of being assigned to any line.

    Returns (items, unallocated): `items` is one row per order line with the
    exact attributed dispatched qty; `unallocated` carries every dispatch qty
    that could not be safely attributed so no data is hidden.
    """
    stmt = (select(SalesOrder, SalesOrderLine)
            .join(SalesOrderLine, SalesOrderLine.order_id == SalesOrder.id)
            .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc()))
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if date_from:
        stmt = stmt.where(SalesOrder.order_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(SalesOrder.order_date <= date.fromisoformat(date_to))
    rows = db.execute(stmt).all()
    if not rows:
        return [], []

    order_ids = sorted({o.id for o, _ in rows})

    # (order_id, product_id) -> number of ORDER lines for that product.
    product_line_count: dict[tuple, int] = {}
    for o, ln in rows:
        if ln.product_id is not None:
            key = (o.id, ln.product_id)
            product_line_count[key] = product_line_count.get(key, 0) + 1

    # Dispatch lines of the filtered orders.
    dq = (select(
            DispatchLine.quantity, DispatchLine.product_id,
            DispatchLine.sales_order_line_id, Dispatch.sales_order_id,
            Dispatch.dispatch_no, Dispatch.plant_id,
        )
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .where(Dispatch.sales_order_id.in_(order_ids)))
    dispatch_rows = db.execute(dq).all()

    exact_by_line: dict[tuple, float] = {}       # (order_id, line_id) -> sum
    pool_by_order_product: dict[tuple, float] = {}  # (order_id, product_id) -> sum of unlinked
    pool_meta: dict[tuple, dict] = {}
    for qty, pid, sol_id, so_id, dno, plant_id in dispatch_rows:
        q = float(qty or 0)
        if q == 0:
            continue
        if sol_id is not None:
            key = (so_id, sol_id)
            exact_by_line[key] = exact_by_line.get(key, 0.0) + q
            continue
        if pid is not None:
            key = (so_id, pid)
            pool_by_order_product[key] = pool_by_order_product.get(key, 0.0) + q
            meta = pool_meta.setdefault(key, {"dispatch_nos": set(), "location": None})
            meta["dispatch_nos"].add(dno or "")
            meta["location"] = _location_name(db, plant_id)

    orders_by_id = {o.id: o for o, _ in rows}
    items = []
    for o, ln in rows:
        ordered = float(ln.quantity or 0)
        exact = exact_by_line.get((o.id, ln.id), 0.0)
        extra = 0.0
        unallocated_for_row = 0.0
        if ln.product_id is not None:
            key = (o.id, ln.product_id)
            pool = pool_by_order_product.get(key, 0.0)
            if pool:
                if product_line_count[key] == 1:
                    extra = pool
                else:
                    # Only the first order line of this product carries the
                    # unattributable qty marker; the aggregate lives in the
                    # `unallocated` collection returned alongside.
                    unallocated_for_row = pool
        disp = exact + extra
        if ordered == 0:
            dstatus = "Not Dispatched"
        elif disp >= ordered:
            dstatus = "Completed"
        elif disp > 0:
            dstatus = "Partially Dispatched"
        else:
            dstatus = "Not Dispatched"
        items.append({
            "order_id": o.id, "order_no": o.order_no, "order_type": o.order_type.value,
            "customer_id": o.customer_id, "customer": o.customer.name if o.customer else None,
            "order_date": o.order_date.isoformat(), "period": f"{o.order_date.year}-{o.order_date.month:02d}",
            "customer_po_no": ln.customer_po_no or o.customer_po_no or "",
            "product_id": ln.product_id, "model": ln.product.model if ln.product else None,
            "item_code": ln.product.item_code if ln.product else (ln.description or ""),
            "ordered_qty": ordered, "dispatched_qty": round(disp, 4),
            "balance_qty": round(ordered - disp, 4),
            "exact_dispatched": round(exact, 4),
            "unallocated_qty": round(unallocated_for_row, 4),
            "delivery_status": dstatus,
        })

    # Unlinked dispatch quantities that cannot be safely attributed to a single
    # order line (order has multiple lines for the same product).
    unallocated = []
    for (so_id, pid), pool in sorted(pool_by_order_product.items()):
        if product_line_count.get((so_id, pid), 0) > 1:
            meta = pool_meta.get((so_id, pid), {})
            so = orders_by_id.get(so_id)
            unallocated.append({
                "order_id": so_id,
                "order_no": so.order_no if so else str(so_id),
                "customer_id": so.customer_id if so else None,
                "customer": so.customer.name if (so and so.customer) else None,
                "product_id": pid,
                "dispatch_no": ", ".join(sorted(meta.get("dispatch_nos", set()))),
                "location": meta.get("location"),
                "quantity": round(pool, 4),
            })
    return items, unallocated


def _location_name(db: Session, plant_id):
    if plant_id is None:
        return "Main Store"
    p = db.get(Plant, plant_id)
    return p.name if p else f"plant {plant_id}"


@router.get("/delivery")
def delivery_report(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    customer_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    status: str = "",
):
    """Delivery report: classify each order line as Completed / Partially
    Dispatched / Not Dispatched, plus a per-customer rollup. Dispatch quantities
    are attributed per line (exact via sales_order_line_id, product-identity
    pool only when provable); anything unattributable is reported separately in
    `unallocated` instead of being guessed (C4).
    """
    items, unallocated = _delivery_rows(db, customer_id=customer_id, date_from=date_from, date_to=date_to)
    if status:
        items = [i for i in items if i["delivery_status"] == status]

    # per-customer rollup
    by = {}
    for i in items:
        key = i["customer_id"]
        e = by.setdefault(key, {
            "customer_id": key, "customer": i["customer"],
            "orders": set(), "ordered": 0.0, "dispatched": 0.0, "balance": 0.0,
            "completed": 0, "partial": 0, "not_dispatched": 0,
        })
        e["orders"].add(i["order_id"])
        e["ordered"] += i["ordered_qty"]
        e["dispatched"] += i["dispatched_qty"]
        e["balance"] += i["balance_qty"]
        if i["delivery_status"] == "Completed":
            e["completed"] += 1
        elif i["delivery_status"] == "Partially Dispatched":
            e["partial"] += 1
        else:
            e["not_dispatched"] += 1
    summary = []
    for e in by.values():
        e["ordered"] = round(e["ordered"], 4)
        e["dispatched"] = round(e["dispatched"], 4)
        e["balance"] = round(e["balance"], 4)
        e["order_count"] = len(e["orders"])
        e["delivery_pct"] = round(e["dispatched"] / e["ordered"], 4) if e["ordered"] else 0.0
        summary.append({k: (len(v) if isinstance(v, set) else v) for k, v in e.items()})
    summary.sort(key=lambda x: -(x.get("ordered") or 0))

    total_ordered = round(sum(x["ordered_qty"] for x in items), 4)
    total_dispatched = round(sum(x["dispatched_qty"] for x in items), 4)
    unallocated_total = round(sum(u["quantity"] for u in unallocated), 4)
    status_count = {}
    for i in items:
        status_count[i["delivery_status"]] = status_count.get(i["delivery_status"], 0) + 1
    return {
        "items": items,
        "summary": summary,
        "total": len(items),
        "unallocated": unallocated,
        "totals": {
            "ordered": total_ordered,
            "dispatched": total_dispatched,
            "balance": round(total_ordered - total_dispatched, 4),
            "unallocated": unallocated_total,
            "by_status": status_count,
        },
    }


@router.get("/delivery/csv")
def delivery_csv(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    customer_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
):
    items, unallocated = _delivery_rows(db, customer_id=customer_id, date_from=date_from, date_to=date_to)
    headers = ["Order No", "Customer", "Order Date", "PO No", "Product", "Item Code",
               "Ordered Qty", "Dispatched Qty", "Balance", "Delivery Status"]
    data = [[i["order_no"], i["customer"] or "", i["order_date"], i["customer_po_no"],
             i["model"] or "", i["item_code"], i["ordered_qty"], i["dispatched_qty"],
             i["balance_qty"], i["delivery_status"]] for i in items]
    for u in unallocated:
        data.append([u["order_no"], u["customer"] or "", "", "",
                     "(unallocated)", str(u["product_id"] or ""),
                     0, u["quantity"], -u["quantity"], "Unallocated"])
    return _csv_response(headers, data, "delivery_report.csv")


# ---------------------------------------------------------------------------
# Order PDF (Phase Orders Department)
# ---------------------------------------------------------------------------
def _order_dispatch_qty(db: Session, o: SalesOrder) -> float:
    """Order-level dispatched quantity using the same aggregation as the
    Orders module (preserves existing business calculation)."""
    return db.scalar(
        select(func.coalesce(func.sum(DispatchLine.quantity), 0))
        .select_from(Dispatch)
        .join(DispatchLine, DispatchLine.dispatch_id == Dispatch.id)
        .where(Dispatch.sales_order_id == o.id)
    ) or 0.0 if o.order_type == OrderType.oem else 0.0


@router.get("/orders/{order_id}/pdf")
def order_pdf(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Download a single order as a branded PDF."""
    o = db.get(SalesOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=40, leftMargin=40,
                            topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    story = []

    # Header
    story.append(Paragraph("<b>Kalika Enterprises</b>", styles["Title"]))
    story.append(Paragraph("Kalika ERP — Order Detail", styles["Heading3"]))
    story.append(Spacer(1, 12))

    customer = o.customer
    contact = o.customer_contact or (customer.phone if customer else "")
    email = o.customer_email or (customer.email if customer else "")
    salesperson = o.salesperson.name if o.salesperson else ""

    meta = [
        ["Customer", customer.name if customer else (o.customer_name or "—"), "SO No", o.order_no or "—"],
        ["Contact", contact or "—", "PO No", o.customer_po_no or "—"],
        ["Email", email or "—", "Order Date", str(o.order_date or "—")],
        ["Salesperson", salesperson or "—", "Order Type", o.order_type.value if o.order_type else "—"],
    ]
    meta_table = Table(meta, colWidths=[80, 200, 80, 120])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f8fafc")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#334155")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e7e8eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 16))

    # Lines
    headers = ["Item Code", "Model", "Schedule", "Ask Till", "Dispatch", "% Comp", "Balance", "Opening"]
    disp_total = _order_dispatch_qty(db, o)
    rows = []
    for ln in o.lines:
        item_code = ln.item_code or (ln.product.item_code if ln.product else "")
        model = ln.product.model if ln.product else (ln.description or "")
        rows.append([
            item_code or "—",
            model or "—",
            _fmt_pdf_num(ln.schedule_qty),
            _fmt_pdf_num(ln.ask_till_date),
            _fmt_pdf_num(disp_total) if o.order_type == OrderType.oem else "—",
            f"{(ln.completion_pct or 0) * 100:.1f}%" if ln.completion_pct is not None else "—",
            _fmt_pdf_num(ln.balance_qty),
            _fmt_pdf_num(ln.opening_stock),
        ])

    if rows:
        line_table = Table([headers] + rows, repeatRows=1)
        line_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e7e8eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(line_table)
    else:
        story.append(Paragraph("No order lines.", styles["Normal"]))

    if o.remarks:
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"<b>Remarks:</b> {o.remarks}", styles["Normal"]))

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    safe_name = "".join(c for c in (o.order_no or str(o.id)) if c.isalnum() or c in "-_").strip() or str(o.id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=order_{safe_name}.pdf"},
    )


def _fmt_pdf_num(v):
    """Format numeric value for PDF tables; blank for None."""
    if v is None:
        return "—"
    try:
        n = float(v)
        return f"{n:,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)
