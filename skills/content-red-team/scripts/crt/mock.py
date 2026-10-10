"""Deterministic mock LLM for --dry-run, tests and CI. Makes no network calls and needs no key.

It is NOT a review: output is templated from the inputs so the pipeline, validation, isolation,
parallelism and writers can be exercised. Members take opposing stances on shared topics
(by panel position) so that disputes exist and the judge has something to rule on.
Every output carries a [[OUT:<phase>:<member>]] token so tests can prove nothing leaked.
"""
from __future__ import annotations

import time
import zlib
from typing import Any

from pydantic import BaseModel

from .llm import Call
from .models import (
    AssetReview,
    AssetVerdict,
    Critique,
    Dispute,
    MemberReport,
    MergedPoint,
    Point,
    Quoted,
    RankedFix,
    Rebuttal,
    Response,
    Rewrites,
    ScoreChange,
    ScriptEdit,
    ShortMoment,
    ThumbConcept,
    Verdict,
)

TOPICS = {
    "title": ["Title length on a mobile feed", "Curiosity gap versus honest promise"],
    "thumbnail": ["Amount of text on the thumbnail", "Single focal point and emotion"],
    "script": ["Cold open versus context-setting intro", "CTA placement and tone", "Jargon level for the audience"],
}
SEV = ["minor", "major", "blocker"]


def _h(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())


def token(phase: str, member: str) -> str:
    return f"[[OUT:{phase}:{member}]]"


def _evidence(asset: str, inputs: dict, seed: int) -> str:
    if asset == "title":
        t = inputs["titles"][0]
        return f'Title {t["label"]}: "{t["text"]}" ({len(t["text"])} chars)'
    if asset == "thumbnail":
        th = inputs["thumbnails"][0]
        m = th["metrics"]
        return (f'Thumbnail {th["label"]} at 120px preview: contrast_std={m["contrast_std"]}, '
                f'edge_density_120={m["edge_density_120"]}, dominant colour {m["dominant_hex"]}, text "{th.get("text", "")}"')
    lines = [(i, ln) for i, ln in enumerate(inputs["script"]["text"].splitlines(), 1) if ln.strip()]
    i, ln = lines[seed % len(lines)]
    return f'L{i:03d}: "{" ".join(ln.split()[:12])}"'


def _stance_keep(index: int, topic_idx: int) -> bool:
    return (index + topic_idx) % 2 == 0


def phase1(c: Call) -> MemberReport:
    ctx = c.context
    m, idx, inputs, rubric = ctx["member"], ctx["index"], ctx["inputs"], ctx["rubric"]
    reviews = []
    t_idx = 0
    for asset in inputs["assets"]:
        scores = {d: 4 + _h(m["id"], asset, d) % 5 for d in rubric[asset]}
        keep, fix = [], []
        for topic in TOPICS[asset]:
            ev = _evidence(asset, inputs, _h(m["id"], topic))
            if _stance_keep(idx, t_idx):
                keep.append(Point(claim=f"{topic}: works as intended", evidence=ev, severity="minor"))
            else:
                fix.append(Point(claim=f"{topic}: is a problem", evidence=ev, severity=SEV[_h(m["id"], topic) % 3]))
            t_idx += 1
        overall = max(1, min(10, round(sum(scores.values()) / len(scores))))
        reviews.append(AssetReview(
            asset=asset, scores=scores, overall=overall, keep=keep, fix=fix,
            risks=[f"{m['name']}: unsupported claims need checking (mock)"],
            rewrite=f"[MOCK rewrite by {m['name']}]", confidence="medium"))
    rank = {}
    if len(inputs["titles"]) > 1:
        labels = [t["label"] for t in inputs["titles"]]
        rank["title"] = labels[idx % len(labels):] + labels[: idx % len(labels)]
    if len(inputs["thumbnails"]) > 1:
        labels = [t["label"] for t in inputs["thumbnails"]]
        rank["thumbnail"] = labels[idx % len(labels):] + labels[: idx % len(labels)]
    return MemberReport(summary=f"{m['name']} mock summary {token('p1', m['id'])}", reviews=reviews,
                        variant_ranking=rank, ranking_reason="mock ranking" if rank else "")


def _points(report: MemberReport) -> list[tuple[str, str, Point]]:
    return [(r.asset, kind, p) for r in report.reviews for kind, ps in (("keep", r.keep), ("fix", r.fix)) for p in ps]


def critique(c: Call) -> Critique:
    ctx = c.context
    me = ctx["member"]["id"]
    own_topics = {p.claim.split(":")[0]: kind for _, kind, p in _points(ctx["own"])}
    challenges, endorse = [], []
    for oid, rep in ctx["others"].items():
        for _asset, kind, p in _points(rep):
            topic = p.claim.split(":")[0]
            if own_topics.get(topic) and own_topics[topic] != kind and len(challenges) < 3:
                challenges.append(Quoted(target_member=oid, quoted_point=p.claim,
                                         comment=f"I disagree on '{topic}'. {token('p2', me)}"))
            elif len(endorse) < 1 and own_topics.get(topic) == kind:
                endorse.append(Quoted(target_member=oid, quoted_point=p.claim,
                                      comment=f"Fair point I underweighted. {token('p2', me)}"))
    if not endorse:  # always able to endorse something
        oid, rep = next(iter(ctx["others"].items()))
        endorse.append(Quoted(target_member=oid, quoted_point=_points(rep)[0][2].claim,
                              comment=f"Worth acting on. {token('p2', me)}"))
    while len(challenges) < 2:  # weak fallback so protocol minimum always holds
        oid, rep = list(ctx["others"].items())[len(challenges) % len(ctx["others"])]
        challenges.append(Quoted(target_member=oid, quoted_point=_points(rep)[-1][2].claim,
                                 comment=f"Needs stronger evidence. {token('p2', me)}"))
    return Critique(challenges=challenges, endorsements=endorse, flags=[])


