"""
Shared Pydantic response schemas (pagination, standard messages).
"""

from typing import Generic, TypeVar
from pydantic import BaseModel


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated list wrapper used by list APIs."""

    total: int
    page: int
    page_size: int
    items: list[T]


class MessageResponse(BaseModel):
    """Simple confirmation message response."""

    message: str
    detail: str | None = None

