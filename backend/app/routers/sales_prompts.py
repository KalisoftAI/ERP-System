"""JWT-gated read-only API for refined sales and marketing prompts."""
from fastapi import APIRouter, HTTPException, status

from ..auth import CurrentUser
from ..services import sales_prompt_catalog

router = APIRouter(
    prefix="/api/v1/sales-ops/prompts",
    tags=["sales-ops-prompts"],
)


@router.get("")
def list_prompts(_: CurrentUser):
    return sales_prompt_catalog.catalog()


@router.get("/checks")
def list_checks(_: CurrentUser):
    return sales_prompt_catalog.check_rules()


@router.get("/{prompt_id}")
def get_prompt(prompt_id: str, _: CurrentUser):
    result = sales_prompt_catalog.get_prompt(prompt_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Prompt {prompt_id} not found")
    return result
