"""Idempotent migration: ensure all OrderStatus member names exist as PostgreSQL
enum labels. Run against the target database (local .env or Cloud SQL env).

This script only executes ALTER TYPE ... ADD VALUE for labels that are missing;
it never drops/recreates the enum and never modifies existing data.

Usage:
    python scripts/migrate_orderstatus_enum.py [--dry-run]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.models import OrderStatus


def main():
    parser = argparse.ArgumentParser(description="Add missing orderstatus enum labels")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be added without executing")
    args = parser.parse_args()

    # The labels SQLAlchemy actually stores for OrderStatus (member names).
    required_labels = [member.name for member in OrderStatus]

    with engine.connect() as conn:
        existing = {
            r[0] for r in conn.execute(text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'orderstatus'"
            ))
        }
        missing = [label for label in required_labels if label not in existing]

        if not missing:
            print("All OrderStatus labels already present in PostgreSQL enum 'orderstatus'.")
            return

        print(f"Missing orderstatus labels: {missing}")
        if args.dry_run:
            print("Dry run — no changes made.")
            return

        for label in missing:
            # PostgreSQL ADD VALUE is transactional and idempotent by virtue of
            # the prior existence check; we guard with a DO block so repeated
            # runs never error even if a concurrent process added the label.
            conn.execute(text(
                "DO $$ "
                "BEGIN "
                "  IF NOT EXISTS ("
                "    SELECT 1 FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                "    WHERE t.typname = 'orderstatus' AND e.enumlabel = :label"
                "  ) THEN "
                "    ALTER TYPE orderstatus ADD VALUE :label; "
                "  END IF; "
                "END $$"
            ), {"label": label})
            print(f"  -> Added '{label}' to orderstatus enum")

        conn.commit()
        print("Done. Current labels:", sorted(required_labels + list(existing)))


if __name__ == "__main__":
    main()
