"""Kalika Enterprises ERP - FastAPI application entrypoint."""
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from .config import settings
from .database import Base, engine, check_db_health
from . import models  # noqa: F401  (register models)
from .routers import (
    auth, users, meta, customers, suppliers, products, plants, raw_materials,
    purchases, inventory, production, orders, dispatch, plans, dashboard, reports,
    requirements, salespersons, local_orders, bom, alerts,
    material_requirements, fulfilment, stock_flow,
)

# Schema additions create_all cannot apply to pre-existing tables (idempotent ALTER).
_COLUMN_MIGRATIONS = [
    ("raw_material_balances", "min_stock", "DOUBLE PRECISION"),
    ("raw_material_balances", "max_stock", "DOUBLE PRECISION"),
    ("sales_order_lines", "less", "DOUBLE PRECISION"),
    ("sales_order_lines", "item_code", "VARCHAR(120) DEFAULT ''"),
    ("sales_order_lines", "schedule_qty", "DOUBLE PRECISION"),
    ("sales_order_lines", "ask_till_date", "DOUBLE PRECISION"),
    ("sales_order_lines", "completion_pct", "DOUBLE PRECISION"),
    ("sales_order_lines", "balance_qty", "DOUBLE PRECISION"),
    ("sales_order_lines", "opening_stock", "DOUBLE PRECISION"),
    ("sales_order_lines", "uom", "VARCHAR(30) DEFAULT ''"),
    ("sales_orders", "customer_name", "VARCHAR(255)"),
    ("sales_orders", "customer_contact", "VARCHAR(60) DEFAULT ''"),
    ("sales_orders", "customer_email", "VARCHAR(160) DEFAULT ''"),
    ("sales_orders", "local_order_type", "VARCHAR(20) DEFAULT 'TRADING'"),
    ("sales_orders", "so_no", "VARCHAR(120)"),
    ("purchase_orders", "supplier_name", "VARCHAR(255)"),
    ("purchase_order_lines", "item_code", "VARCHAR(120)"),
    ("stock_transfers", "customer_name", "VARCHAR(255)"),
    ("customer_dispatches", "customer_name", "VARCHAR(255)"),
    ("bill_of_materials", "bom_id", "INTEGER"),
    ("plans", "sales_order_id", "INTEGER"),
    ("purchase_order_lines", "uom", "VARCHAR(30) DEFAULT ''"),
    ("purchase_order_lines", "tax_percent", "DOUBLE PRECISION"),
    ("purchase_order_lines", "discount_percent", "DOUBLE PRECISION"),
]

# Internal stock locations seeded as Plants (Main Store = plant_id NULL).
_LOCATION_PLANTS = ["Dispatch", "Production"]


def _ensure_columns() -> None:
    with engine.begin() as conn:
        for table, column, ddl in _COLUMN_MIGRATIONS:
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
            )
        # Backfill derived fields ONLY where never computed (idempotent); existing
        # historical values are left untouched.
        conn.execute(text(
            "UPDATE raw_material_balances "
            "SET balance_qty = ROUND(CAST(COALESCE(schedule_qty, 0) - COALESCE(inward_qty, 0) AS NUMERIC), 4), "
            "    completion_pct = CASE WHEN COALESCE(schedule_qty, 0) <> 0 "
            "         THEN ROUND(CAST(COALESCE(inward_qty, 0) / COALESCE(schedule_qty, 0) AS NUMERIC), 4) ELSE 0 END "
            "WHERE schedule_qty IS NOT NULL AND balance_qty IS NULL"
        ))


