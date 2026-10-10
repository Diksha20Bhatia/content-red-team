"""Prompt builders. Each builder receives ONLY what that member may see (isolation by construction)."""
from __future__ import annotations

import json
from typing import Any

from .models import AssetReview, Critique, MemberReport, Rebuttal

BASE_RULES = """You are a member of a panel red-teaming YouTube content before it ships.
Stay fully in character: use your persona's bias, priorities and vocabulary. Do not hedge toward neutrality.
Rules:
- Every `fix` point needs concrete evidence: a quote, line number (L001 style), timestamp estimate, or a thumbnail region.
- No vague praise or vague criticism. Be specific and brief.
- Scores are 1-10 judgment, not data. Never invent statistics; label any figure as an estimate unless it was measured or supplied.
- Do not quote the real people involved at length; short snippets only.
- If the content makes income, job-guarantee, medical or legal claims, flag them as major or blocker.
- You can disagree with the other panelists. Do not move toward the group out of politeness."""

REAL_PERSON = """This persona is a simulation of a real person's public style. Everything you write is a simulated
opinion based on public content, not the real person's view. Never invent quotes or attribute statements to them."""


def member_system(member: dict, card: str) -> str:
    parts = [BASE_RULES, f"\nYOU ARE: {member['name']} (id: {member['id']}).\nYour lens: {' '.join(str(member.get('lens', '')).split())}",
             f"\nPERSONA CARD:\n{card}"]
    if member.get("real_person"):
        parts.append("\n" + REAL_PERSON)
    return "\n".join(parts)


def numbered(text: str) -> str:
    return "\n".join(f"L{i:03d}: {ln}" for i, ln in enumerate(text.splitlines(), 1))


def materials(inputs: dict) -> str:
    out = [f"PROJECT: {inputs['project']}", f"FORMAT: {inputs['format']}", f"GOAL: {inputs['goal']}"]
    if inputs.get("audience"):
        out.append(f"TARGET AUDIENCE: {inputs['audience']}")
    if inputs.get("brief"):
        out.append(f"BRIEF / STRATEGY:\n{inputs['brief']}")
    if inputs.get("assumptions"):
        out.append("ASSUMPTIONS MADE: " + " ".join(inputs["assumptions"]))
    if inputs["titles"]:
        out.append("TITLES:\n" + "\n".join(f"  {t['label']}: {t['text']}  ({len(t['text'])} chars)" for t in inputs["titles"]))
    for th in inputs["thumbnails"]:
        m = th["metrics"]
        out.append(
            f"THUMBNAIL {th['label']}: on-image text = \"{th.get('text') or '(not supplied; read it from the image)'}\"\n"
            f"  Images attached: full size and 120px feed-size preview. Pixel facts (measured): "
            f"{m['source_size'][0]}x{m['source_size'][1]}, contrast_std={m['contrast_std']}, mean_luma={m['mean_luma']}, "
            f"dominant={m['dominant_hex']}, at 120px: contrast_std={m['contrast_std_120']}, edge_density={m['edge_density_120']}."
        )
    if inputs["script"]:
        out.append("SCRIPT (line-numbered):\n" + numbered(inputs["script"]["text"]))
    return "\n\n".join(out)


def rubric_text(rubric: dict, assets: list[str]) -> str:
    return "\n".join(f"{a.upper()} dimensions (score each 1-10, plus overall):\n" +
                     "\n".join(f"  - {k}: {v}" for k, v in rubric[a].items()) for a in assets)


def images_for(inputs: dict) -> list[str]:
    imgs = []
    for th in inputs["thumbnails"]:
        imgs += [th["previews"]["1280"], th["previews"]["120"]]
    return imgs


def phase1(member: dict, card: str, inputs: dict, rubric: dict) -> tuple[str, str]:
    variants = ""
    if len(inputs["titles"]) > 1 or len(inputs["thumbnails"]) > 1:
        variants = ("\nThere are variants. Fill `variant_ranking` (asset -> labels best-first) and "
                    "`ranking_reason` explaining why.")
    user = (f"{materials(inputs)}\n\nRUBRIC:\n{rubric_text(rubric, inputs['assets'])}\n\n"
            f"Review each asset present ({', '.join(inputs['assets'])}) independently from your own point of view. "
            f"Give one AssetReview per asset, including a `rewrite` of your own.{variants}")
    return member_system(member, card), user


