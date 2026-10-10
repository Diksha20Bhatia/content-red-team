"""Protocol validation. A run that breaks these rules fails rather than silently continuing."""
from __future__ import annotations

import re

from .models import Critique, MemberReport, Rebuttal

MIN_REASON_CHARS = 15


def _norm(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def _report_text(r: MemberReport) -> str:
    return " ".join(p.claim + " " + p.evidence for rv in r.reviews for p in rv.keep + rv.fix)


def validate_report(rep: MemberReport, inputs: dict, rubric: dict) -> list[str]:
    errs: list[str] = []
    got = {r.asset: r for r in rep.reviews}
    for a in inputs["assets"]:
        if a not in got:
            errs.append(f"missing review for asset '{a}'")
            continue
        r = got[a]
        missing = set(rubric[a]) - set(r.scores)
        if missing:
            errs.append(f"{a}: missing score dimensions {sorted(missing)}")
        for p in r.fix:
            if len(p.evidence.strip()) < 5:
                errs.append(f"{a}: fix point without evidence: '{p.claim[:50]}'")
        for p in r.keep:
            if len(p.evidence.strip()) < 5:
                errs.append(f"{a}: keep point without evidence: '{p.claim[:50]}'")
        if not r.fix and not r.keep:
            errs.append(f"{a}: no keep/fix points")
    if len(inputs["titles"]) > 1 and "title" not in rep.variant_ranking:
        errs.append("title variants present but variant_ranking['title'] missing")
    if len(inputs["thumbnails"]) > 1 and "thumbnail" not in rep.variant_ranking:
        errs.append("thumbnail variants present but variant_ranking['thumbnail'] missing")
    return errs


def validate_critique(c: Critique, me: str, reports: dict[str, MemberReport]) -> list[str]:
    errs: list[str] = []
    for kind, items in (("challenge", c.challenges), ("endorsement", c.endorsements), ("flag", c.flags)):
        for q in items:
            if q.target_member == me or q.target_member not in reports:
                errs.append(f"{kind}: target_member '{q.target_member}' must be another panelist id {sorted(reports)}")
                continue
            qt, tt = set(_norm(q.quoted_point)), set(_norm(_report_text(reports[q.target_member])))
            if not qt or len(qt & tt) / len(qt) < 0.6:
                errs.append(f"{kind}: quoted_point does not match {q.target_member}'s report: '{q.quoted_point[:60]}'")
    if len({q.quoted_point for q in c.challenges}) < 2:
        errs.append("need 2 distinct challenged points")
    return errs


def validate_rebuttal(r: Rebuttal, own: MemberReport) -> list[str]:
    errs: list[str] = []
    orig = {rv.asset: rv for rv in own.reviews}
    for ch in r.score_changes:
        tag = f"{ch.asset}/{ch.dimension}"
        if len(ch.because.strip()) < MIN_REASON_CHARS:
            errs.append(f"score change {tag} {ch.before}->{ch.after} has no real reason")
        if ch.asset not in orig:
            errs.append(f"score change for unknown asset {ch.asset}")
            continue
        rv = orig[ch.asset]
        cur = rv.overall if ch.dimension == "overall" else rv.scores.get(ch.dimension)
        if cur is None:
            errs.append(f"score change {tag}: unknown dimension")
        elif cur != ch.before:
            errs.append(f"score change {tag}: 'before'={ch.before} but your phase-1 score was {cur}")
        if not 1 <= ch.after <= 10 or ch.after == ch.before:
            errs.append(f"score change {tag}: invalid after={ch.after}")
    return errs


def suspicious_consensus(reports: dict[str, MemberReport], critiques: dict[str, Critique]) -> bool:
    """True when members agree on everything: tiny overall spread on every asset and no real challenge."""
    assets = {rv.asset for r in reports.values() for rv in r.reviews}
    tight = all(
        max(rv.overall for r in reports.values() for rv in r.reviews if rv.asset == a)
        - min(rv.overall for r in reports.values() for rv in r.reviews if rv.asset == a) <= 1
        for a in assets
    )
    claims: dict[str, set] = {}
    for r in reports.values():
        for rv in r.reviews:
            for kind, ps in (("keep", rv.keep), ("fix", rv.fix)):
                for p in ps:
                    claims.setdefault(p.claim.split(":")[0], set()).add(kind)
    opposing = any(len(v) > 1 for v in claims.values()) or any(c.flags for c in critiques.values())
    return tight and not opposing


def final_scores(reports: dict[str, MemberReport], rebuttals: dict[str, Rebuttal]) -> dict:
    """member -> asset -> {dimension|overall: score} after applying logged rebuttal changes."""
    out: dict = {}
    for mid, rep in reports.items():
        out[mid] = {rv.asset: {**rv.scores, "overall": rv.overall} for rv in rep.reviews}
        for ch in rebuttals[mid].score_changes:
            if ch.asset in out[mid]:
                out[mid][ch.asset][ch.dimension] = ch.after
    return out


def drift_ratio(reports: dict[str, MemberReport], rebuttals: dict[str, Rebuttal]) -> tuple[int, int]:
    """(# changes that moved toward the group mean, # changes). High ratio with weak reasons = drift."""
    toward = total = 0
    for mid, reb in rebuttals.items():
        for ch in reb.score_changes:
            others = []
            for oid, rep in reports.items():
                if oid == mid:
                    continue
                for rv in rep.reviews:
                    if rv.asset == ch.asset:
                        v = rv.overall if ch.dimension == "overall" else rv.scores.get(ch.dimension)
                        if v is not None:
                            others.append(v)
            if others:
                mean = sum(others) / len(others)
                total += 1
                toward += abs(ch.after - mean) < abs(ch.before - mean)
    return toward, total


def count_disagreements(reports: dict[str, MemberReport]) -> list[str]:
    """Topics (claim prefix before ':') that some members keep and others fix. Mock/diagnostic aid."""
    seen: dict[str, set] = {}
    for r in reports.values():
        for rv in r.reviews:
            for p in rv.keep:
                seen.setdefault(p.claim.split(":")[0], set()).add("keep")
            for p in rv.fix:
                seen.setdefault(p.claim.split(":")[0], set()).add("fix")
    return [t for t, k in seen.items() if len(k) > 1]
