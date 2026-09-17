"""SQLAlchemy models for the Kalika Enterprises ERP.

Schema designed from the actual Excel source (Kalika_inventory/Daily Report Aug-26.xlsx):
Supplier -> Purchase -> RawMaterial -> Store -> Production -> Finished Product -> Order -> Dispatch -> Completed.
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, Float, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    store = "store"
    production = "production"
    dispatch = "dispatch"
    viewer = "viewer"


class ProductCategory(str, enum.Enum):
    raw_material = "raw_material"
    finished = "finished"
    store = "store"
    trading = "trading"


class ProductSourceType(str, enum.Enum):
    manufactured = "MANUFACTURED"
    trading = "TRADING"
    mixed = "MIXED"
    unknown = "UNKNOWN"


class OrderType(str, enum.Enum):
    oem = "OEM"
    trading = "TRADING"
    manufacturing = "MANUFACTURING"
    local = "LOCAL"


class ConfirmationStatus(str, enum.Enum):
    confirmed = "CONFIRMED"
    needs_business_confirmation = "NEEDS_BUSINESS_CONFIRMATION"


class OrderStatus(str, enum.Enum):
    new = "New"
    confirmed = "Confirmed"
    in_production = "In Production"
    ready = "Ready"
    dispatched = "Dispatched"
    completed = "Completed"
    cancelled = "Cancelled"


class ProductionStatus(str, enum.Enum):
    planned = "Planned"
    in_production = "In Production"
    completed = "Completed"
    cancelled = "Cancelled"


class DispatchStatus(str, enum.Enum):
    pending = "Pending"
    in_transit = "In Transit"
    delivered = "Delivered"
    partial = "Partially Dispatched"
    completed = "Completed"


class PurchaseStatus(str, enum.Enum):
    draft = "Draft"
    ordered = "Ordered"
    partially_received = "Partially Received"
    received = "Received"
    cancelled = "Cancelled"


class MovementType(str, enum.Enum):
    receipt = "RECEIPT"
    issue = "ISSUE"
    consumption = "CONSUMPTION"
    production_output = "PRODUCTION_OUTPUT"
    dispatch = "DISPATCH"
    adjustment = "ADJUSTMENT"
    opening = "OPENING"
    purchase_receipt = "PURCHASE_RECEIPT"
    rm_consumption = "RM_CONSUMPTION"
    transfer = "TRANSFER"


class PlanType(str, enum.Enum):
    production = "PRODUCTION_PLAN"
    dispatch = "DISPATCH_PLAN"


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.viewer, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(60), default="", index=True)
    company: Mapped[str] = mapped_column(String(255), default="")
    contact_person: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    gstin: Mapped[str] = mapped_column(String(40), default="")
    is_plant: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    confirmation_status: Mapped[str] = mapped_column(String(60), default="CONFIRMED", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomerAlias(Base):
    """Original source spelling of a customer name (never silently merged)."""

    __tablename__ = "customer_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    alias: Mapped[str] = mapped_column(String(255), index=True)
    match_rule: Mapped[str] = mapped_column(String(80), default="EXACT_SOURCE")
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer: Mapped[Customer] = relationship()


class Salesperson(Base):
    """Salesperson / owner names (DISPATCH col A, PLANE col A). Never a customer."""

    __tablename__ = "salespersons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReportingPeriod(Base):
    """Monthly reporting period (e.g. August 2026) with workbook metadata."""

    __tablename__ = "reporting_periods"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_period_year_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    working_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_comp: Mapped[float | None] = mapped_column(Float, nullable=True)
    balance_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_file: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ImportBatch(Base):
    """One isolated migration run. Live data is never touched by a batch."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file: Mapped[str] = mapped_column(String(255), default="")
    period_label: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(40), default="IMPORTED", index=True)
    # IMPORTED -> VALIDATED -> READY_FOR_PROMOTION / NOT_READY_FOR_PROMOTION
    hard_errors: Mapped[str] = mapped_column(Text, default="")
    warnings: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(60), default="", index=True)
    company: Mapped[str] = mapped_column(String(255), default="")
    contact_person: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    gstin: Mapped[str] = mapped_column(String(40), default="")
    materials: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("item_code", "model", name="uq_product_code_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_code: Mapped[str] = mapped_column(String(80), default="", index=True)
    model: Mapped[str] = mapped_column(String(500), index=True)
    name: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[ProductCategory] = mapped_column(
        Enum(ProductCategory), default=ProductCategory.store, index=True
    )
    uom: Mapped[str] = mapped_column(String(30), default="Each")
    min_stock_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[ProductSourceType] = mapped_column(
        Enum(ProductSourceType), default=ProductSourceType.unknown, index=True
    )
    family: Mapped[str] = mapped_column(String(120), default="", index=True)
    sourcing_note: Mapped[str] = mapped_column(Text, default="")
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    stock: Mapped[list[Inventory]] = relationship(back_populates="product", cascade="all, delete-orphan")


class ProductAlias(Base):
    """Alternate/legacy identifier for a product (typo codes, float codes,
    leading-zero variants). Linkage only — no silent merging."""

    __tablename__ = "product_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    alias_code: Mapped[str] = mapped_column(String(120), default="", index=True)
    alias_model: Mapped[str] = mapped_column(String(500), default="")
    match_rule: Mapped[str] = mapped_column(String(80), default="EXACT_SOURCE")
    status: Mapped[str] = mapped_column(String(40), default="SUGGESTED")
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Product] = relationship()


