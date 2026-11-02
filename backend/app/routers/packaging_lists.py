"""Packaging List router.

Operations department records for box-wise packing weights. Creating or editing
a packaging list does not affect inventory, dispatch, production or orders.
"""
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..auth import CurrentUser, AllStaff, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import Customer, PackagingList, PackagingListLine, User
from ..schemas import PackagingListCreate, PackagingListUpdate, PackagingListOut

router = APIRouter(prefix="/packaging-lists", tags=["packaging-lists"])


def _next_list_no(db: Session) -> str:
    """Generate the next sequential packaging-list number for today."""
    prefix = f"PKL-{date.today():%Y%m%d}-"
    rows = db.execute(
        select(PackagingList.list_no).where(PackagingList.list_no.like(f"{prefix}%"))
    ).scalars().all()
    max_seq = 0
    for no in rows:
        suffix = no[len(prefix):]
        try:
            max_seq = max(max_seq, int(suffix))
        except ValueError:
            continue
    return f"{prefix}{max_seq + 1:03d}"


def _wt(value: float) -> float:
    """Round a weight to 6 decimals.

    Weights are stored exactly as entered (floats allowed). Six decimals keeps
    full precision for the Net WT arithmetic while still removing float noise
    such as 29.7 - 3.2 = 26.499999999999996. Rendering is padded to 3 decimals.
    """
    return round(float(value or 0), 6)


def _recalc(pl: PackagingList, lines_data: list[dict]) -> None:
    """Recalculate per-line net weight and header totals.

    Net WT = Gross WT - Less. Totals are summed across all lines.
    """
    pl.lines.clear()
    total_gross = 0.0
    total_less = 0.0
    total_net = 0.0
    for idx, ln_in in enumerate(lines_data, start=1):
        gross = float(ln_in.get("gross_wt") or 0)
        # If less is not provided for a line, fall back to the list-level default.
        raw_less = ln_in.get("less")
        if raw_less is None or raw_less == "":
            less = float(pl.less_default or 0)
        else:
            less = float(raw_less)
        net = _wt(gross - less)
        pl.lines.append(PackagingListLine(
            sr_no=idx,
            gross_wt=_wt(gross),
            less=_wt(less),
            net_wt=net,
        ))
        total_gross += gross
        total_less += less
        total_net += net
    pl.total_gross_wt = _wt(total_gross)
    pl.total_less = _wt(total_less)
    pl.total_net_wt = _wt(total_net)


def _resolve_customer(db: Session, data: PackagingListCreate | PackagingListUpdate) -> tuple[int | None, str]:
    """Link to an existing customer or keep the manually entered name."""
    customer_id = data.customer_id
    customer_name = (data.customer_name or "").strip()
    if customer_id:
        customer = db.get(Customer, customer_id)
        if customer:
            return customer.id, customer.name
    return customer_id, customer_name


def _find_duplicates(db: Session, data: PackagingListCreate | PackagingListUpdate,
                     exclude_id: int | None = None) -> list[PackagingList]:
    """Find existing packaging lists with the same date, client and item."""
    stmt = select(PackagingList).where(
        PackagingList.list_date == data.list_date,
        func.lower(PackagingList.customer_name) == (data.customer_name or "").strip().lower(),
        func.lower(PackagingList.item_description) == (data.item_description or "").strip().lower(),
    )
    if exclude_id:
        stmt = stmt.where(PackagingList.id != exclude_id)
    return db.scalars(stmt).all()


def _serialize(pl: PackagingList) -> dict[str, Any]:
    """Serialize a packaging list with its lines for API responses."""
    creator = pl.created_by
    return {
        "id": pl.id,
        "list_no": pl.list_no,
        "list_date": pl.list_date,
        "customer_id": pl.customer_id,
        "customer_name": pl.customer_name,
        "item_description": pl.item_description,
        "less_default": float(pl.less_default or 0),
        "total_gross_wt": float(pl.total_gross_wt or 0),
        "total_less": float(pl.total_less or 0),
        "total_net_wt": float(pl.total_net_wt or 0),
        "lines": [
            {
                "id": ln.id,
                "sr_no": ln.sr_no,
                "gross_wt": float(ln.gross_wt or 0),
                "less": float(ln.less or 0),
                "net_wt": float(ln.net_wt or 0),
            }
            for ln in pl.lines
        ],
        "created_by": {
            "id": creator.id,
            "full_name": creator.full_name,
            "username": creator.username,
        } if creator else None,
        "created_at": pl.created_at,
        "updated_at": pl.updated_at,
    }


