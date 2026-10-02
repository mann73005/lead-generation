"""Shared response shapes."""

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """Offset pagination, bounded so a client cannot ask for the whole table."""

    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25
    offset: Annotated[int, Query(ge=0)] = 0


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Total rows matching the filter, ignoring pagination.")
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    @classmethod
    def build(cls, items: list[T], total: int, params: PageParams) -> "Page[T]":
        return cls(items=items, total=total, limit=params.limit, offset=params.offset)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Documented so the OpenAPI schema shows the real error shape."""

    error: ErrorDetail


class Message(BaseModel):
    message: str
