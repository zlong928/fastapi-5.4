from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BookRead(BaseModel):
    id: int
    title: str
    original_filename: str
    created_at: datetime
    last_opened_at: datetime | None = None

    model_config = {"from_attributes": True}


class BookUploadResponse(BaseModel):
    book_id: int
    title: str
    original_filename: str


class BookProgressRead(BaseModel):
    id: int
    book_id: int
    user_id: int | None = None
    location_cfi: str | None = None
    progress_percent: float | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class BookProgressUpdate(BaseModel):
    location_cfi: str = Field(..., min_length=1)
    progress_percent: float | None = Field(default=None, ge=0, le=1)
