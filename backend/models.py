"""Pydantic request/response models shared by routers.

Pure module — pydantic only, no app imports — so routers and main can import it
freely. As domains migrate out of main.py their models land here; main.py
re-exports them so existing ``from main import <Model>`` usages keep working.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ProvisioningTenantRow(BaseModel):
    client_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    area_code: Optional[str] = None
    plan: str = "free"


class ProvisioningJobRequest(BaseModel):
    tenants: List[ProvisioningTenantRow] = Field(..., min_length=1, max_length=500)
    default_area_code: Optional[str] = None


class SmsAutomationCreate(BaseModel):
    trigger: Literal["after_inquiry", "post_call"]
    template: str


class SmsAutomationUpdate(BaseModel):
    template: Optional[str] = None
    enabled: Optional[bool] = None
