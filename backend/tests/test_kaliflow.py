"""Self-check for the Kaliflow admin toggle and gated HTML view."""
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.database import Base
from app.models import User, UserRole
from app.routers import kaliflow


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _users(db):
    token = uuid4().hex[:8]
    admin = User(username=f"adm-{token}", email=f"adm-{token}@example.com",
                 password_hash=hash_password("secret"), role=UserRole.admin)
    viewer = User(username=f"vw-{token}", email=f"vw-{token}@example.com",
                  password_hash=hash_password("secret"), role=UserRole.viewer)
    db.add_all([admin, viewer])
    db.commit()
    return admin, viewer


def test_toggle_defaults_off_and_blocks_dashboard():
    db = _session()
    _, viewer = _users(db)
    assert kaliflow.get_toggle(viewer, db).enabled is False
    try:
        kaliflow.dashboard(viewer, db)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("dashboard should be disabled by default")


def test_admin_toggles_and_viewer_reads_cached_html():
    db = _session()
    admin, viewer = _users(db)
    assert kaliflow.set_toggle(kaliflow.ToggleIn(enabled=True), admin, db).enabled is True
    assert kaliflow.get_toggle(viewer, db).enabled is True
    original = (kaliflow._cached_html, kaliflow._cache_expiry, kaliflow._cache_path)
    kaliflow._cached_html = b"<html>Kaliflow</html>"
    kaliflow._cache_expiry = 1e12
    kaliflow._cache_path = (
        f"{kaliflow.settings.KALIFLOW_GCS_BUCKET}/"
        f"{kaliflow.settings.KALIFLOW_GCS_OBJECT}"
    )
    try:
        response = kaliflow.dashboard(viewer, db)
        assert response.status_code == 200
        assert response.body == b"<html>Kaliflow</html>"
    finally:
        kaliflow._cached_html, kaliflow._cache_expiry, kaliflow._cache_path = original


def test_assets_are_seeded_and_updatable_by_admin():
    db = _session()
    admin, viewer = _users(db)
    items = kaliflow.list_assets(viewer, db)["items"]
    assert {item["key"] for item in items} == set(kaliflow.DEFAULT_ASSETS)
    dashboard_asset = next(item for item in items if item["key"] == "kaliflow_dashboard")
    assert dashboard_asset["kind"] == "html"
    assert "storage.googleapis.com" in dashboard_asset["url"]
    updated = kaliflow.update_asset(
        "kaliflow_dashboard",
        kaliflow.AssetIn(kind="html", object_path="assets/updated.html"),
        admin,
        db,
    )
    assert updated.object_path == "assets/updated.html"
    assert kaliflow._asset(db, "kaliflow_dashboard").object_path == "assets/updated.html"