class Plant(Base):
    """Ship-to location / customer plant (G-6, C-33, CPG, EATON, ...)."""

    __tablename__ = "plants"
    __table_args__ = (UniqueConstraint("name", name="uq_plant_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    code: Mapped[str] = mapped_column(String(60), default="", index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    customer: Mapped[Customer | None] = relationship()


# ---------------------------------------------------------------------------
# Raw material & purchase
# ---------------------------------------------------------------------------
class RawMaterialBalance(Base):
    """Raw-material monthly position from the RAW MATERIAL sheet."""

    __tablename__ = "raw_material_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    schedule_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_till_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    inward_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    completion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    balance_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_stock: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_stock: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_stock: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    product: Mapped[Product] = relationship()


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(120), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    order_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    status: Mapped[PurchaseStatus] = mapped_column(
        Enum(PurchaseStatus), default=PurchaseStatus.ordered, index=True
    )
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lines: Mapped[list[PurchaseOrderLine]] = relationship(back_populates="po", cascade="all, delete-orphan")
    supplier: Mapped[Supplier | None] = relationship()


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    item_code: Mapped[str] = mapped_column(String(120), default="", index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    received_qty: Mapped[float] = mapped_column(Float, default=0)
    rate: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    uom: Mapped[str] = mapped_column(String(30), default="")
    tax_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("product_id", "plant_id", name="uq_inventory_product_plant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True, index=True)
    opening_stock: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", default=0)
    received_qty: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", default=0)
    issued_qty: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", default=0)
    current_stock: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", default=0)
    min_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product: Mapped[Product] = relationship(back_populates="stock")
    plant: Mapped[Plant | None] = relationship()


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (Index("ix_movement_product_date", "product_id", "transaction_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True, index=True)
    movement_type: Mapped[MovementType] = mapped_column(Enum(MovementType), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    transaction_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    ref_type: Mapped[str] = mapped_column(String(80), default="")
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Product] = relationship()
    plant: Mapped[Plant | None] = relationship()


# ---------------------------------------------------------------------------
# Stock transfers (Main Store -> Dispatch / Production)
# ---------------------------------------------------------------------------
class StockTransfer(Base):
    """Location-to-location stock movement document.

    Main Store is plant_id = NULL (existing convention). Internal locations
    (Dispatch, Production) are seeded Plants. Customer is optional transaction
    reference only — no allocation/reservation concept.
    """

    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_no: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    from_plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True, index=True)
    to_plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    transfer_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lines: Mapped[list[StockTransferLine]] = relationship(back_populates="transfer", cascade="all, delete-orphan")
    from_plant: Mapped[Plant | None] = relationship(foreign_keys=[from_plant_id])
    to_plant: Mapped[Plant | None] = relationship(foreign_keys=[to_plant_id])
    customer: Mapped[Customer | None] = relationship()


class StockTransferLine(Base):
    __tablename__ = "stock_transfer_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("stock_transfers.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    item_code: Mapped[str] = mapped_column(String(120), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)

    transfer: Mapped[StockTransfer] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


# ---------------------------------------------------------------------------
# Simple customer dispatch (stock-based, additive to Sales-Order Dispatch)
# ---------------------------------------------------------------------------
class CustomerDispatch(Base):
    """Actual dispatch of stock OUT of the Dispatch location to a customer.

    Each dispatch is an independent, date-wise historical transaction. Customer
    is optional (transaction reference). Independent from the sales-order-driven
    `Dispatch` module which remains untouched.
    """

    __tablename__ = "customer_dispatches"

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_no: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True, index=True)
    dispatch_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lines: Mapped[list[CustomerDispatchLine]] = relationship(back_populates="dispatch", cascade="all, delete-orphan")
    customer: Mapped[Customer | None] = relationship()
    plant: Mapped[Plant | None] = relationship()


class CustomerDispatchLine(Base):
    __tablename__ = "customer_dispatch_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("customer_dispatches.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    item_code: Mapped[str] = mapped_column(String(120), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)

    dispatch: Mapped[CustomerDispatch] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------
class ProductionOrder(Base):
    __tablename__ = "production_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    salesperson_id: Mapped[int | None] = mapped_column(ForeignKey("salespersons.id"), nullable=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True, index=True)
    section: Mapped[str] = mapped_column(String(120), default="", index=True)
    schedule_qty: Mapped[float] = mapped_column(Float, default=0)
    ask_till_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    produced_qty: Mapped[float] = mapped_column(Float, default=0)
    completion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    balance_qty: Mapped[float] = mapped_column(Float, default=0)
    opening_stock: Mapped[float] = mapped_column(Float, default=0)
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    period_id: Mapped[int | None] = mapped_column(ForeignKey("reporting_periods.id"), nullable=True, index=True)
    status: Mapped[ProductionStatus] = mapped_column(
        Enum(ProductionStatus), default=ProductionStatus.planned, index=True
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Product] = relationship()
    customer: Mapped[Customer | None] = relationship()
    salesperson: Mapped[Salesperson | None] = relationship()
    sales_order: Mapped[SalesOrder | None] = relationship()
    movements: Mapped[list[ProductionMovement]] = relationship(
        back_populates="production_order", cascade="all, delete-orphan"
    )


class ProductionMovement(Base):
    __tablename__ = "production_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    production_date: Mapped[date] = mapped_column(Date, index=True)
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)

    production_order: Mapped[ProductionOrder] = relationship(back_populates="movements")


# ---------------------------------------------------------------------------
# Sales orders
# ---------------------------------------------------------------------------
class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(120), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    order_type: Mapped[OrderType] = mapped_column(Enum(OrderType), default=OrderType.oem, index=True)
    local_order_type: Mapped[str] = mapped_column(String(20), default="TRADING")
    customer_po_no: Mapped[str] = mapped_column(String(120), default="", index=True)
    so_no: Mapped[str] = mapped_column(String(120), default="")
    salesperson_id: Mapped[int | None] = mapped_column(ForeignKey("salespersons.id"), nullable=True)
    period_id: Mapped[int | None] = mapped_column(ForeignKey("reporting_periods.id"), nullable=True, index=True)
    order_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    required_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.new, index=True)
    total_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    remarks: Mapped[str] = mapped_column(Text, default="")
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer: Mapped[Customer | None] = relationship()
    salesperson: Mapped[Salesperson | None] = relationship()
    lines: Mapped[list[SalesOrderLine]] = relationship(back_populates="order", cascade="all, delete-orphan")
    dispatches: Mapped[list[Dispatch]] = relationship(back_populates="sales_order")


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    item_code: Mapped[str] = mapped_column(String(120), default="", index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    customer_po_no: Mapped[str] = mapped_column(String(120), default="")
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    less: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)

    order: Mapped[SalesOrder] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
class Dispatch(Base):
    __tablename__ = "dispatches"

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_no: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plants.id"), nullable=True, index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True, index=True)
    salesperson_id: Mapped[int | None] = mapped_column(ForeignKey("salespersons.id"), nullable=True)
    sales_person: Mapped[str] = mapped_column(String(120), default="")
    period_id: Mapped[int | None] = mapped_column(ForeignKey("reporting_periods.id"), nullable=True, index=True)
    schedule_qty: Mapped[float] = mapped_column(Float, default=0)
    ask_till_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    dispatched_qty: Mapped[float] = mapped_column(Float, default=0)
    completion_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    balance_qty: Mapped[float] = mapped_column(Float, default=0)
    opening_stock: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[DispatchStatus] = mapped_column(
        Enum(DispatchStatus), default=DispatchStatus.pending, index=True
    )
    dispatch_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(120), default="")
    transport_details: Mapped[str] = mapped_column(Text, default="")
    report_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    customer: Mapped[Customer | None] = relationship()
    plant: Mapped[Plant | None] = relationship()
    salesperson: Mapped[Salesperson | None] = relationship()
    sales_order: Mapped[SalesOrder | None] = relationship(back_populates="dispatches")
    lines: Mapped[list[DispatchLine]] = relationship(back_populates="dispatch", cascade="all, delete-orphan")


class DispatchLine(Base):
    __tablename__ = "dispatch_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    sales_order_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=0)
    dispatch_date: Mapped[date] = mapped_column(Date, index=True)
    rate: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)

    dispatch: Mapped[Dispatch] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


