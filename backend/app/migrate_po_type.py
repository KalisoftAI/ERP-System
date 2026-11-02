from sqlalchemy import text
from app.database import engine

stmts = [
    "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS po_type VARCHAR(20) DEFAULT 'regular'",
    "UPDATE purchase_orders SET po_type = 'regular' WHERE po_type IS NULL",
]
with engine.begin() as conn:
    for s in stmts:
        conn.execute(text(s))
print('done')

