"""Fetch the source Excel workbook and shared assets from Google Cloud Storage."""
import logging
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

try:
    from google.cloud import storage
    _GCS_AVAILABLE = True
except ImportError:
    _GCS_AVAILABLE = False

_stamp_bytes: bytes | None = None
_stamp_loaded = False


def get_stamp_bytes() -> bytes | None:
    """Return the company stamp image, cached after the first call.

    Prefers the shared GCS copy so every deployment prints the same stamp. If
    GCS is unavailable (missing ADC, network, permissions) the backend-bundled
    copy is used and the failure is logged; returns None only when neither is
    readable, so callers can omit the stamp instead of emitting a broken PDF.
    """
    global _stamp_bytes, _stamp_loaded
    if _stamp_loaded:
        return _stamp_bytes
    _stamp_loaded = True

    if _GCS_AVAILABLE:
        try:
            client = storage.Client()
            blob = client.bucket(settings.GCS_BUCKET).blob(settings.GCS_STAMP_FILE)
            _stamp_bytes = blob.download_as_bytes()
            logger.info("Loaded stamp from gs://%s/%s", settings.GCS_BUCKET, settings.GCS_STAMP_FILE)
            return _stamp_bytes
        except Exception as exc:
            logger.warning("Could not load stamp from GCS (%s); using bundled copy", exc)

    fallback = Path(__file__).resolve().parent.parent / "assets" / "stamp.png"
    if fallback.exists():
        _stamp_bytes = fallback.read_bytes()
        logger.info("Loaded bundled stamp: %s", fallback)
    else:
        logger.error("Company stamp unavailable: GCS failed and %s is missing", fallback)
        _stamp_bytes = None
    return _stamp_bytes


def download_excel(dest: Path | None = None) -> Path:
    """Download GCS_EXCEL_FILE to the data directory. Returns local path."""
    dest = dest or (Path(__file__).resolve().parent.parent.parent.parent / "data"
                    / settings.GCS_EXCEL_FILE.split("/")[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)

    if not _GCS_AVAILABLE:
        raise RuntimeError("google-cloud-storage not installed")

    client = storage.Client()
    bucket = client.bucket(settings.GCS_BUCKET)
    blob = bucket.blob(settings.GCS_EXCEL_FILE)
    if not blob.exists():
        raise FileNotFoundError(f"gs://{settings.GCS_BUCKET}/{settings.GCS_EXCEL_FILE} not found")
    blob.download_to_filename(str(dest))
    return dest