# ---------------------------------------------------------------------------
# Plans (production / dispatch plane)
# ---------------------------------------------------------------------------
class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_type: Mapped[PlanType] = mapped_column(Enum(PlanType), index=True)
    model: Mapped[str] = mapped_column(String(500), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True, index=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    rate: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(80), default="PENDING", index=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True, default=date.today)
    source_excel: Mapped[str] = mapped_column(String(255), default="")
    source_sheet: Mapped[str] = mapped_column(String(120), default="")
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True, index=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    product: Mapped[Product | None] = relationship()
    customer: Mapped[Customer | None] = relationship()
    sales_order: Mapped[SalesOrder | None] = relationship()


# ---------------------------------------------------------------------------
# Purchase requirements (shortage detection engine)
# ---------------------------------------------------------------------------
class PurchaseRequirement(Base):
    """A detected shortage for a customer/order requirement.

    Shortage = required - available. Category derives from product
    source_type: MANUFACTURED -> production, TRADING -> purchase,
    MIXED/UNKNOWN -> decision required (user picks the source).
    Status lifecycle: Pending -> In Progress -> Ordered -> Received -> Completed.
    """

    __tablename__ = "purchase_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), nullable=True, index=True)
    sales_order_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    required_qty: Mapped[float] = mapped_column(Float, default=0)
    available_qty: Mapped[float] = mapped_column(Float, default=0)
    shortage_qty: Mapped[float] = mapped_column(Float, default=0)
    category: Mapped[str] = mapped_column(String(40), default="PURCHASE", index=True)
    # PRODUCTION | PURCHASE | DECISION
    action: Mapped[str] = mapped_column(String(40), default="REQUIRED")
    requirement_type: Mapped[str] = mapped_column(String(40), default="TRADING_PRODUCT", index=True)
    status: Mapped[str] = mapped_column(String(40), default="Pending", index=True)
    source_type: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product: Mapped[Product] = relationship()
    customer: Mapped[Customer | None] = relationship()
    sales_order: Mapped[SalesOrder | None] = relationship()


