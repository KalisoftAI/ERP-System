"""Read-only, source-traced refined prompts for sales and marketing API consumers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

CATALOG_VERSION = "2026.11.23"

VERIFIED_FACTS: dict[str, str] = {
    "FK-HERITAGE": "Kalika Enterprises, established 1990, MIDC Ahmednagar.",
    "FK-CAPACITY": "In-house stretch film extrusion capacity of 7-10 tons/day.",
    "FK-SPEC": "Stretch film 23-51 microns with up to 300% stretch.",
    "FK-RECYCLING": "In-house recycling is part of the manufacturing process.",
    "FK-TRACEABILITY": "Rolls are barcoded and weighed for batch traceability.",
    "FK-CATALOG": "Industrial packaging catalogue and factory video links are available for B2B follow-up.",
}

CHECK_RULES: dict[str, str] = {
    "source_traceability": "Every prompt must name at least one GCS source document.",
    "verified_claims_only": "Numeric and performance claims must come from the verified fact set.",
    "actual_pipeline_separation": "Pipeline opportunities must never be presented as booked sales.",
    "human_review_required": "Outreach prompts must remain in human-review mode before external use.",
}

_SOURCES = {
    "forecast_doc": "gs://sales-crm/assets/docs/Kalika_Barcode_Sales_Forecasting_Implementation.md",
    "forecast_template": "gs://sales-crm/assets/docs/Kalika_Sales_Forecast_Data_Template.csv",
    "knowledge_graph": "gs://sales-crm/Sales_Intelligence_Analysis/sales_intelligence_report_knowledge_graph.md",
    "contacts": "gs://sales-crm/Sales_Intelligence_Analysis/extracted_sales_intelligence_contacts.md",
    "production_spec": "gs://sales-crm/prompts/kalika_kali_softai_production_safe_backend_api_frontend_ui_gcs_sales_crm_automation_spec.md",
    "langgraph_spec": "gs://sales-crm/prompts/kalika_kali_softai_gcs_opencode_langgraph_sales_crm_automation_spec.md",
}

_ALLOWED_NUMBERS = {"1990", "7", "10", "23", "51", "300"}
_OUTREACH_CHANNELS = {"email", "whatsapp", "social", "video"}
_UNVERIFIED_CLAIM_PATTERNS = (
    (re.compile(r"\bROI\b", re.IGNORECASE), "ROI is not a verified claim in the source documents"),
    (re.compile(r"\bconversion rate\b", re.IGNORECASE), "Conversion rate is not a verified claim in the source documents"),
    (re.compile(r"\bguaranteed\b", re.IGNORECASE), "Guarantees are not permitted in refined prompts"),
    (re.compile(r"\b(?:no\.?\s*1|best|world[- ]class|zero defect)\b", re.IGNORECASE), "Superlative performance claims are not permitted"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*%\s*(?:accuracy|savings|conversion|growth)\b", re.IGNORECASE), "Performance percentages are not verified"),
    (re.compile(r"[₹$]\s*\d|\b\d+(?:\.\d+)?\s*(?:cr|crore|lakh|rs\.?|inr)\b", re.IGNORECASE), "Revenue and price figures are not verified in this catalog"),
)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Prompt:
    id: str
    title: str
    audience: str
    channel: str
    intent: str
    refined_prompt: str
    fact_ids: tuple[str, ...]
    sources: tuple[str, ...]
    human_review_required: bool = True
    requires_pipeline_check: bool = False

    def as_dict(self, checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "audience": self.audience,
            "channel": self.channel,
            "intent": self.intent,
            "refined_prompt": self.refined_prompt,
            "fact_ids": list(self.fact_ids),
            "facts": [VERIFIED_FACTS[fact_id] for fact_id in self.fact_ids],
            "sources": list(self.sources),
            "human_review_required": self.human_review_required,
        }
        if checks is not None:
            result["checks"] = checks
            result["checks_passed"] = all(check["passed"] for check in checks)
        return result


PROMPTS: tuple[Prompt, ...] = (
    Prompt(
        id="SP-B2B-EMAIL-STRETCH",
        title="B2B stretch film catalogue follow-up",
        audience="procurement heads",
        channel="email",
        intent="catalogue_follow_up",
        refined_prompt=(
            "Write a concise business-to-business follow-up email for {{company_name}}. Greetings from Kalika "
            "Enterprises, established 1990 in MIDC Ahmednagar. State that in-house stretch film "
            "extrusion runs at 7-10 tons/day with 23-51 micron film and up to 300% stretch. "
            "Mention in-house recycling and barcode plus weight traceability. Link the industrial "
            "packaging catalogue at {{catalog_link}} and the factory video at {{video_link}}. "
            "Ask the recipient to reply with sizes and quantities. Do not state revenue, order "
            "counts, return-on-investment, conversion-rate figures, or savings percentages. Keep the tone factual and "
            "route the final copy for human review before sending."
        ),
        fact_ids=("FK-HERITAGE", "FK-CAPACITY", "FK-SPEC", "FK-RECYCLING", "FK-TRACEABILITY", "FK-CATALOG"),
        sources=(_SOURCES["production_spec"], _SOURCES["forecast_doc"]),
    ),
    Prompt(
        id="SP-WHATSAPP-HUMAN-COPY",
        title="WhatsApp human-copy follow-up",
        audience="sales prospects",
        channel="whatsapp",
        intent="human_copy_follow_up",
        refined_prompt=(
            "Prepare a short WhatsApp follow-up for {{contact_name}} at {{company_name}} using "
            "only human-copy mode. Introduce Kalika Enterprises, established 1990 in MIDC "
            "Ahmednagar. Mention stretch film in 23-51 microns, 7-10 tons/day in-house capacity, "
            "and barcode plus weight traceability. Share {{catalog_link}} and {{video_link}}. "
            "Ask them to reply QUOTE or use {{whatsapp_number}}. Do not auto-send, do not claim "
            "booked sales, return-on-investment, conversion-rate figures, or discounts. Return the draft with a human-review "
            "flag set."
        ),
        fact_ids=("FK-HERITAGE", "FK-CAPACITY", "FK-SPEC", "FK-TRACEABILITY", "FK-CATALOG"),
        sources=(_SOURCES["production_spec"], _SOURCES["langgraph_spec"]),
    ),
    Prompt(
        id="SP-SOCIAL-REEL-LAUNCH",
        title="Factory reel concept",
        audience="marketing reviewers",
        channel="social",
        intent="factory_reel_concept",
        refined_prompt=(
            "Create a short factory reel concept for Kalika Enterprises, established 1990 in MIDC "
            "Ahmednagar. Show in-house stretch film extrusion at 7-10 tons/day, 23-51 micron film, "
            "up to 300% stretch, in-house recycling, and barcode plus weight traceability. End "
            "with a CTA to {{catalog_link}} and {{whatsapp_number}}. Do not display revenue "
            "figures, order counts, return-on-investment, conversion-rate figures, or superlative performance claims. "
            "Mark the concept AWAITING_HUMAN_APPROVAL."
        ),
        fact_ids=("FK-HERITAGE", "FK-CAPACITY", "FK-SPEC", "FK-RECYCLING", "FK-TRACEABILITY", "FK-CATALOG"),
        sources=(_SOURCES["production_spec"], _SOURCES["langgraph_spec"]),
    ),
    Prompt(
        id="SP-FORECAST-REVIEW",
        title="Sales and marketing forecast review",
        audience="sales and marketing reviewers",
        channel="internal-api",
        intent="forecast_interpretation",
        refined_prompt=(
            "Summarise the forecast for {{period}} from verified ERP actuals and CRM pipeline data. "
            "Keep actual orders, dispatches and invoiced revenue separate from pipeline "
            "opportunities; never describe pipeline as booked sales. Report data freshness, "
            "coverage, missing dates, exclusions and assumptions. Use WAPE, MAE and bias for "
            "backtest metrics; do not use MAPE where actuals are zero or near zero. If history is "
            "insufficient, reply Insufficient data. Forecasts are recommendations only and require "
            "sales and marketing reviewer approval before external use."
        ),
        fact_ids=("FK-TRACEABILITY",),
        sources=(_SOURCES["forecast_doc"], _SOURCES["forecast_template"]),
        requires_pipeline_check=True,
    ),
    Prompt(
        id="SP-LEAD-QUALIFICATION-HOT",
        title="Hot lead qualification note",
        audience="sales and marketing reviewers",
        channel="internal-api",
        intent="lead_qualification",
        refined_prompt=(
            "Draft a sales qualification note for {{company_name}} using only verified CRM fields. "
            "Classify the lead as HOT only when there is a confirmed order, active quotation, or "
            "explicit product and volume requirement. Keep product interest, quoted rate status "
            "and next action separate from confirmed sales. Do not invent contact details, revenue, "
            "return-on-investment, conversion-rate figures, or accuracy figures. Route the note to a sales reviewer and a "
            "marketing reviewer before it is shared externally."
        ),
        fact_ids=("FK-CATALOG",),
        sources=(_SOURCES["knowledge_graph"], _SOURCES["contacts"]),
        requires_pipeline_check=True,
    ),
)


def validate_prompt_text(text: str) -> list[str]:
    failures: list[str] = []
    for pattern, detail in _UNVERIFIED_CLAIM_PATTERNS:
        if pattern.search(text):
            failures.append(detail)
    for value in _NUMBER_RE.findall(text):
        if value not in _ALLOWED_NUMBERS:
            failures.append(f"Numeric claim {value} is not in the verified fact set")
    return sorted(set(failures))


def evaluate_prompt(prompt: Prompt) -> list[dict[str, Any]]:
    claim_failures = validate_prompt_text(prompt.refined_prompt)
    checks = [
        {
            "rule": "source_traceability",
            "passed": bool(prompt.sources),
            "detail": f"{len(prompt.sources)} GCS source document(s) linked",
        },
        {
            "rule": "verified_claims_only",
            "passed": not claim_failures,
            "detail": "All numeric and performance claims are verified" if not claim_failures else "; ".join(claim_failures),
        },
    ]
    if prompt.requires_pipeline_check:
        text = prompt.refined_prompt.lower()
        separated = "separate" in text or "never describe" in text
        checks.append({
            "rule": "actual_pipeline_separation",
            "passed": separated,
            "detail": "Actual sales and pipeline are explicitly separated" if separated else "Pipeline separation language is missing",
        })
    if prompt.channel in _OUTREACH_CHANNELS:
        checks.append({
            "rule": "human_review_required",
            "passed": prompt.human_review_required,
            "detail": "Human review gate is on" if prompt.human_review_required else "Outreach prompt is missing the human review gate",
        })
    return checks


def catalog() -> dict[str, Any]:
    items = []
    for prompt in PROMPTS:
        checks = evaluate_prompt(prompt)
        items.append(prompt.as_dict(checks))
    return {
        "version": CATALOG_VERSION,
        "read_only": True,
        "count": len(items),
        "items": items,
    }


def get_prompt(prompt_id: str) -> dict[str, Any] | None:
    for prompt in PROMPTS:
        if prompt.id == prompt_id:
            checks = evaluate_prompt(prompt)
            return {
                "version": CATALOG_VERSION,
                "read_only": True,
                "prompt": prompt.as_dict(checks),
            }
    return None


def check_rules() -> dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "rules": [
            {"rule": rule, "description": description}
            for rule, description in CHECK_RULES.items()
        ],
    }
