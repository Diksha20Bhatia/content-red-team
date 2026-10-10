"""Phase logic: builds isolated calls, validates, retries with feedback, checkpoints."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from . import prompts, validate
from .config import persona_card
from .llm import LLM, Call
from .models import Critique, MemberReport, Rebuttal, ValidationProblem, Verdict

MAX_RETRIES = 2


class Engine:
    def __init__(self, cfg: dict, inputs: dict, rubric: dict, llm: LLM, out: Path, cache_dir: Path):
        self.cfg, self.inputs, self.rubric, self.llm, self.out = cfg, inputs, rubric, llm, out
        self.members: list[dict] = cfg["members"]
        self.by_id = {m["id"]: m for m in self.members}
        self.names = {m["id"]: m["name"] for m in self.members}
        self.cards = {m["id"]: persona_card(m, cache_dir) for m in self.members}
        self.ckpt = out / ".checkpoints"
        self.images = prompts.images_for(inputs)

    # ---- checkpoints -------------------------------------------------
    def _load(self, phase: str, mid: str, schema: type[BaseModel]) -> BaseModel | None:
        f = self.ckpt / phase / f"{mid}.json"
        if f.exists():
            try:
                return schema.model_validate_json(f.read_text())
            except ValidationError:
                return None
        return None

    def _save(self, phase: str, mid: str, obj: BaseModel) -> None:
        f = self.ckpt / phase / f"{mid}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(obj.model_dump_json(indent=2))

    # ---- generic validated call -------------------------------------
    def _run(self, phase: str, mid: str, system: str, user: str, schema: type[BaseModel],
             check: Callable[[Any], list[str]], context: dict, images: list[str], model: str | None = None) -> Any:
        cached = self._load(phase, mid, schema)
        if cached is not None:
            return cached
        feedback = ""
        errs: list[str] = []
        for _ in range(MAX_RETRIES + 1):
            call = Call(phase=phase, member_id=mid, system=system, user=user + feedback, schema=schema,
                        images=images, context=context, model=model, max_tokens=self.cfg["max_tokens"])
            try:
                obj = self.llm.call(call)
            except ValidationError as e:
                errs = [f"schema: {x['loc']}: {x['msg']}" for x in e.errors()[:6]]
            else:
                errs = check(obj)
                if not errs:
                    self._save(phase, mid, obj)
                    return obj
            feedback = "\n\nYOUR PREVIOUS ANSWER WAS REJECTED. Fix these problems and answer again:\n- " + "\n- ".join(errs)
        raise ValidationProblem(f"{phase}/{mid} failed validation after retries: {errs}")

    # ---- phases --------------------------------------------------------
    def index(self, mid: str) -> int:
        return [m["id"] for m in self.members].index(mid)

    def build_phase1(self, mid: str) -> dict:
        m = self.by_id[mid]
        system, user = prompts.phase1(m, self.cards[mid][0], self.inputs, self.rubric)
        ctx = {"member": m, "index": self.index(mid), "inputs": self.inputs, "rubric": self.rubric}
        return dict(phase="phase1", mid=mid, system=system, user=user, schema=MemberReport, context=ctx,
                    images=self.images, check=lambda r: validate.validate_report(r, self.inputs, self.rubric))

    def build_critique(self, mid: str, reports: dict[str, MemberReport]) -> dict:
        m = self.by_id[mid]
        others = {k: v for k, v in reports.items() if k != mid}
        system, user = prompts.phase2(m, self.cards[mid][0], self.inputs, reports[mid], others, self.names)
        ctx = {"member": m, "index": self.index(mid), "inputs": self.inputs, "own": reports[mid], "others": others}
        return dict(phase="critique", mid=mid, system=system, user=user, schema=Critique, context=ctx,
                    images=self.images, check=lambda c: validate.validate_critique(c, mid, reports))

    @staticmethod
    def aimed_at(mid: str, critiques: dict[str, Critique]) -> list[dict]:
        out = []
        for cid, c in critiques.items():
            for kind, items in (("challenge", c.challenges), ("endorsement", c.endorsements), ("flag", c.flags)):
                out += [{"from": cid, "kind": kind, "quoted_point": q.quoted_point, "comment": q.comment}
                        for q in items if q.target_member == mid]
        return out

    def build_rebuttal(self, mid: str, reports: dict[str, MemberReport], critiques: dict[str, Critique]) -> dict:
        m = self.by_id[mid]
        aimed = self.aimed_at(mid, critiques)
        system, user = prompts.phase3(m, self.cards[mid][0], self.inputs, reports[mid], aimed)
        ctx = {"member": m, "index": self.index(mid), "inputs": self.inputs, "own": reports[mid], "aimed": aimed}
        return dict(phase="rebuttal", mid=mid, system=system, user=user, schema=Rebuttal, context=ctx,
                    images=[], check=lambda r: validate.validate_rebuttal(r, reports[mid]))

    def build_judge(self, reports, critiques, rebuttals) -> dict:
        changes = [{"member": mid, **ch.model_dump()} for mid, r in rebuttals.items() for ch in r.score_changes]
        sus = validate.suspicious_consensus(reports, critiques)
        system, user = prompts.judge(self.inputs, self.rubric, reports, critiques, rebuttals, self.names, sus, changes)
        weights = ", ".join(f"{m['name']}={m['weight']}" for m in self.members)
        user += f"\nPanel weights (how much to weigh each voice when evidence is equal): {weights}"
        ctx = {"inputs": self.inputs, "names": self.names, "reports": reports, "critiques": critiques,
               "rebuttals": rebuttals, "suspicious": sus, "score_changes": changes}
        return dict(phase="judge", mid="judge", system=system, user=user, schema=Verdict, context=ctx,
                    images=[], model=self.cfg["judge_model"], check=lambda v: self._check_verdict(v, sus))

    def _check_verdict(self, v: Verdict, sus: bool) -> list[str]:
        errs = []
        got = {a.asset for a in v.asset_verdicts}
        for a in self.inputs["assets"]:
            if a not in got:
                errs.append(f"no verdict for asset {a}")
        if len(v.rewrites.titles) < 3 and self.inputs["titles"]:
            errs.append("need 3 title options")
        if sus and not v.devils_advocate:
            errs.append("panel was suspiciously unanimous: devils_advocate is required")
        for d in v.disputes:
            if not d.ruling.strip():
                errs.append(f"dispute '{d.topic}' has no ruling")
        return errs

    def execute(self, spec: dict) -> Any:
        s = dict(spec)
        mid = s.pop("mid")
        return self._run(s.pop("phase"), mid, s.pop("system"), s.pop("user"), s.pop("schema"), s.pop("check"),
                         s.pop("context"), s.pop("images"), s.pop("model", None))


def read_json(p: Path) -> Any:
    return json.loads(p.read_text())
