"""Self-check for the Kaliflow admin toggle and gated HTML view."""
import os
import sys
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.database import Base
from app.models import GcsAsset, User, UserRole
from app.routers import kaliflow
from app.services.kaliflow_assets import AssetFetchError, AssetValidationError


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


def test_toggle_defaults_on_and_admin_can_disable():
    db = _session()
    admin, viewer = _users(db)
    assert kaliflow.get_toggle(viewer, db).enabled is True
    assert kaliflow.set_toggle(kaliflow.ToggleIn(enabled=False), admin, db).enabled is False
    assert kaliflow.get_toggle(viewer, db).enabled is False
    try:
        kaliflow.dashboard(viewer, db)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("dashboard should be blocked when disabled")


def test_admin_toggles_and_viewer_reads_cached_html():
    db = _session()
    admin, viewer = _users(db)
    kaliflow.asset_reader.clear()
    spec = kaliflow.asset_registry["kaliflow_dashboard"]
    kaliflow.asset_reader.prime(spec.bucket, spec.object_path, b"<html>Kaliflow</html>")
    assert kaliflow.set_toggle(kaliflow.ToggleIn(enabled=True), admin, db).enabled is True
    assert kaliflow.get_toggle(viewer, db).enabled is True
    try:
        response = kaliflow.dashboard(viewer, db)
        assert response.status_code == 200
        assert b"KALIFLOW_NOS" in response.body
        assert b"<html>Kaliflow</html>" in response.body
    finally:
        kaliflow.asset_reader.clear()


def test_assets_are_seeded_and_updatable_by_admin():
    db = _session()
    admin, viewer = _users(db)
    items = kaliflow.list_assets(viewer, db)["items"]
    assert {item["key"] for item in items} == set(kaliflow.DEFAULT_ASSETS)
    dashboard_asset = next(item for item in items if item["key"] == "kaliflow_dashboard")
    assert dashboard_asset["kind"] == "html"
    assert "%20" in dashboard_asset["url"]
    assert dashboard_asset["url"].endswith("%2818%29.html")
    updated = kaliflow.update_asset(
        "kaliflow_dashboard",
        kaliflow.AssetIn(kind="html", object_path="assets/updated.html"),
        admin,
        db,
    )
    assert updated.object_path == "assets/updated.html"
    assert kaliflow._asset(db, "kaliflow_dashboard").object_path == "assets/updated.html"
    try:
        kaliflow.update_asset(
            "kaliflow_dashboard",
            kaliflow.AssetIn(object_path="../secret.html"),
            admin,
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("unsafe object path should be rejected")
    assert kaliflow._asset(db, "kaliflow_dashboard").object_path == "assets/updated.html"


def test_video_asset_is_served_with_mp4_type():
    db = _session()
    _, viewer = _users(db)
    kaliflow.asset_reader.clear()
    spec = kaliflow.asset_registry["kalika_demo_video"]
    kaliflow.asset_reader.prime(spec.bucket, spec.object_path, b"\x00\x00\x00\x18ftypmp42")
    try:
        response = kaliflow.asset_file("kalika_demo_video", viewer, db)
        assert response.status_code == 200
        assert response.media_type == "video/mp4"
        assert response.body.startswith(b"\x00\x00\x00\x18ftyp")
    finally:
        kaliflow.asset_reader.clear()


def test_legacy_asset_paths_are_reconciled():
    db = _session()
    db.add_all([
        GcsAsset(
            key="kaliflow_dashboard",
            kind="html",
            bucket="sales-crm",
            object_path="assets/UI/kaliflow_kalika_enterprises_3d_manufacturing_dashboard.html",
        ),
        GcsAsset(
            key="kalika_demo_video",
            kind="video",
            bucket="sales-crm",
            object_path="Manufacturing-Data/kalika-videos/app-demo-videos/15-30-12.mp4",
        ),
        GcsAsset(
            key="kalika_logo",
            kind="logo",
            bucket="sales-crm",
            object_path="assets/custom-logo.png",
        ),
    ])
    db.commit()
    assert kaliflow.reconcile_assets(db) is True
    assert kaliflow._asset(db, "kaliflow_dashboard").object_path == (
        "assets/Html-data/Kaliflow - Kalika Enterprises 3D Manufacturing Dashboard (18).html"
    )
    assert kaliflow._asset(db, "kalika_demo_video").object_path == (
        "assets/Videos/ScreenVideo_20261123_064013.mp4"
    )
    assert kaliflow._asset(db, "kalika_logo").object_path == "assets/custom-logo.png"
    assert kaliflow.reconcile_assets(db) is False


def test_reader_rejects_oversized_payloads(monkeypatch):
    kaliflow.asset_reader.clear()
    spec = kaliflow.asset_registry["kalika_logo"]
    monkeypatch.setattr(kaliflow.asset_reader, "_download", lambda _: b"x" * (spec.max_bytes + 1))
    try:
        kaliflow.asset_reader.read(spec)
    except AssetFetchError:
        pass
    else:
        raise AssertionError("oversized asset should be rejected")
    assert kaliflow.asset_reader._cache == {}


def test_asset_validation_rejects_unsafe_values():
    for fields in (
        {"bucket": "evil-bucket"},
        {"object_path": "/etc/passwd"},
        {"object_path": "assets/../secret.html"},
        {"object_path": "assets/a%20b.html"},
        {"kind": "script"},
    ):
        try:
            kaliflow.validate_asset_update("kaliflow_dashboard", fields)
        except AssetValidationError:
            continue
        raise AssertionError(f"unsafe asset fields accepted: {fields}")
