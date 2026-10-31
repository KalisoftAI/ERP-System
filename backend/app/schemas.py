"""Pydantic schemas for request/response validation."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .models import (
    DispatchStatus, EmployeeStatus, MovementType, OrderStatus, OrderType, PlanType,
    PRNLineMode, PRNStatus, ProductCategory, ProductionStatus, PurchaseStatus,
    QuotationStatus, QuotationType, UserRole, normalize_quotation_company,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------- Auth -------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(ORMModel):
    id: int
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: str = Field(max_length=160)
    full_name: str = Field(default="", max_length=160)
    password: str = Field(min_length=6, max_length=128)
    role: UserRole = UserRole.viewer


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    # Session policy surfaced to the client so it can enforce timeouts without
    # hard-coding them (seconds). 0 = not configured.
    expires_in: int = 0
    inactivity_seconds: int = 0


# ------------------------- Master -------------------------
class CustomerBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = ""
    company: str = ""
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    gstin: str = ""
    is_plant: bool = False
    notes: str = ""


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    company: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = None
    is_plant: Optional[bool] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerOut(CustomerBase, ORMModel):
    id: int
    is_active: bool
    created_at: datetime


class SupplierBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = ""
    company: str = ""
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    gstin: str = ""
    materials: str = ""
    notes: str = ""


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    company: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = None
    materials: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierOut(SupplierBase, ORMModel):
    id: int
    is_active: bool
    created_at: datetime


class EmployeeBase(BaseModel):
    employee_code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=160)
    mobile: str = ""
    email: str = ""
    department: str = ""
    designation: str = ""
    joining_date: Optional[date] = None
    # Sensitive (admin-only). Plain strings — format is validated in the router so
    # validation errors never echo the submitted value back to the client.
    aadhaar_number: str = ""
    pan_number: str = ""
    bank_account_number: str = ""
    ifsc_code: str = ""
    bank_name: str = ""
    branch_name: str = ""
    # Advanced Edit — statutory / payroll & verification (all optional). Choice
    # fields use plain strings validated in the router (never echo submitted
    # values), dates are optional and nullable.
    pf_applicable: str = ""
    uan: str = ""
    pf_member_id: str = ""
    pf_joining_date: Optional[date] = None
    pf_exit_date: Optional[date] = None
    previous_pf_membership: str = ""
    esic_applicable: str = ""
    esic_ip_number: str = ""
    esic_joining_date: Optional[date] = None
    esic_exit_date: Optional[date] = None
    esic_registration_status: str = ""
    verification_status: str = ""
    verified_by: str = ""
    verification_date: Optional[date] = None
    remarks: str = ""
    supporting_document_ref: str = ""
    job_leave_date: Optional[date] = None
    status: EmployeeStatus = EmployeeStatus.active


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    employee_code: Optional[str] = None
    name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    joining_date: Optional[date] = None
    aadhaar_number: Optional[str] = None
    pan_number: Optional[str] = None
    bank_account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    bank_name: Optional[str] = None
    branch_name: Optional[str] = None
    pf_applicable: Optional[str] = None
    uan: Optional[str] = None
    pf_member_id: Optional[str] = None
    pf_joining_date: Optional[date] = None
    pf_exit_date: Optional[date] = None
    previous_pf_membership: Optional[str] = None
    esic_applicable: Optional[str] = None
    esic_ip_number: Optional[str] = None
    esic_joining_date: Optional[date] = None
    esic_exit_date: Optional[date] = None
    esic_registration_status: Optional[str] = None
    verification_status: Optional[str] = None
    verified_by: Optional[str] = None
    verification_date: Optional[date] = None
    remarks: Optional[str] = None
    supporting_document_ref: Optional[str] = None
    job_leave_date: Optional[date] = None
    status: Optional[EmployeeStatus] = None


class EmployeeOut(EmployeeBase, ORMModel):
    id: int
    created_at: datetime


class ProductBase(BaseModel):
    item_code: str = ""
    model: str = Field(min_length=1, max_length=500)
    name: str = ""
    category: ProductCategory = ProductCategory.store
    uom: str = "Each"
    min_stock_level: Optional[float] = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    item_code: Optional[str] = None
    model: Optional[str] = None
    name: Optional[str] = None
    category: Optional[ProductCategory] = None
    uom: Optional[str] = None
    min_stock_level: Optional[float] = None
    is_active: Optional[bool] = None


class ProductOut(ProductBase, ORMModel):
    id: int
    is_active: bool
    created_at: datetime


class PlantBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str = ""
    customer_id: Optional[int] = None
    description: str = ""


class PlantCreate(PlantBase):
    pass


class PlantUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    customer_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PlantOut(PlantBase, ORMModel):
    id: int
    is_active: bool


# ------------------------- Raw materials -------------------------
class RawMaterialBalanceOut(ORMModel):
    id: int
    product_id: int
    report_date: date
    schedule_qty: Optional[float]
    ask_till_date: Optional[float]
    inward_qty: Optional[float]
    completion_pct: Optional[float]
    balance_qty: Optional[float]
    opening_stock: Optional[float]
    min_stock: Optional[float]
    max_stock: Optional[float]
    notes: str
    product: Optional[ProductOut] = None


class RawMaterialStockSet(BaseModel):
    """Set physical current stock (Main Store) via the stock-movement pipeline."""
    current_stock: float
    remarks: str = ""


# ------------------------- Purchases -------------------------
class PurchaseOrderLineIn(BaseModel):
    product_id: Optional[int] = None
    description: str = ""
    item_code: str = ""
    make: str = ""
    quantity: float = 0
    received_qty: float = 0
    rate: Optional[float] = None
    amount: Optional[float] = None
    uom: str = ""
    tax_percent: Optional[float] = None
    discount_percent: Optional[float] = None
    prn_line_id: Optional[int] = None


class PurchaseOrderCreate(BaseModel):
    po_number: str = Field(min_length=1, max_length=120)
    supplier_id: Optional[int] = None
    supplier_name: str = ""
    supplier_gstin: str = ""
    supplier_address: str = ""
    supplier_phone: str = ""
    supplier_email: str = ""
    order_date: date = Field(default_factory=date.today)
    valid_until: Optional[date] = None
    status: PurchaseStatus = PurchaseStatus.ordered
    notes: str = ""
    lines: list[PurchaseOrderLineIn] = []
    prn_id: Optional[int] = None
    idempotency_key: str = Field(default="", max_length=80)
    po_type: str = "regular"
    import_meta: dict = {}


class PurchaseOrderUpdate(BaseModel):
    po_number: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    supplier_gstin: Optional[str] = None
    supplier_address: Optional[str] = None
    supplier_phone: Optional[str] = None
    supplier_email: Optional[str] = None
    order_date: Optional[date] = None
    valid_until: Optional[date] = None
    status: Optional[PurchaseStatus] = None
    notes: Optional[str] = None
    lines: Optional[list[PurchaseOrderLineIn]] = None
    po_type: Optional[str] = None
    import_meta: Optional[dict] = None


class PurchaseOrderLineOut(ORMModel):
    id: int
    product_id: Optional[int]
    description: str
    item_code: str = ""
    make: str = ""
    quantity: float
    received_qty: float
    rate: Optional[float]
    amount: Optional[float]
    uom: str = ""
    tax_percent: Optional[float]
    discount_percent: Optional[float]
    product: Optional[ProductOut] = None


class PurchaseOrderOut(ORMModel):
    id: int
    po_number: str
    supplier_id: Optional[int]
    order_date: date
    valid_until: Optional[date] = None
    status: PurchaseStatus
    po_type: str = "regular"
    total_amount: float
    notes: str
    created_at: datetime
    supplier: Optional[SupplierOut] = None
    lines: list[PurchaseOrderLineOut] = []


# ------------------------- Inventory -------------------------
class StockMovementIn(BaseModel):
    product_id: int
    plant_id: Optional[int] = None
    movement_type: MovementType
    quantity: float
    transaction_date: date = Field(default_factory=date.today)
    remarks: str = ""


class ManualAddStockIn(BaseModel):
    """Add physical/manual stock received at a location.

    Item Code is OPTIONAL. When a `product_id` is given it is reused as the
    tracking identity. Otherwise the item is matched/created through the shared
    `resolve_or_create_product` helper (blank-code + description -> a fresh
    Product with a unique internal ID; never merged by description). Stock is
    recorded through the same `apply_movement`/Inventory pipeline used by
    purchases / transfers / production so Inventory and StockMovement stay
    consistent and other modules see the stock automatically.
    """
    product_id: Optional[int] = None
    item_code: Optional[str] = ""
    description: Optional[str] = ""
    quantity: float = Field(gt=0, description="Quantity to add (must be > 0)")
    unit: Optional[str] = None          # -> Product.uom when creating/laid on product
    category: Optional[str] = None      # only used when creating a NEW product
    plant_id: Optional[int] = None      # None = Main Store
    transaction_date: date = Field(default_factory=date.today)
    remarks: Optional[str] = ""         # reference / note carried on the movement
    min_level: Optional[float] = None   # optional reorder/min level on the inventory row


class InventoryUpdate(BaseModel):
    """Edit an existing Inventory row.

    Quantity reconcile uses the shared movement pipeline (a compensating
    StockMovement) so the balance is corrected WITHOUT double-counting and the
    movement history stays in sync. Unit/Item Code update the underlying
    Product (same Product ID is preserved — never duplicated). Location/Product
    change is allowed only when safe (zero balance with no attached movements);
    otherwise the caller should use the existing transfer flow which moves stock
    and preserves history.)
    """
    quantity: Optional[float] = None
    min_level: Optional[float] = None
    unit: Optional[str] = None          # -> Product.uom
    item_code: Optional[str] = None     # -> same Product (no duplicate)
    description: Optional[str] = None   # -> Product.model/name (same Product)
    plant_id: Optional[int] = None      # safe relocate only (see above)
    product_id: Optional[int] = None    # safe repoint only
    remarks: Optional[str] = ""         # carried on the reconcile movement


class StockMovementOut(ORMModel):
    id: int
    product_id: int
    plant_id: Optional[int]
    movement_type: MovementType
    quantity: float
    transaction_date: date
    ref_type: str
    ref_id: Optional[int]
    remarks: str
    created_at: datetime
    product: Optional[ProductOut] = None
    plant: Optional[PlantOut] = None


class InventoryOut(ORMModel):
    id: int
    product_id: int
    plant_id: Optional[int]
    opening_stock: float
    received_qty: float
    issued_qty: float
    current_stock: float
    min_level: Optional[float]
    product: Optional[ProductOut] = None
    plant: Optional[PlantOut] = None


# ------------------------- Stock Transfers -------------------------
class StockTransferLineIn(BaseModel):
    product_id: Optional[int] = None
    item_code: str = ""
    description: str = ""
    quantity: float = 0


class StockTransferCreate(BaseModel):
    transfer_no: Optional[str] = None
    from_plant_id: Optional[int] = None  # None = Main Store
    to_plant_id: int
    customer_id: Optional[int] = None
    customer_name: str = ""
    transfer_date: date = Field(default_factory=date.today)
    notes: str = ""
    lines: list[StockTransferLineIn] = []


class StockTransferUpdate(BaseModel):
    transfer_no: Optional[str] = None
    from_plant_id: Optional[int] = None
    to_plant_id: Optional[int] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    transfer_date: Optional[date] = None
    notes: Optional[str] = None
    lines: Optional[list[StockTransferLineIn]] = None


class StockTransferLineOut(ORMModel):
    id: int
    product_id: Optional[int]
    item_code: str
    description: str
    quantity: float
    product: Optional[ProductOut] = None


class StockTransferOut(ORMModel):
    id: int
    transfer_no: str
    from_plant_id: Optional[int]
    to_plant_id: int
    customer_id: Optional[int]
    customer_name: str
    transfer_date: date
    notes: str
    created_at: datetime
    from_plant: Optional[PlantOut] = None
    to_plant: Optional[PlantOut] = None
    customer: Optional[CustomerOut] = None
    lines: list[StockTransferLineOut] = []


# ------------------------- Customer Dispatch -------------------------
class CustomerDispatchLineIn(BaseModel):
    product_id: Optional[int] = None
    item_code: str = ""
    description: str = ""
    quantity: float = 0


class CustomerDispatchCreate(BaseModel):
    dispatch_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: str = ""
    plant_id: Optional[int] = None  # Dispatch location (defaults to seeded plant)
    dispatch_date: date = Field(default_factory=date.today)
    remarks: str = ""
    lines: list[CustomerDispatchLineIn] = []


class CustomerDispatchUpdate(BaseModel):
    dispatch_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    plant_id: Optional[int] = None
    dispatch_date: Optional[date] = None
    remarks: Optional[str] = None
    lines: Optional[list[CustomerDispatchLineIn]] = None


class CustomerDispatchLineOut(ORMModel):
    id: int
    product_id: Optional[int]
    item_code: str
    description: str
    quantity: float
    product: Optional[ProductOut] = None


class CustomerDispatchOut(ORMModel):
    id: int
    dispatch_no: str
    customer_id: Optional[int]
    customer_name: str
    plant_id: Optional[int]
    dispatch_date: date
    remarks: str
    created_at: datetime
    customer: Optional[CustomerOut] = None
    plant: Optional[PlantOut] = None
    lines: list[CustomerDispatchLineOut] = []


# ------------------------- Production -------------------------
class ProductionOrderCreate(BaseModel):
    product_id: Optional[int] = None
    item_code: str = ""
    model: str = ""
    order_no: Optional[str] = None
    section: str = ""
    schedule_qty: float = 0
    ask_till_date: Optional[float] = None
    produced_qty: float = 0
    opening_stock: float = 0
    customer_id: Optional[int] = None
    customer_name: str = ""
    sales_order_id: Optional[int] = None
    sales_order_line_id: Optional[int] = None
    status: ProductionStatus = ProductionStatus.planned
    category: str = "Manufacturing"
    start_date: Optional[date] = None
    completion_date: Optional[date] = None
    report_date: date = Field(default_factory=date.today)
    remarks: str = ""


class ProductionOrderUpdate(BaseModel):
    product_id: Optional[int] = None
    section: Optional[str] = None
    schedule_qty: Optional[float] = None
    ask_till_date: Optional[float] = None
    produced_qty: Optional[float] = None
    opening_stock: Optional[float] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    sales_order_id: Optional[int] = None
    sales_order_line_id: Optional[int] = None
    status: Optional[ProductionStatus] = None
    start_date: Optional[date] = None
    completion_date: Optional[date] = None
    report_date: Optional[date] = None
    remarks: Optional[str] = None


class ProductionMovementOut(ORMModel):
    id: int
    production_order_id: int
    quantity: float
    production_date: date


class ProductionOrderOut(ORMModel):
    id: int
    order_no: str
    product_id: int
    section: str
    schedule_qty: float
    ask_till_date: Optional[float]
    produced_qty: float
    completion_pct: Optional[float]
    balance_qty: float
    opening_stock: float
    status: ProductionStatus
    start_date: Optional[date]
    completion_date: Optional[date]
    report_date: date
    remarks: str
    sales_order_id: Optional[int] = None
    sales_order_line_id: Optional[int] = None
    product: Optional[ProductOut] = None
    movements: list[ProductionMovementOut] = []


# ------------------------- Orders -------------------------
def _order_status(obj):
    """Accept enum member names ('new') and values ('New').
    
    Raises ValueError for invalid status strings that are not valid OrderStatus values.
    This ensures the database Enum column only receives valid enum values.
    """
    if isinstance(obj, str):
        obj_lower = obj.lower()
        for member in OrderStatus:
            if member.name.lower() == obj_lower or member.value.lower() == obj_lower:
                return member.value
        # Invalid status string — raise error so Pydantic returns 422
        raise ValueError(f"Invalid OrderStatus: {obj!r}")
    return obj


class SalesOrderLineIn(BaseModel):
    product_id: Optional[int] = None
    description: str = ""
    item_code: str = ""
    quantity: float = 0
    schedule_qty: Optional[float] = None
    ask_till_date: Optional[float] = None
    completion_pct: Optional[float] = None
    balance_qty: Optional[float] = None
    opening_stock: Optional[float] = None
    uom: str = ""
    unit_price: Optional[float] = None
    less: Optional[float] = None
    amount: Optional[float] = None
    customer_po_no: str = ""


class SalesOrderLineUpdate(BaseModel):
    product_id: Optional[int] = None
    description: Optional[str] = None
    item_code: Optional[str] = None
    quantity: Optional[float] = None
    schedule_qty: Optional[float] = None
    ask_till_date: Optional[float] = None
    completion_pct: Optional[float] = None
    balance_qty: Optional[float] = None
    opening_stock: Optional[float] = None
    uom: Optional[str] = None
    unit_price: Optional[float] = None
    less: Optional[float] = None
    amount: Optional[float] = None
    customer_po_no: Optional[str] = None


class SalesOrderCreate(BaseModel):
    order_no: str = Field(min_length=1, max_length=120)
    customer_id: Optional[int] = None
    customer_name: str = ""
    customer_contact: str = ""
    customer_email: str = ""
    order_type: OrderType = OrderType.oem
    local_order_type: Optional[str] = None
    customer_po_no: str = ""
    salesperson_id: Optional[int] = None
    salesperson_name: str = ""
    order_date: date = Field(default_factory=date.today)
    required_delivery_date: Optional[date] = None
    status: OrderStatus = OrderStatus.new
    remarks: str = ""
    lines: list[SalesOrderLineIn] = []

    _status = field_validator("status", mode="before")(_order_status)


class SalesOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_contact: Optional[str] = None
    customer_email: Optional[str] = None
    order_type: Optional[OrderType] = None
    order_no: Optional[str] = None
    customer_po_no: Optional[str] = None
    salesperson_id: Optional[int] = None
    salesperson_name: Optional[str] = None
    order_date: Optional[date] = None
    required_delivery_date: Optional[date] = None
    local_order_type: Optional[str] = None
    status: Optional[OrderStatus] = None
    remarks: Optional[str] = None
    lines: Optional[list[SalesOrderLineIn]] = None

    _status = field_validator("status", mode="before")(_order_status)


class LocalOrderLineIn(SalesOrderLineIn):
    """Local order line: carries the DB line id so edits preserve history."""
    id: Optional[int] = None


class LocalOrderCreate(BaseModel):
    order_no: Optional[str] = None
    so_no: Optional[str] = None
    customer_po_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: str = ""
    customer_mobile: str = ""
    customer_email: str = ""
    local_order_type: Optional[str] = None
    order_date: date = Field(default_factory=date.today)
    required_delivery_date: Optional[date] = None
    status: OrderStatus = OrderStatus.new
    remarks: str = ""
    transport_name: str = ""
    lines: list[LocalOrderLineIn] = []

    _status = field_validator("status", mode="before")(_order_status)


class LocalOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    customer_email: Optional[str] = None
    so_no: Optional[str] = None
    customer_po_no: Optional[str] = None
    order_date: Optional[date] = None
    required_delivery_date: Optional[date] = None
    local_order_type: Optional[str] = None
    status: Optional[OrderStatus] = None
    remarks: Optional[str] = None
    transport_name: Optional[str] = None
    lines: Optional[list[LocalOrderLineIn]] = None

    _status = field_validator("status", mode="before")(_order_status)


class SalesOrderLineOut(ORMModel):
    id: int
    product_id: Optional[int]
    description: str
    quantity: float
    schedule_qty: Optional[float]
    ask_till_date: Optional[float]
    completion_pct: Optional[float]
    balance_qty: Optional[float]
    opening_stock: Optional[float]
    uom: str = ""
    unit_price: Optional[float]
    less: Optional[float]
    amount: Optional[float]
    product: Optional[ProductOut] = None


class SalesOrderOut(ORMModel):
    id: int
    order_no: str
    customer_id: Optional[int]
    customer_name: str = ""
    customer_contact: str = ""
    customer_email: str = ""
    order_date: date
    required_delivery_date: Optional[date]
    status: OrderStatus
    total_value: float
    remarks: str
    created_at: datetime
    customer: Optional[CustomerOut] = None
    salesperson: Optional[dict] = None
    lines: list[SalesOrderLineOut] = []


# ------------------------- Dispatch -------------------------
class DispatchLineIn(BaseModel):
    product_id: Optional[int] = None
    item_code: str = ""
    description: str = ""
    quantity: float = 0
    dispatch_date: date = Field(default_factory=date.today)
    rate: Optional[float] = None
    weight: Optional[float] = None
    sales_order_line_id: Optional[int] = None
    # Product-wise planned quantity for THIS line. When omitted it is derived
    # from the linked order line (schedule_qty ?? quantity); for lines with no
    # order link it defaults to the dispatched quantity.
    schedule_qty: Optional[float] = None


class DispatchCreate(BaseModel):
    dispatch_no: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: str = ""
    plant_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    sales_person: str = ""
    schedule_qty: float = 0
    ask_till_date: Optional[float] = None
    dispatched_qty: float = 0
    opening_stock: float = 0
    status: DispatchStatus = DispatchStatus.pending
    dispatch_date: Optional[date] = None
    delivery_status: str = ""
    transport_details: str = ""
    report_date: date = Field(default_factory=date.today)
    remarks: str = ""
    lines: list[DispatchLineIn] = []


class DispatchUpdate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    plant_id: Optional[int] = None
    sales_order_id: Optional[int] = None
    sales_person: Optional[str] = None
    schedule_qty: Optional[float] = None
    ask_till_date: Optional[float] = None
    dispatched_qty: Optional[float] = None
    opening_stock: Optional[float] = None
    status: Optional[DispatchStatus] = None
    dispatch_date: Optional[date] = None
    delivery_status: Optional[str] = None
    transport_details: Optional[str] = None
    report_date: Optional[date] = None
    remarks: Optional[str] = None
    lines: Optional[list[DispatchLineIn]] = None


class DispatchLineOut(ORMModel):
    id: int
    product_id: Optional[int]
    description: str
    quantity: float
    dispatch_date: date
    rate: Optional[float]
    weight: Optional[float]
    product: Optional[ProductOut] = None


class DispatchOut(ORMModel):
    id: int
    dispatch_no: str
    customer_id: Optional[int]
    plant_id: Optional[int]
    sales_order_id: Optional[int]
    sales_person: str
    schedule_qty: float
    ask_till_date: Optional[float]
    dispatched_qty: float
    completion_pct: Optional[float]
    balance_qty: float
    opening_stock: float
    status: DispatchStatus
    dispatch_date: Optional[date]
    delivery_status: str
    transport_details: str
    report_date: date
    remarks: str
    created_at: datetime
    customer: Optional[CustomerOut] = None
    plant: Optional[PlantOut] = None
    lines: list[DispatchLineOut] = []


# ------------------------- Plans -------------------------
class PlanCreate(BaseModel):
    plan_type: PlanType
    model: str
    product_id: Optional[int] = None
    customer_id: Optional[int] = None
    customer_name: str = ""
    sales_order_id: Optional[int] = None
    quantity: Optional[float] = None
    rate: Optional[float] = None
    weight: Optional[float] = None
    owner: str = ""
    status: str = "PENDING"
    plan_date: date = Field(default_factory=date.today)
    remarks: str = ""


class PlanUpdate(BaseModel):
    model: Optional[str] = None
    product_id: Optional[int] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    sales_order_id: Optional[int] = None
    quantity: Optional[float] = None
    rate: Optional[float] = None
    weight: Optional[float] = None
    owner: Optional[str] = None
    status: Optional[str] = None
    plan_date: Optional[date] = None
    remarks: Optional[str] = None


class PlanOut(ORMModel):
    id: int
    plan_type: PlanType
    model: str
    product_id: Optional[int]
    customer_id: Optional[int]
    sales_order_id: Optional[int]
    quantity: Optional[float]
    rate: Optional[float]
    weight: Optional[float]
    owner: str
    status: str
    plan_date: date
    remarks: str
    product: Optional[ProductOut] = None
    customer: Optional[CustomerOut] = None


# ------------------------- BOM -------------------------
class BOMBase(BaseModel):
    product_id: int
    raw_material_product_id: int
    quantity_per_unit: float = Field(gt=0)
    uom: str = "KG"
    effective_date: date = Field(default_factory=date.today)
    version: int = 1
    notes: str = ""


class BOMCreate(BOMBase):
    pass


class BOMUpdate(BaseModel):
    product_id: Optional[int] = None
    raw_material_product_id: Optional[int] = None
    quantity_per_unit: Optional[float] = Field(default=None, gt=0)
    uom: Optional[str] = None
    effective_date: Optional[date] = None
    version: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class BOMOut(BOMBase, ORMModel):
    id: int
    is_active: bool
    created_at: datetime
    product: Optional[ProductOut] = None
    raw_material: Optional[ProductOut] = None


class BOMLineIn(BaseModel):
    """One raw-material line for a BOM. Either an existing product id or a
    manually typed name is accepted (name auto-creates the product if unknown)."""
    id: Optional[int] = None
    raw_material_product_id: Optional[int] = None
    raw_material_name: str = ""
    quantity_per_unit: float = Field(default=0)
    uom: str = "KG"


class BOMGroupIn(BaseModel):
    """Header + multiple raw material lines for one BOM."""
    bom_code: str = Field(min_length=1, max_length=60)
    product_id: Optional[int] = None
    product_name: str = ""
    effective_date: date = Field(default_factory=date.today)
    version: int = 1
    notes: str = ""
    is_active: bool = True
    lines: list[BOMLineIn] = []


# ------------------------- Alerts -------------------------
class AlertOut(ORMModel):
    id: int
    type: str
    priority: str
    message: str
    entity_type: str
    entity_id: Optional[int]
    target_role: str
    is_read: bool
    status: str
    created_at: datetime
    resolved_at: Optional[datetime]


class AlertUpdate(BaseModel):
    is_read: Optional[bool] = None
    status: Optional[str] = None


# ------------------------- Material Requirements -------------------------
class MaterialRequirementItem(BaseModel):
    product_id: int
    product_name: str
    production_quantity: float
    raw_material_id: int
    raw_material_name: str
    bom_quantity_per_unit: float
    uom: str
    required_quantity: float
    available_quantity: float
    shortage_quantity: float
    status: str  # READY | SHORTAGE | NO_BOM


# ------------------------- Fulfilment Indicators -------------------------
class FulfilmentIndicator(BaseModel):
    sales_order_line_id: int
    order_no: str
    product_name: str
    ordered_qty: float
    fulfilled_qty: float
    balance: float
    available_stock: float
    source_type: str
    fulfilment_status: str  # READY | PRODUCTION_REQUIRED | PURCHASE_REQUIRED | MANUAL_DECISION_REQUIRED | NO_BOM
    shortage_qty: float


# ------------------------- Meta -------------------------
class DashboardSummary(BaseModel):
    total_orders: int
    new_orders_today: int
    pending_orders: int
    completed_orders: int
    orders_in_production: int
    ready_to_dispatch: int
    orders_dispatched: int
    order_value: float
    raw_material_count: int
    raw_material_stock: float
    low_stock_items: int
    out_of_stock_items: int
    production_planned_qty: float
    production_produced_qty: float
    production_pending_qty: float
    purchase_count: int
    purchase_value: float
    dispatch_scheduled: float
    dispatch_done: float
    dispatch_pending: float
    supplier_count: int
    customer_count: int
    plant_count: int
    product_count: int
    store_items: int


class EmailSendIn(BaseModel):
    to: str
    subject: str
    message: str


class EmailPreviewOut(BaseModel):
    to: str
    subject: str
    message: str


class EmailHistoryOut(BaseModel):
    id: int
    email_type: str
    recipient: str
    subject: str
    status: str
    error_message: str
    sent_at: datetime


# ---------------------------------------------------------------------------
# Packaging List
# ---------------------------------------------------------------------------
class PackagingListLineIn(BaseModel):
    id: Optional[int] = None
    sr_no: int = 0
    gross_wt: float = 0
    # None means "use the list-level default less"
    less: Optional[float] = None
    net_wt: float = 0


class PackagingListLineOut(BaseModel):
    id: int
    sr_no: int
    gross_wt: float
    less: float
    net_wt: float


class PackagingListCreate(BaseModel):
    list_no: Optional[str] = None
    list_date: date = Field(default_factory=date.today)
    customer_id: Optional[int] = None
    customer_name: str = ""
    item_description: str = ""
    less_default: float = 0
    lines: list[PackagingListLineIn] = []


class PackagingListUpdate(BaseModel):
    list_no: Optional[str] = None
    list_date: Optional[date] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    item_description: Optional[str] = None
    less_default: Optional[float] = None
    lines: Optional[list[PackagingListLineIn]] = None


class PackagingListOut(ORMModel):
    id: int
    list_no: str
    list_date: date
    customer_id: Optional[int]
    customer_name: str
    item_description: str
    less_default: float
    total_gross_wt: float
    total_less: float
    total_net_wt: float
    lines: list[PackagingListLineOut]
    created_by: Optional[UserMiniOut] = None
    created_at: datetime
    updated_at: Optional[datetime]


class PageOut(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


# ------------------------- Quotations -------------------------
class UserMiniOut(ORMModel):
    id: int
    username: str
    full_name: str


class QuotationLineIn(BaseModel):
    id: Optional[int] = None
    product_id: Optional[int] = None
    item_code: str = ""
    description: str = Field(min_length=1, max_length=500)
    hsn_code: str = ""
    quantity: float = Field(gt=0)
    uom: str = ""
    price: float = Field(ge=0)
    lead_time: str = ""
    tax_percent: Optional[float] = None
    amount: Optional[float] = 0


class QuotationLineOut(ORMModel):
    id: int
    product_id: Optional[int]
    product: Optional[ProductOut]
    item_code: str
    description: str
    hsn_code: str
    quantity: float
    uom: str
    price: float
    lead_time: str
    tax_percent: Optional[float]
    amount: float


class QuotationBase(BaseModel):
    quotation_type: QuotationType
    customer_id: Optional[int] = None
    customer_name: str = ""
    customer_contact: str = ""
    customer_email: str = ""
    customer_address: str = ""
    customer_gstin: str = ""

    company_name: str = "KALIKA ENTERPRISES"
    company_address: str = "Plot No. M-59, MIDC, AHMEDNAGAR"
    company_website: str = "www.kalikaindia.com"
    company_phone: str = "+91 9405536016"
    contact_email: str = "info@kalikaindia.com"

    quotation_no: Optional[str] = None
    quote_date: date = date.today()
    valid_until: Optional[date] = None
    approved_by: str = ""
    terms: str = ""
    payment_days: Optional[int] = Field(default=None, ge=1)
    status: QuotationStatus = QuotationStatus.draft
    lines: list[QuotationLineIn] = []


class QuotationCreate(QuotationBase):
    @field_validator("company_name")
    @classmethod
    def _valid_company_name(cls, v: str) -> str:
        return normalize_quotation_company(v)


class QuotationUpdate(QuotationBase):
    @field_validator("company_name")
    @classmethod
    def _valid_company_name(cls, v: str) -> str:
        return normalize_quotation_company(v)


class QuotationOut(QuotationBase, ORMModel):
    id: int
    quotation_no: str
    revision: int
    revised_from_id: Optional[int]
    subtotal: float
    tax_total: float
    total_amount: float
    lines: list[QuotationLineOut]
    customer: Optional[CustomerOut]
    created_by: Optional[UserMiniOut]
    created_at: datetime
    updated_at: Optional[datetime]


class QuotationListOut(ORMModel):
    id: int
    quotation_no: str
    revision: int
    quotation_type: QuotationType
    status: QuotationStatus
    customer_name: str
    customer_id: Optional[int]
    quote_date: date
    valid_until: Optional[date]
    total_amount: float
    created_at: datetime


class QuotationStatusIn(BaseModel):
    status: QuotationStatus


class QuotationDuplicateOut(QuotationOut):
    pass


class QuotationRevisionOut(ORMModel):
    id: int
    quotation_no: str
    revision: int
    status: QuotationStatus
    quote_date: date
    total_amount: float
    created_at: datetime
    created_by: Optional[UserMiniOut]


class QuotationHistoryOut(ORMModel):
    revisions: list[QuotationRevisionOut]
    audit: list[Any]


class TermsTemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str = ""
    is_default: bool = False


class TermsTemplateCreate(TermsTemplateBase):
    pass


class TermsTemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    is_default: Optional[bool] = None


class TermsTemplateOut(TermsTemplateBase, ORMModel):
    id: int
    created_at: datetime


class QuotationEmailSendIn(BaseModel):
    to: str
    cc: Optional[str] = ""
    subject: str
    message: str
    attach_pdf: bool = True


class QuotationEmailPreviewOut(BaseModel):
    to: str
    cc: str
    subject: str
    message: str


class QuotationEmailHistoryOut(ORMModel):
    id: int
    email_type: str
    recipient: str
    cc: str
    subject: str
    status: str
    error_message: str
    sent_at: datetime


# ------------------------- PRN (Purchase Requisition Note) -------------------------
class PRNLineIn(BaseModel):
    """One material requirement row. Manual (unmatched) rows carry no stock —
    the router stores NULL, never 0, for stock on a manual entry."""

    id: Optional[int] = None
    entry_mode: PRNLineMode = PRNLineMode.manual
    material_id: Optional[int] = None
    # Inventory location for the stock snapshot. None = Main Store (default).
    plant_id: Optional[int] = None
    material_code: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)
    specification: str = Field(default="", max_length=2000)
    quantity: float = 0
    uom: str = Field(default="", max_length=30)
    remarks: str = Field(default="", max_length=2000)
    # Optional PRN-specific stock estimate (override). Never an inventory change.
    stock_override: Optional[float] = None

    @field_validator("stock_override")
    @classmethod
    def _override_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and float(v) < 0:
            raise ValueError("Stock override cannot be negative")
        return v

    @field_validator("description")
    @classmethod
    def _description_required(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Material description is required")
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def _quantity_positive(cls, v: float) -> float:
        if v is None or float(v) <= 0:
            raise ValueError("Required quantity must be greater than zero")
        return float(v)

    @model_validator(mode="after")
    def _existing_needs_material(self):
        if self.entry_mode == PRNLineMode.existing and not self.material_id:
            raise ValueError("An existing material selection is required for Existing mode")
        return self


class PRNCreate(BaseModel):
    prn_date: Optional[date] = None
    department: str = Field(default="", max_length=120)
    department_head: str = Field(default="", max_length=160)
    company_name: str = Field(default="", max_length=160)
    # Manually entered requester name; falls back to the authenticated user.
    requested_by_name: Optional[str] = Field(default=None, max_length=160)
    required_by_date: Optional[date] = None
    priority: str = Field(default="Normal", max_length=20)
    requirement_type: str = Field(default="Production", max_length=40)
    purpose: str = Field(default="", max_length=4000)
    production_reference: str = Field(default="", max_length=120)
    checked_by_name: str = Field(default="", max_length=160)
    purchase_remarks: str = Field(default="", max_length=4000)
    lines: list[PRNLineIn] = Field(default_factory=list)


class PRNUpdate(BaseModel):
    prn_date: Optional[date] = None
    department: Optional[str] = Field(default=None, max_length=120)
    department_head: Optional[str] = Field(default=None, max_length=160)
    company_name: Optional[str] = Field(default=None, max_length=160)
    requested_by_name: Optional[str] = Field(default=None, max_length=160)
    required_by_date: Optional[date] = None
    priority: Optional[str] = Field(default=None, max_length=20)
    requirement_type: Optional[str] = Field(default=None, max_length=40)
    purpose: Optional[str] = Field(default=None, max_length=4000)
    production_reference: Optional[str] = Field(default=None, max_length=120)
    checked_by_name: Optional[str] = Field(default=None, max_length=160)
    purchase_remarks: Optional[str] = Field(default=None, max_length=4000)
    lines: Optional[list[PRNLineIn]] = None


class PRNRejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class PRNFulfillmentIn(BaseModel):
    fulfillment_status: Literal["Pending", "Partially Fulfilled", "Completed"]
    purchase_reference: str = Field(default="", max_length=120)
    purchase_remarks: str = Field(default="", max_length=4000)
