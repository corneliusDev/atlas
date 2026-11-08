"""System routes: health and the vault list."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from atlas.http.dto import HealthResponse, VaultListResponse
from atlas.http.routes_common import get_health_check, get_vault_reader, need
from atlas.read.protocols import HealthCheck, VaultReader

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse, tags=["system"])
def health(check: Annotated[HealthCheck | None, Depends(get_health_check)]) -> HealthResponse:
    return need(check, "health").check()


@router.get("/api/vaults", response_model=VaultListResponse, tags=["vaults"])
def list_vaults(vaults: Annotated[VaultReader | None, Depends(get_vault_reader)]) -> VaultListResponse:
    return VaultListResponse(vaults=need(vaults, "list vaults").vaults())
