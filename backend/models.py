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


class RefinementEntry(BaseModel):
    prompt: str
    seed: Optional[int] = None
    image_filename: Optional[str] = None
    model: str = ""


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
    refinement_history: list[RefinementEntry] = Field(default_factory=list)
    refinement_index: int = -1
    figure1_kf_id: Optional[str] = None
    figure2_kf_id: Optional[str] = None


class Transition(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    position: int
    from_keyframe_id: str
    to_keyframe_id: str
    prompt: str
    negative_prompt: str = ""
    duration: Optional[int] = None  # per-transition override; None = use project default
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
    locked: bool = False


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    activity: str = "film-director"
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
    narration_voice: str = ""
    narration_locked: bool = False
    score_locked: bool = False
    final_filename: Optional[str] = None
    original_prompts: list[str] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    soundtrack_sections: list["SoundtrackSection"] = Field(default_factory=list)
    images: list[GalleryImage] = Field(default_factory=list)
    sequences: list[Sequence] = Field(default_factory=list)
    active_sequence_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GalleryImage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    prompt: str = ""
    negative_prompt: str = ""
    model: str = "hidream"
    width: int = 1024
    height: int = 576
    seed: Optional[int] = None
    image_filename: Optional[str] = None
    figure1_id: Optional[str] = None
    figure2_id: Optional[str] = None
    status: KeyframeStatus = KeyframeStatus.pending
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SoundtrackSection(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    position: int = 0
    transition_ids: list[str] = Field(default_factory=list)
    prompt: str = ""
    bpm: int = 120
    keyscale: str = "C major"
    music_volume: float = 0.3
    narration_volume: float = 1.0
    status: KeyframeStatus = KeyframeStatus.pending
    seed: Optional[int] = None
    audio_filename: Optional[str] = None
    preview_filename: Optional[str] = None
    error_message: Optional[str] = None


class Sequence(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "Untitled Sequence"
    duration: int = 10
    negative_prompt: str = "fade, crossfade, smoke, clouds"
    keyframes: list[Keyframe] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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
    duration: Optional[int] = None


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
    activity: str = "film-director"


class GenerateStoryRequest(BaseModel):
    scene_count: int = 6
    scene_duration: int = 10
    width: int = 1280
    height: int = 720
    style: str = "transition-story"