def _compact(report: MemberReport) -> str:
    d = report.model_dump()
    return json.dumps(d, indent=1)


def phase2(member: dict, card: str, inputs: dict, own: MemberReport, others: dict[str, MemberReport],
           names: dict[str, str]) -> tuple[str, str]:
    blocks = "\n\n".join(f"=== REPORT OF {names[mid]} (id: {mid}) ===\n{_compact(r)}" for mid, r in others.items())
    user = (f"{materials(inputs)}\n\nYOUR OWN PHASE-1 REPORT:\n{_compact(own)}\n\n"
            f"OTHER PANELISTS' PHASE-1 REPORTS:\n{blocks}\n\n"
            "ROUND 1: CROSS-CRITIQUE. You must: (a) challenge at least 2 specific points from others, quoting the claim "
            "text exactly in `quoted_point` and giving `target_member` as their id; (b) endorse at least 1 point you "
            "initially missed, quoting it; (c) put in `flags` any point you think is wrong and say why. "
            "You are critiquing independently: you cannot see anyone else's critique.")
    return member_system(member, card), user


def phase3(member: dict, card: str, inputs: dict, own: MemberReport, aimed: list[dict]) -> tuple[str, str]:
    items = "\n".join(
        f"- from {a['from']} ({a['kind']}): quoted \"{a['quoted_point']}\" -> {a['comment']}" for a in aimed
    ) or "(no critique was aimed at you)"
    user = (f"{materials(inputs)}\n\nYOUR PHASE-1 REPORT:\n{_compact(own)}\n\nCRITIQUES AIMED AT YOU:\n{items}\n\n"
            "ROUND 2: REBUTTAL. Respond to each critic in `responses` (defend, concede, or modify, with reasoning). "
            "You may change a score only with a stated reason; list every change in `score_changes` as "
            "(asset, dimension, before, after, because). `dimension` is a rubric key or \"overall\". "
            "Do not change scores just to move toward the group. If nothing persuaded you, change nothing.")
    return member_system(member, card), user


JUDGE_SYSTEM = """You are the Judge of a content red-team panel. You do NOT score the content. You moderate,
resolve disputes with reasons (never by averaging scores), and issue the verdict.
Rules:
- Verdict per asset: ship | fix then ship | rework.
- Merge and deduplicate keep/fix points; tag each with the members who agreed and disagreed.
- For every unresolved dispute, state the positions, your ruling and the reasoning.
- Rank fixes by impact (1-5) and effort (1-5).
- Rewrites: 3 title options; 2-3 thumbnail concepts (text, visual direction, emotion, colours, what to remove);
  an improved script hook for the first 20 seconds; sections to cut/tighten/add; for long videos the 2 best Shorts moments.
- Confidence note: what is opinion vs evidence, and what to A/B test. Label metrics as estimates unless a tool supplied them.
- Flag any income / job-guarantee / medical / legal claims.
- Any output derived from a simulated real person must be described as simulated opinion, not the real person's view.
- Do not fabricate quotes."""


def judge(inputs: dict, rubric: dict, reports: dict, critiques: dict, rebuttals: dict, names: dict[str, str],
          suspicious: bool, score_changes: list[dict]) -> tuple[str, str]:
    def dump(d: dict) -> str:
        return "\n\n".join(f"=== {names[k]} (id: {k}) ===\n{json.dumps(v.model_dump(), indent=1)}" for k, v in d.items())
    sus = ""
    if suspicious:
        sus = ("\nWARNING: the panel agreed suspiciously closely. Open `devils_advocate` with the strongest case "
               "AGAINST the consensus before ruling.")
    user = (f"{materials(inputs)}\n\nPHASE 1 REPORTS:\n{dump(reports)}\n\nROUND 1 CRITIQUES:\n{dump(critiques)}\n\n"
            f"ROUND 2 REBUTTALS:\n{dump(rebuttals)}\n\nSCORE CHANGES (member, asset, dim, before, after, because):\n"
            f"{json.dumps(score_changes, indent=1)}\n{sus}\nIssue the Verdict.")
    return JUDGE_SYSTEM, user


def flatten_review(r: AssetReview) -> str:
    return " ".join(p.claim + " " + p.evidence for p in r.keep + r.fix)


def critique_text(c: Critique) -> str:
    return json.dumps(c.model_dump())


def rebuttal_text(r: Rebuttal) -> str:
    return json.dumps(r.model_dump())


__all__: list[Any] = []