def rebuttal(c: Call) -> Rebuttal:
    ctx = c.context
    me = ctx["member"]["id"]
    own: MemberReport = ctx["own"]
    responses, changes, used = [], [], False
    for i, a in enumerate(ctx["aimed"]):
        concede = (_h(me, str(i)) % 3 == 0) and not used
        if concede:
            rv = own.reviews[0]
            dim = next(iter(rv.scores))
            before = rv.scores[dim]
            after = max(1, before - 1) if before > 1 else 2
            changes.append(ScoreChange(asset=rv.asset, dimension=dim, before=before, after=after,
                                       because=f"{a['from']}'s point on '{a['quoted_point'][:40]}' exposed a weakness I had missed"))
            used = True
        responses.append(Response(to_member=a["from"], stance="concede" if concede else "defend",
                                  reasoning=f"{'Conceding' if concede else 'Holding my position'} on that. {token('p3', me)}"))
    if not responses:
        responses.append(Response(to_member="judge", stance="defend", reasoning=f"Nothing aimed at me. {token('p3', me)}"))
    return Rebuttal(responses=responses, score_changes=changes)


def judge(c: Call) -> Verdict:
    ctx = c.context
    names, reports, inputs = ctx["names"], ctx["reports"], ctx["inputs"]
    by_topic: dict[str, dict[str, list[tuple[str, Point, str]]]] = {}
    for mid, rep in reports.items():
        for asset, kind, p in _points(rep):
            by_topic.setdefault(p.claim.split(":")[0], {"keep": [], "fix": []})[kind].append((mid, p, asset))
    disputes, keep, fix = [], [], []
    for topic, d in by_topic.items():
        if d["keep"] and d["fix"]:
            positions = {m: "works" for m, _, _ in d["keep"]} | {m: "problem" for m, _, _ in d["fix"]}
            worst = max(d["fix"], key=lambda x: SEV.index(x[1].severity))
            disputes.append(Dispute(topic=topic, positions={names[k]: v for k, v in positions.items()},
                                    ruling=f"Treat as a problem (severity {worst[1].severity}): fix before shipping.",
                                    reasoning="The fix side cited concrete evidence; the keep side described intent. Mock ruling."))
        for kind, bucket in (("keep", keep), ("fix", fix)):
            if d[kind]:
                m0, p0, asset = d[kind][0]
                other = "fix" if kind == "keep" else "keep"
                bucket.append(MergedPoint(asset=asset, claim=p0.claim, evidence=p0.evidence, severity=p0.severity,
                                          agreed_by=[names[m] for m, _, _ in d[kind]],
                                          disagreed_by=[names[m] for m, _, _ in d[other]]))
    avg = {}
    for a in inputs["assets"]:
        vals = [r.overall for rep in reports.values() for r in rep.reviews if r.asset == a]
        avg[a] = sum(vals) / len(vals)
    av = [AssetVerdict(asset=a, verdict="ship" if s >= 8 else "fix then ship" if s >= 6 else "rework",
                       reason=f"Mock: mean overall {s:.1f} (judgment, not data); disputes ruled below.") for a, s in avg.items()]
    ranked = [RankedFix(fix=p.claim, asset=p.asset, impact={"blocker": 5, "major": 4, "minor": 2}[p.severity], effort=2) for p in fix]
    ranked.sort(key=lambda r: -r.impact)
    t0 = inputs["titles"][0]["text"] if inputs["titles"] else "Untitled"
    rw = Rewrites(
        titles=[f"[MOCK] {t0[:50]}", f"[MOCK] Shorter: {t0[:30]}", f"[MOCK] Question form: {t0[:40]}?"],
        thumbnails=[ThumbConcept(text="3-4 WORDS", visual="face left, text right", emotion="surprise", colours="high-contrast yellow on dark", remove="secondary text") for _ in range(2)],
        script_hook="[MOCK] Open with the payoff in the first sentence, then the stakes.",
        script_edits=[ScriptEdit(section="intro", action="tighten", note="mock"), ScriptEdit(section="outro", action="cut", note="mock")],
        shorts=[ShortMoment(moment="[MOCK] strongest 45s example", why="self-contained"), ShortMoment(moment="[MOCK] myth-bust beat", why="clear hook")]
        if inputs["format"] == "long" else [],
    )
    return Verdict(asset_verdicts=av, keep=keep, fix=fix, disputes=disputes, ranked_fixes=ranked, rewrites=rw,
                   confidence_note="Mock run: all content is templated. Scores are judgment; A/B test title and thumbnail.",
                   ab_tests=["Title A vs B", "Thumbnail text length"],
                   devils_advocate="[MOCK] Strongest case against the consensus." if ctx["suspicious"] else None)


class MockLLM:
    def __init__(self, delay: float = 0.05):
        self.delay = delay

    def call(self, call: Call) -> BaseModel:
        time.sleep(self.delay)  # lets tests observe real concurrency
        fn: Any = {"phase1": phase1, "critique": critique, "rebuttal": rebuttal, "judge": judge}[call.phase]
        return fn(call)
