"""Pydantic models for API request/response."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class KeyframeStatus(str, Enum):
    pending = "pending"
    rendering = "rendering"
    done = "done"
    error = "error"


class Keyframe(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    position: int
    prompt: str
    status: KeyframeStatus = KeyframeStatus.pending
    seed: Optional[int] = None
    image_filename: Optional[str] = None
    locked: bool = False
    error_message: Optional[str] = None


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    theme: str
    scene_count: int
    style: str = "transition-story"
    active_index: int = 0
    keyframes: list[Keyframe] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GenerateRequest(BaseModel):
    theme: str
    count: int = 6
    style: str = "transition-story"


class RenderRequest(BaseModel):
    prompt: Optional[str] = None
    seed: Optional[int] = None
    width: int = 1920
    height: int = 1088


class UpdateKeyframeRequest(BaseModel):
    prompt: Optional[str] = None
    position: Optional[int] = None
