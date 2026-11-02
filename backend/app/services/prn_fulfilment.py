"""Keep a PRN's fulfilment in step with its linked purchase orders.

A PRN never touches stock itself. This module only RE-READS the received
quantities already recorded against POs linked to the PRN (via
`prn_line_id`) and updates the PRN's derived status. It is deliberately
side-effect free apart from the PRN status/fulfilment fields, and performs no
commit — callers commit inside their own transaction.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import PRN, PRNLine, PRNStatus, PurchaseOrder, PurchaseOrderLine, PurchaseStatus

# A PRN only enters the purchasing lifecycle once it is sent to purchase; before
# that its status is driven by the approval workflow, so sync must never touch it.
_SCOPE = (PRNStatus.sent_to_purchase, PRNStatus.partially_fulfilled, PRNStatus.completed)
_EPS = 1e-6


def affected_prn_ids(db: Session, po_lines) -> set[int]:
    """PRN ids reached by the given PO lines (through their prn_line_id)."""
    line_ids = {ln.prn_line_id for ln in po_lines if getattr(ln, "prn_line_id", None)}
    if not line_ids:
        return set()
    return set(db.scalars(select(PRNLine.prn_id).where(PRNLine.id.in_(line_ids))).all())


def sync_prn_fulfilment(db: Session, prn_ids) -> list[dict]:
    """Recompute status/fulfilment for each PRN from its actual receipts.

    Completed  = every PRN line has received (across non-cancelled POs) >= required.
    Partial    = at least one line has some receipt but not all are complete.
    Otherwise  = back to Sent to Purchase (e.g. a linked PO was deleted/reversed).

    Returns the transitions applied (for audit) and mutates the PRN rows.
    """
    transitions: list[dict] = []
    for prn_id in {p for p in prn_ids if p}:
        prn = db.get(PRN, prn_id)
        if prn is None or prn.status not in _SCOPE:
            continue
        lines = list(prn.lines)
        if not lines:
            continue
        rows = db.execute(
            select(PurchaseOrderLine.prn_line_id,
                   func.coalesce(func.sum(PurchaseOrderLine.received_qty), 0))
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.po_id)
            .where(PurchaseOrderLine.prn_line_id.in_([ln.id for ln in lines]),
                   PurchaseOrder.status != PurchaseStatus.cancelled)
            .group_by(PurchaseOrderLine.prn_line_id)
        ).all()
        received_by_line = {r[0]: float(r[1] or 0) for r in rows}

        complete = all(
            received_by_line.get(ln.id, 0.0) + _EPS >= float(ln.quantity or 0)
            for ln in lines
        )
        any_received = any(received_by_line.get(ln.id, 0.0) > 0 for ln in lines)

        if complete:
            new_status, new_fulfilment = PRNStatus.completed, "Completed"
        elif any_received:
            new_status, new_fulfilment = PRNStatus.partially_fulfilled, "Partially Fulfilled"
        else:
            new_status, new_fulfilment = PRNStatus.sent_to_purchase, "Pending"

        if (prn.status, prn.fulfillment_status) != (new_status, new_fulfilment):
            old = prn.status.value
            prn.status = new_status
            prn.fulfillment_status = new_fulfilment
            transitions.append({
                "prn_id": prn.id, "prn_number": prn.prn_number,
                "from": old, "to": new_status.value,
            })
    return transitions