@router.get("", response_model=dict)
def list_packaging_lists(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """List packaging lists with search and date filters."""
    stmt = select(PackagingList).options(joinedload(PackagingList.created_by))
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                PackagingList.customer_name.ilike(term),
                PackagingList.item_description.ilike(term),
                PackagingList.list_no.ilike(term),
            )
        )
    if date_from:
        stmt = stmt.where(PackagingList.list_date >= date_from)
    if date_to:
        stmt = stmt.where(PackagingList.list_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(PackagingList.list_date.desc(), PackagingList.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return {
        "items": [_serialize(pl) for pl in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_packaging_list(
    data: PackagingListCreate,
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
    force: bool = Query(False, description="Skip duplicate warning and create anyway"),
):
    """Create a new packaging list.

    Returns a warning when a duplicate date/client/item record exists unless
    force=true is supplied.
    """
    duplicates = _find_duplicates(db, data)
    if duplicates and not force:
        return {
            "warning": True,
            "message": "A packaging list with the same date, client and item already exists.",
            "existing": [_serialize(pl) for pl in duplicates[:5]],
        }

    customer_id, customer_name = _resolve_customer(db, data)
    pl = PackagingList(
        list_no=data.list_no or _next_list_no(db),
        list_date=data.list_date,
        customer_id=customer_id,
        customer_name=customer_name,
        item_description=data.item_description or "",
        less_default=data.less_default or 0,
        created_by_id=user.id,
    )
    _recalc(pl, [ln.model_dump() for ln in data.lines])
    db.add(pl)
    db.commit()
    db.refresh(pl)
    write_audit(db, user, "CREATE", "packaging_lists", pl.id, f"Created packaging list {pl.list_no}")
    return _serialize(pl)


@router.get("/{list_id}", response_model=dict)
def get_packaging_list(
    list_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    """Fetch a single packaging list with all lines."""
    pl = db.get(PackagingList, list_id, options=[joinedload(PackagingList.created_by)])
    if pl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging list not found")
    return _serialize(pl)


@router.put("/{list_id}", response_model=dict)
def update_packaging_list(
    list_id: int,
    data: PackagingListUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
    force: bool = Query(False, description="Skip duplicate warning and update anyway"),
):
    """Update a packaging list header and lines."""
    pl = db.get(PackagingList, list_id)
    if pl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging list not found")

    # Apply scalar header fields directly; apply_updates expects a Pydantic model.
    update_data = data.model_dump(exclude_unset=True)

    # Only touch the customer when the client actually sent those fields.
    # Inline weight add/remove sends only "lines", so the client must be kept as-is.
    if "customer_id" in update_data or "customer_name" in update_data:
        customer_id, customer_name = _resolve_customer(db, data)
        pl.customer_id = customer_id
        pl.customer_name = customer_name

    for key, value in update_data.items():
        if key in {"customer_id", "customer_name", "lines"}:
            continue
        if value is not None and hasattr(pl, key):
            setattr(pl, key, value)

    # Only warn about duplicates when the record identity actually changed.
    identity_changed = any(
        k in update_data for k in ("list_date", "customer_name", "item_description")
    )
    if identity_changed:
        duplicates = _find_duplicates(db, PackagingListCreate(
            list_date=pl.list_date,
            customer_name=pl.customer_name,
            item_description=pl.item_description,
            lines=[],
        ), exclude_id=pl.id)
        if duplicates and not force:
            return {
                "warning": True,
                "message": "A packaging list with the same date, client and item already exists.",
                "existing": [_serialize(p) for p in duplicates[:5]],
            }

    if data.lines is not None:
        _recalc(pl, [ln.model_dump() for ln in data.lines])

    db.commit()
    db.refresh(pl)
    write_audit(db, user, "UPDATE", "packaging_lists", pl.id, f"Updated packaging list {pl.list_no}")
    return _serialize(pl)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_packaging_list(
    list_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: ManagerOrAdmin,
):
    """Delete a packaging list after confirmation."""
    pl = db.get(PackagingList, list_id)
    if pl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging list not found")
    db.delete(pl)
    db.commit()
    write_audit(db, user, "DELETE", "packaging_lists", list_id, f"Deleted packaging list {pl.list_no}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{list_id}/duplicate", response_model=dict)
def duplicate_packaging_list(
    list_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
):
    """Create a copy of an existing packaging list with a new number."""
    pl = db.get(PackagingList, list_id)
    if pl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging list not found")
    new_pl = PackagingList(
        list_no=_next_list_no(db),
        list_date=date.today(),
        customer_id=pl.customer_id,
        customer_name=pl.customer_name,
        item_description=pl.item_description,
        less_default=pl.less_default,
        total_gross_wt=pl.total_gross_wt,
        total_less=pl.total_less,
        total_net_wt=pl.total_net_wt,
        created_by_id=user.id,
    )
    for ln in pl.lines:
        new_pl.lines.append(PackagingListLine(
            sr_no=ln.sr_no,
            gross_wt=ln.gross_wt,
            less=ln.less,
            net_wt=ln.net_wt,
        ))
    db.add(new_pl)
    db.commit()
    db.refresh(new_pl)
    write_audit(db, user, "DUPLICATE", "packaging_lists", new_pl.id,
                f"Duplicated from {pl.list_no}")
    return _serialize(new_pl)
