"""Pydantic schemas for every phase of the panel."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Asset = Literal["title", "thumbnail", "script"]
Severity = Literal["minor", "major", "blocker"]


class Point(BaseModel):
    claim: str
    evidence: str  # quote, line number, timestamp, or thumbnail region
    severity: Severity = "minor"


class AssetReview(BaseModel):
    asset: Asset
    scores: dict[str, int]  # rubric dimensions, 1-10
    overall: int = Field(ge=1, le=10)
    keep: list[Point] = []
    fix: list[Point] = []
    risks: list[str] = []
    rewrite: str | None = None
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator("scores")
    @classmethod
    def _score_range(cls, v: dict[str, int]) -> dict[str, int]:
        for k, s in v.items():
            if not 1 <= s <= 10:
                raise ValueError(f"score {k}={s} outside 1-10")
        return v


class MemberReport(BaseModel):
    """Phase 1 output of one member."""

    summary: str = ""
    reviews: list[AssetReview]
    variant_ranking: dict[str, list[str]] = {}  # asset -> labels best-first
    ranking_reason: str = ""


class Quoted(BaseModel):
    target_member: str
    quoted_point: str  # exact text of the other member's claim
    comment: str  # objection, endorsement reason, or why-wrong


class Critique(BaseModel):
    challenges: list[Quoted]
    endorsements: list[Quoted]
    flags: list[Quoted] = []

    @field_validator("challenges")
    @classmethod
    def _two_challenges(cls, v: list[Quoted]) -> list[Quoted]:
        if len(v) < 2:
            raise ValueError("need at least 2 challenges")
        return v

    @field_validator("endorsements")
    @classmethod
    def _one_endorsement(cls, v: list[Quoted]) -> list[Quoted]:
        if len(v) < 1:
            raise ValueError("need at least 1 endorsement")
        return v


class Response(BaseModel):
    to_member: str
    stance: Literal["defend", "concede", "modify"]
    reasoning: str


class ScoreChange(BaseModel):
    asset: Asset
    dimension: str  # a rubric dimension or "overall"
    before: int
    after: int
    because: str


class Rebuttal(BaseModel):
    responses: list[Response]
    score_changes: list[ScoreChange] = []


class Dispute(BaseModel):
    topic: str
    positions: dict[str, str]  # member id -> position
    ruling: str
    reasoning: str


class MergedPoint(BaseModel):
    asset: Asset
    claim: str
    evidence: str = ""
    severity: Severity = "minor"
    agreed_by: list[str] = []
    disagreed_by: list[str] = []


class AssetVerdict(BaseModel):
    asset: Asset
    verdict: Literal["ship", "fix then ship", "rework"]
    reason: str


class RankedFix(BaseModel):
    fix: str
    asset: Asset
    impact: int = Field(ge=1, le=5)
    effort: int = Field(ge=1, le=5)


class ThumbConcept(BaseModel):
    text: str
    visual: str
    emotion: str
    colours: str
    remove: str


class ScriptEdit(BaseModel):
    section: str
    action: Literal["cut", "tighten", "add"]
    note: str


class ShortMoment(BaseModel):
    moment: str
    why: str


class Rewrites(BaseModel):
    titles: list[str]
    thumbnails: list[ThumbConcept]
    script_hook: str
    script_edits: list[ScriptEdit] = []
    shorts: list[ShortMoment] = []


class Verdict(BaseModel):
    asset_verdicts: list[AssetVerdict]
    keep: list[MergedPoint]
    fix: list[MergedPoint]
    disputes: list[Dispute]
    ranked_fixes: list[RankedFix]
    rewrites: Rewrites
    confidence_note: str
    ab_tests: list[str] = []
    devils_advocate: str | None = None


class ValidationProblem(Exception):
    """Raised when a phase output breaks the protocol (e.g. unexplained score change)."""