def _ensure_order_status_enum() -> None:
    """Add the manual 'Production Completed' value to the sales_orders.status
    enum type.

    Local Order status is user-controlled; 'Production Completed' is the manual
    gate between production and dispatch. create_all cannot alter an existing
    Postgres enum, so add the value idempotently (additive; no data touched).
    No-op on non-Postgres engines (SQLite stores enums as VARCHAR).
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        type_name = conn.execute(text(
            "SELECT t.typname FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_type t ON t.oid = a.atttypid "
            "WHERE c.relname = 'sales_orders' AND a.attname = 'status'"
        )).scalar()
        if not type_name:
            return
        present = conn.execute(text(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = :t AND e.enumlabel = :v"
        ), {"t": type_name, "v": "production_completed"}).scalar()
    if present:
        return
    # ADD VALUE cannot run inside a transaction block on older Postgres —
    # use an autocommit connection.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'ALTER TYPE "{type_name}" ADD VALUE \'production_completed\''))
        conn.execute(text(f'ALTER TYPE "{type_name}" ADD VALUE \'partially_dispatched\''))
        conn.execute(text(f'ALTER TYPE "{type_name}" ADD VALUE \'ready_for_dispatch\''))
        conn.execute(text(f'ALTER TYPE "{type_name}" ADD VALUE \'purchase_required\''))


def _ensure_number_indexes() -> None:
    """SO Number (sales_orders.order_no) and PO Number (purchase_orders.po_number)
    are manual business-document references, not system-generated unique keys.
    The database internal ID (primary key) remains the unique identifier. This
    idempotent migration drops any prior UNIQUE constraint/index on those two
    reference columns and recreates them as ordinary (non-unique) search indexes
    so the same document number may legitimately repeat across business contexts.
    No business data is touched and no other schema is modified."""
    with engine.begin() as conn:
        conn.execute(text("""
            DO $$
            DECLARE r RECORD;
            BEGIN
                FOR r IN
                    SELECT t.relname AS tbl, con.conname AS cname
                    FROM pg_constraint con
                    JOIN pg_class t ON t.oid = con.conrelid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(con.conkey)
                    WHERE t.relname IN ('sales_orders', 'purchase_orders')
                      AND con.contype = 'u'
                      AND a.attname IN ('order_no', 'po_number')
                LOOP
                    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', r.tbl, r.cname);
                END LOOP;
                FOR r IN
                    SELECT indexname AS iname
                    FROM pg_indexes
                    WHERE tablename IN ('sales_orders', 'purchase_orders')
                      AND indexdef ILIKE '%UNIQUE%'
                      AND (indexdef ILIKE '%(order_no)%' OR indexdef ILIKE '%(po_number)%')
                LOOP
                    EXECUTE format('DROP INDEX IF EXISTS %I', r.iname);
                END LOOP;
            END $$;
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sales_orders_order_no ON sales_orders (order_no)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_purchase_orders_po_number ON purchase_orders (po_number)"
        ))


def _ensure_inventory_unique() -> None:
    """C3: guarantee ONE inventory row per (product_id, plant_id), including the
    NULL plant (Main Store) case.

    The existing uq_inventory_product_plant index covers only non-NULL
    plant_ids (Postgres treats NULLs as distinct values), so a Main-Store row
    could silently be duplicated. This idempotent, additive migration first
    PRE-CHECKS the live data: if any duplicate Main-Store row already exists the
    index is NOT created and the duplicates are logged for manual resolution
    (never guessed / never merged). Otherwise a partial unique index enforces
    the invariant going forward. No business data is touched."""
    with engine.begin() as conn:
        dups = conn.execute(text("""
            SELECT product_id, COUNT(*) AS n
            FROM inventory
            WHERE plant_id IS NULL
            GROUP BY product_id
            HAVING COUNT(*) > 1
            ORDER BY product_id
        """)).fetchall()
        if dups:
            log.error(
                "Inventory uniqueness NOT enforced: %d Main-Store product(s) already have "
                "duplicate rows (product_ids: %s). Resolve them first, then re-run.",
                len(dups), [r[0] for r in dups])
            return
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_product_main "
            "ON inventory (product_id) WHERE plant_id IS NULL"
        ))


def _ensure_locations() -> None:
    """Idempotent seed of internal stock locations as Plants
    (Dispatch, Production). Main Store stays plant_id NULL. Never duplicates."""
    from .database import SessionLocal
    from .models import Plant
    with SessionLocal() as session:
        added = 0
        for name in _LOCATION_PLANTS:
            exists = session.scalar(select(Plant.id).where(Plant.name == name))
            if not exists:
                session.add(Plant(name=name, code=name.upper(),
                                  description="Internal stock location"))
                added += 1
        session.commit()
        if added:
            log.info("Seeded internal locations: %s", _LOCATION_PLANTS)


log = logging.getLogger("kalika")

app = FastAPI(
    title="Kalika Enterprises ERP",
    description="Manufacturing + B2B trading ERP for Kalika Enterprises.",
    version="1.0.0",
)

