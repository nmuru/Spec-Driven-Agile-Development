"""Schemas for the phase-based intent-to-specification workflow."""

from pydantic import BaseModel


class SpecificationRequest(BaseModel):
    intent: str
    repo_url: str
    provider: str = "openrouter"
    model: str = "openrouter/free"
    api_key: str
    work_id: str | None = None


class SpecificationResult(BaseModel):
    run_id: str
    intent: str
    scope: str
    business_requirements: str
    software_requirements: str
    design: str
    tasks: str
    specification: str
    review: str