# ---------------------------------------------------------------------------
# Bill of Materials (BOM)
# ---------------------------------------------------------------------------
class BOM(Base):
    """BOM header — ONE BOM (unique BOM Code) groups MULTIPLE raw material lines."""
    __tablename__ = "boms"

    id: Mapped[int] = mapped_column(primary_key=True)
    bom_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_date: Mapped[date] = mapped_column(Date, default=date.today)
    version: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product: Mapped[Product] = relationship(foreign_keys=[product_id])
    lines: Mapped[list[BillOfMaterial]] = relationship(
        back_populates="bom", cascade="all, delete-orphan", foreign_keys="BillOfMaterial.bom_id",
    )


class BillOfMaterial(Base):
    """Raw Material line under a BOM (product → raw material mapping).
    User-entered, never invented."""
    __tablename__ = "bill_of_materials"
    __table_args__ = (UniqueConstraint("product_id", "raw_material_product_id", "version",
                                       name="uq_bom_product_rm_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bom_id: Mapped[int | None] = mapped_column(ForeignKey("boms.id"), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    raw_material_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity_per_unit: Mapped[float] = mapped_column(Float, default=0)
    uom: Mapped[str] = mapped_column(String(30), default="KG")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_date: Mapped[date] = mapped_column(Date, default=date.today)
    version: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product: Mapped[Product] = relationship(foreign_keys=[product_id])
    raw_material: Mapped[Product] = relationship(foreign_keys=[raw_material_product_id])
    bom: Mapped[BOM | None] = relationship(back_populates="lines", foreign_keys=[bom_id])


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
class AlertType(str, enum.Enum):
    purchase_required = "PURCHASE_REQUIRED"
    raw_material_shortage = "RAW_MATERIAL_SHORTAGE"
    production_material_shortage = "PRODUCTION_MATERIAL_SHORTAGE"
    stock_shortage = "STOCK_SHORTAGE"
    pending_po = "PENDING_PO"
    over_fulfilled = "OVER_FULFILLED"
    validation_warning = "VALIDATION_WARNING"


class AlertPriority(str, enum.Enum):
    critical = "CRITICAL"
    high = "HIGH"
    medium = "MEDIUM"
    low = "LOW"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[AlertType] = mapped_column(Enum(AlertType), index=True)
    priority: Mapped[AlertPriority] = mapped_column(
        Enum(AlertPriority), default=AlertPriority.medium, index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_role: Mapped[str] = mapped_column(String(60), default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MigrationLog(Base):
    __tablename__ = "migration_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_sheet: Mapped[str] = mapped_column(String(120))
    target_table: Mapped[str] = mapped_column(String(120))
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    assumptions: Mapped[str] = mapped_column(Text, default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(40), default="completed")