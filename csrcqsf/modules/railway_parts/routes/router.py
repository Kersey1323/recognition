"""Shared router for railway parts public APIs."""

from fastapi import APIRouter


parts_router = APIRouter(
    prefix="/railway/parts",
    tags=["railway"],
    responses={404: {"description": "Not found"}},
)
