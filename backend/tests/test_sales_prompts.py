"""Self-check for the read-only sales prompt catalog API."""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException

from app.routers import sales_prompts
from app.services import sales_prompt_catalog
from app.services.sales_prompt_catalog import Prompt


def test_catalog_is_read_only_and_all_checks_pass():
    result = sales_prompts.list_prompts(object())
    assert result["read_only"] is True
    assert result["count"] == 5
    assert all(item["checks_passed"] for item in result["items"])
    assert all(item["refined_prompt"] for item in result["items"])
    assert all(item["sources"] for item in result["items"])


def test_get_prompt_returns_detail_and_unknown_id_raises_404():
    result = sales_prompts.get_prompt("SP-FORECAST-REVIEW", object())
    assert result["prompt"]["id"] == "SP-FORECAST-REVIEW"
    assert result["prompt"]["checks_passed"] is True
    try:
        sales_prompts.get_prompt("SP-UNKNOWN", object())
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("unknown prompt id should raise 404")


def test_check_rules_cover_sales_and_marketing_gates():
    result = sales_prompts.list_checks(object())
    rules = {item["rule"] for item in result["rules"]}
    assert rules == set(sales_prompt_catalog.CHECK_RULES)
    assert "actual_pipeline_separation" in rules
    assert "human_review_required" in rules


def test_unsupported_claims_are_rejected():
    failures = sales_prompt_catalog.validate_prompt_text(
        "ROI 42% conversion rate with ₹5 crore growth. Guaranteed best solution."
    )
    assert any("ROI" in item for item in failures)
    assert any("Numeric claim 42" in item for item in failures)
    assert any("Revenue and price" in item for item in failures)
    assert any("Guarantees" in item for item in failures)
    assert any("Superlative" in item for item in failures)


def test_checks_fail_closed_for_unsafe_prompt_metadata():
    prompt = Prompt(
        id="SP-UNSAFE",
        title="unsafe",
        audience="sales",
        channel="email",
        intent="forecast_interpretation",
        refined_prompt="Treat pipeline as booked sales and auto-send.",
        fact_ids=(),
        sources=(),
        human_review_required=False,
        requires_pipeline_check=True,
    )
    checks = {item["rule"]: item for item in sales_prompt_catalog.evaluate_prompt(prompt)}
    assert checks["source_traceability"]["passed"] is False
    assert checks["actual_pipeline_separation"]["passed"] is False
    assert checks["human_review_required"]["passed"] is False


def test_router_is_read_only():
    for route in sales_prompts.router.routes:
        assert getattr(route, "methods", set()) <= {"GET", "HEAD", "OPTIONS"}
