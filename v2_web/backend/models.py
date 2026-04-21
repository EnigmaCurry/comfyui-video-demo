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
    model: str = "hidream"
    status: KeyframeStatus = KeyframeStatus.pending
    seed: Optional[int] = None
    image_filename: Optional[str] = None
    negative_prompt: str = ""
    locked: bool = False
    error_message: Optional[str] = None


class Transition(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    position: int
    from_keyframe_id: str
    to_keyframe_id: str
    prompt: str
    negative_prompt: str = ""
    status: KeyframeStatus = KeyframeStatus.pending
    seed: Optional[int] = None
    video_filename: Optional[str] = None
    narration: str = ""
    narration_voice: str = ""
    narration_seed: Optional[int] = None
    narration_status: KeyframeStatus = KeyframeStatus.pending
    audio_filename: Optional[str] = None
    narrated_video_filename: Optional[str] = None
    narration_error: Optional[str] = None
    error_message: Optional[str] = None


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    notes: str = ""
    premise: str = ""
    premise_locked: bool = False
    story_locked: bool = False
    keyframes_locked: bool = False
    transitions_locked: bool = False
    scene_count: int = 6
    scene_duration: int = 10
    width: int = 1024
    height: int = 576
    style: str = "transition-story"
    active_index: int = 0
    transition_active_index: int = 0
    narration_active_index: int = 0
    narration_direction: str = ""
    narration_locked: bool = False
    score_locked: bool = False
    final_filename: Optional[str] = None
    original_prompts: list[str] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    soundtrack_sections: list["SoundtrackSection"] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SoundtrackSection(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    position: int = 0
    transition_ids: list[str] = Field(default_factory=list)
    prompt: str = ""
    bpm: int = 120
    keyscale: str = "C major"
    music_volume: float = 0.3
    narration_volume: float = 2.0
    status: KeyframeStatus = KeyframeStatus.pending
    seed: Optional[int] = None
    audio_filename: Optional[str] = None
    preview_filename: Optional[str] = None
    error_message: Optional[str] = None


class GenerateRequest(BaseModel):
    theme: str
    count: int = 6
    style: str = "transition-story"


class RenderRequest(BaseModel):
    prompt: Optional[str] = None
    seed: Optional[int] = None
    width: int = 1280
    height: int = 720


class UpdateKeyframeRequest(BaseModel):
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    model: Optional[str] = None
    position: Optional[int] = None


class UpdateTransitionRequest(BaseModel):
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None


class TransitionRenderRequest(BaseModel):
    seed: Optional[int] = None
    width: int = 1280
    height: int = 720
    frame_rate: int = 25
    duration_seconds: int = 10


class SuggestPremiseRequest(BaseModel):
    notes: str


class SetPremiseRequest(BaseModel):
    premise: str


class GenerateStoryRequest(BaseModel):
    scene_count: int = 6
    scene_duration: int = 10
    width: int = 1280
    height: int = 720
    style: str = "transition-story"