# CORS — allow production frontend URL + localhost for dev
_extra_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_cors = list({*settings.CORS_ORIGINS, *_extra_origins, "http://localhost:5173", "http://127.0.0.1:5173"})
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    log.info("Kalika ERP v%s starting …", settings.APP_VERSION)
    try:
        host = settings.database_url.split("@")[-1].split("?")[0] if "@" in settings.database_url else "local"
        log.info("Database target: %s", host)
    except Exception:
        pass
    # create_all is idempotent; non-fatal so the container starts even if the
    # DB is briefly unreachable (health endpoint reports real status).
    try:
        Base.metadata.create_all(bind=engine)
        log.info("Schema verified / tables created.")
    except Exception as exc:
        log.error("create_all failed (recoverable): %s", exc)
    # Existing databases were created before min/max stock existed; add columns
    # idempotently (fresh DBs already have them via the model).
    try:
        _ensure_columns()
        log.info("Column migrations applied.")
    except Exception as exc:
        log.error("column migration failed (recoverable): %s", exc)
    # Manual 'Production Completed' Local Order status (existing Postgres enum).
    try:
        _ensure_order_status_enum()
    except Exception as exc:
        log.error("order-status enum migration failed (recoverable): %s", exc)
    # SO/PO numbers became manual business references; drop the legacy UNIQUE
    # indexes on them (idempotent, data untouched). Recreated as plain indexes.
    try:
        _ensure_number_indexes()
        log.info("SO/PO number unique indexes released.")
    except Exception as exc:
        log.error("SO/PO number index migration failed (recoverable): %s", exc)
    # Internal stock locations (Dispatch, Production) — idempotent seed.
    try:
        _ensure_locations()
    except Exception as exc:
        log.error("location seed failed (recoverable): %s", exc)
    # C3: one inventory row per (product_id, plant_id) incl. Main Store (NULL
    # plant) — duplicate PRE-CHECKED; additive + idempotent, no data touched.
    try:
        _ensure_inventory_unique()
        log.info("Inventory uniqueness for Main Store enforced.")
    except Exception as exc:
        log.error("inventory uniqueness migration failed (recoverable): %s", exc)
    # Reconcile purchase/production shortage requirements + alerts on boot so
    # the Alert Centre is current even for data imported or changed outside the
    # API. Dedupe-safe and non-fatal (best-effort).
    try:
        from .database import SessionLocal
        from .services.business import sync_purchase_shortages
        with SessionLocal() as s:
            r = sync_purchase_shortages(s)
            log.info("Purchase shortage sync on startup: %s", r)
    except Exception as exc:
        log.error("startup shortage sync failed (recoverable): %s", exc)


@app.get("/", include_in_schema=False)
def root():
    if _FRONTEND_DIST.exists():
        return _serve_frontend("")
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["meta"])
def health():
    db = check_db_health()
    return {
        "status": "ok" if db["status"] == "ok" else "degraded",
        "app": "kalika-erp",
        "version": settings.APP_VERSION,
        "database": db,
    }


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(meta.router)
app.include_router(customers.router)
app.include_router(suppliers.router)
app.include_router(products.router)
app.include_router(plants.router)
app.include_router(raw_materials.router)
app.include_router(purchases.router)
app.include_router(inventory.router)
app.include_router(production.router)
app.include_router(orders.router)
app.include_router(dispatch.router)
app.include_router(plans.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(requirements.router)
app.include_router(salespersons.router)
app.include_router(local_orders.router)
app.include_router(bom.router)
app.include_router(alerts.router)
app.include_router(material_requirements.router)
app.include_router(fulfilment.router)
app.include_router(stock_flow.locations_router)
app.include_router(stock_flow.transfer_router)
app.include_router(stock_flow.dispatch_router)


# Serve the built React app in production mode (frontend/dist mounted next to backend).
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _serve_frontend(path: str):
    index = _FRONTEND_DIST / "index.html"
    if not index.exists():
        return RedirectResponse(url="/docs")
    target = _FRONTEND_DIST / path
    if target.is_file():
        return FileResponse(target)
    return FileResponse(index)


@app.middleware("http")
async def spa_html_navigation(request: Request, call_next):
    """Serve the SPA for real browser navigations.

    API routers (e.g. /production, /orders, /local-orders) are registered
    before the SPA catch-all, so a hard refresh on a page URL would otherwise
    hit an authenticated API route and return 401 {"detail":"Not authenticated"}.
    Browser navigations send Accept: text/html; API calls from the SPA send
    Accept: application/json, so this only affects genuine page loads.
    """
    accept = request.headers.get("accept", "")
    path = request.url.path
    if (
        request.method == "GET"
        and "text/html" in accept
        and _FRONTEND_DIST.exists()
        and path not in ("/", "/health", "/docs", "/redoc", "/openapi.json")
        and not path.startswith("/assets/")
    ):
        index = _FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
    return await call_next(request)


if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        return _serve_frontend(full_path)