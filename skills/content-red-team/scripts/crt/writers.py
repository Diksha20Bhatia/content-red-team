"""Write the output tree and the short chat summary."""
from __future__ import annotations

import json
from pathlib import Path

from . import validate
from .models import AssetReview, Critique, MemberReport, Rebuttal, Verdict

SIM = "> Simulated opinion based on public content, not the real person's view."
ESTIMATE = "_Scores are judgment (1-10), not data. Any figure is an estimate unless a named tool supplied it._"


def _w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def _banner(member: dict) -> str:
    return SIM + "\n\n" if member.get("real_person") else ""


def _label(member: dict) -> str:
    return member["name"] + (" (simulated)" if member.get("real_person") else "")


def _review_md(r: AssetReview) -> str:
    sc = ", ".join(f"{k}={v}" for k, v in r.scores.items())
    pts = lambda ps: "\n".join(f"- **[{p.severity}]** {p.claim}  \n  _evidence:_ {p.evidence}" for p in ps) or "- (none)"  # noqa: E731
    return (f"### {r.asset.title()} - overall {r.overall}/10 (confidence: {r.confidence})\nScores: {sc}\n\n"
            f"**Keep**\n{pts(r.keep)}\n\n**Fix**\n{pts(r.fix)}\n\n**Risks**\n" +
            ("\n".join(f"- {x}" for x in r.risks) or "- (none)") + f"\n\n**Own rewrite:** {r.rewrite or '(none)'}\n")


def report_md(member: dict, rep: MemberReport) -> str:
    out = f"# {_label(member)} - independent review\n\n{_banner(member)}{rep.summary}\n\n"
    out += "\n".join(_review_md(r) for r in rep.reviews)
    if rep.variant_ranking:
        out += "\n### Variant ranking\n" + "\n".join(f"- {a}: {' > '.join(v)}" for a, v in rep.variant_ranking.items())
        out += f"\n\n{rep.ranking_reason}\n"
    return out


def critique_md(member: dict, c: Critique, names: dict) -> str:
    f = lambda items, h: f"## {h}\n" + ("\n".join(f"- To **{names.get(q.target_member, q.target_member)}**, on \"{q.quoted_point}\": {q.comment}" for q in items) or "- (none)") + "\n"  # noqa: E731
    return (f"# {_label(member)} - round 1 cross-critique\n\n{_banner(member)}" + f(c.challenges, "Challenges") +
            "\n" + f(c.endorsements, "Endorsements") + "\n" + f(c.flags, "Flags (points believed wrong)"))


def rebuttal_md(member: dict, r: Rebuttal, names: dict) -> str:
    out = f"# {_label(member)} - round 2 rebuttal\n\n{_banner(member)}## Responses\n"
    out += "\n".join(f"- To **{names.get(x.to_member, x.to_member)}**: **{x.stance}** - {x.reasoning}" for x in r.responses)
    out += "\n\n## Score changes\n"
    out += "\n".join(f"- {c.asset}/{c.dimension}: {c.before} -> {c.after} because {c.because}" for c in r.score_changes) or "- (none)"
    return out


def inputs_md(inputs: dict, meta: dict, cfg: dict) -> str:
    out = [f"# Inputs summary: {inputs['project']}", "",
           f"- Mode: **{meta['mode']}** ({meta['mode_note']})", f"- Model: {meta['model']}",
           f"- Format: {inputs['format']} | Goal: {inputs['goal']} | Audience: {inputs.get('audience') or '(default per panel.yaml)'}",
           f"- Assets reviewed: {', '.join(inputs['assets'])}", f"- Panel: {', '.join(m['name'] for m in cfg['members'])} + Judge",
           f"- Panel config: {cfg['_path']}", ""]
    out += ["## Titles"] + [f"- {t['label']}: {t['text']} ({len(t['text'])} chars)" for t in inputs["titles"]]
    out += ["", "## Thumbnails"] + [f"- {t['label']}: text \"{t.get('text', '')}\" | {t['path']} | previews {', '.join(t['previews'])}px"
                                    for t in inputs["thumbnails"]]
    if inputs["script"]:
        out += ["", f"## Script: {inputs['script']['words']} words ({inputs['script'].get('path') or 'pasted'})"]
    if inputs.get("brief"):
        out += ["", "## Brief", inputs["brief"]]
    out += ["", "## Assumptions"] + [f"- {a}" for a in inputs["assumptions"]] if inputs["assumptions"] else []
    if meta.get("warnings"):
        out += ["", "## Warnings"] + [f"- {w}" for w in meta["warnings"]]
    return "\n".join(out)


def transcript_md(d: dict) -> str:
    names, members = d["names"], {m["id"]: m for m in d["cfg"]["members"]}
    L = lambda mid: _label(members[mid])  # noqa: E731
    out = [f"# Debate transcript: {d['inputs']['project']}", "", ESTIMATE, ""]
    if any(m.get("real_person") for m in members.values()):
        out += [SIM, ""]
    out += ["## Phase 1: independent analysis (parallel, isolated)", ""]
    for mid, r in d["reports"].items():
        out.append(f"### {L(mid)}\n{r.summary}")
        for rv in r.reviews:
            out.append(f"- **{rv.asset}** overall {rv.overall}/10. Fix: " + ("; ".join(p.claim for p in rv.fix) or "none") +
                       ". Keep: " + ("; ".join(p.claim for p in rv.keep) or "none"))
        out.append("")
    out += ["## Round 1: cross-critique", ""]
    for mid, c in d["critiques"].items():
        for q in c.challenges:
            out.append(f"- **{L(mid)}** challenges **{names[q.target_member]}** on \"{q.quoted_point}\": {q.comment}")
        for q in c.endorsements:
            out.append(f"- **{L(mid)}** endorses **{names[q.target_member]}** on \"{q.quoted_point}\": {q.comment}")
        for q in c.flags:
            out.append(f"- **{L(mid)}** flags **{names[q.target_member]}** on \"{q.quoted_point}\": {q.comment}")
    out += ["", "## Round 2: rebuttal", ""]
    for mid, r in d["rebuttals"].items():
        for x in r.responses:
            out.append(f"- **{L(mid)}** {x.stance}s to **{names.get(x.to_member, x.to_member)}**: {x.reasoning}")
        for ch in r.score_changes:
            out.append(f"  - score change {ch.asset}/{ch.dimension} {ch.before}->{ch.after}: {ch.because}")
    v: Verdict = d["verdict"]
    out += ["", "## Judge", ""]
    if v.devils_advocate:
        out += [f"**Devil's advocate (panel was suspiciously unanimous):** {v.devils_advocate}", ""]
    for x in v.disputes:
        out.append(f"- **Dispute: {x.topic}** ({'; '.join(f'{k}: {p}' for k, p in x.positions.items())}). **Ruling:** {x.ruling} _{x.reasoning}_")
    return "\n".join(out)


def scorecard_md(d: dict) -> str:
    finals = validate.final_scores(d["reports"], d["rebuttals"])
    toward, total = validate.drift_ratio(d["reports"], d["rebuttals"])
    out = [f"# Scorecard: {d['inputs']['project']}", "", ESTIMATE, "",
           "| Member | Asset | Dimension | Before debate | After debate | Change |", "|---|---|---|---|---|---|"]
    mem = {m["id"]: m for m in d["cfg"]["members"]}
    for mid, rep in d["reports"].items():
        for rv in rep.reviews:
            rows = [*rv.scores.items(), ("overall", rv.overall)]
            for dim, before in rows:
                after = finals[mid][rv.asset][dim]
                out.append(f"| {_label(mem[mid])} | {rv.asset} | {dim} | {before} | {after} | {'' if after == before else f'{after - before:+d}'} |")
    out += ["", "## Panel means (overall, before -> after; unweighted, judgment not data)", "", "| Asset | Before | After |", "|---|---|---|"]
    for a in d["inputs"]["assets"]:
        b = [rv.overall for r in d["reports"].values() for rv in r.reviews if rv.asset == a]
        f = [finals[mid][a]["overall"] for mid in finals if a in finals[mid]]
        out.append(f"| {a} | {sum(b) / len(b):.1f} | {sum(f) / len(f):.1f} |")
    out += ["", "## Score discipline", f"- {total} score change(s), all with stated reasons (runs without reasons fail validation).",
            f"- {toward} of {total} moved toward the group mean" + (" (watch for drift: read the reasons)" if total and toward / total > 0.8 else "") + ".",
            "", "## Changes with reasons"]
    out += [f"- {d['names'][mid]}: {c.asset}/{c.dimension} {c.before}->{c.after}: {c.because}"
            for mid, r in d["rebuttals"].items() for c in r.score_changes] or ["- (none)"]
    return "\n".join(out)


def verdict_md(d: dict) -> str:
    v: Verdict = d["verdict"]
    pt = lambda p: f"- **[{p.severity}] {p.asset}**: {p.claim}  \n  _evidence:_ {p.evidence}  \n  _agreed:_ {', '.join(p.agreed_by) or '-'} | _disagreed:_ {', '.join(p.disagreed_by) or '-'}"  # noqa: E731
    out = [f"# Verdict: {d['inputs']['project']}", "", ESTIMATE, ""]
    if v.devils_advocate:
        out += ["## Devil's advocate (panel agreed suspiciously closely)", v.devils_advocate, ""]
    out += ["## Verdict per asset"] + [f"- **{a.asset}: {a.verdict.upper()}** - {a.reason}" for a in v.asset_verdicts]
    out += ["", "## What is right (keep)"] + ([pt(p) for p in v.keep] or ["- (none)"])
    out += ["", "## What is wrong (fix)"] + ([pt(p) for p in v.fix] or ["- (none)"])
    out += ["", "## Unresolved disputes and rulings"]
    for x in v.disputes:
        out += [f"### {x.topic}"] + [f"- {k}: {p}" for k, p in x.positions.items()] + [f"- **Ruling:** {x.ruling}", f"- _Why:_ {x.reasoning}", ""]
    out += ["## Ranked fix list (impact 5 = highest; effort 1 = easiest)", "", "| # | Fix | Asset | Impact | Effort |", "|---|---|---|---|---|"]
    out += [f"| {i} | {f.fix} | {f.asset} | {f.impact} | {f.effort} |"
            for i, f in enumerate(sorted(v.ranked_fixes, key=lambda f: (-f.impact, f.effort)), 1)]
    out += ["", "## Confidence", v.confidence_note, "", "**A/B test:** " + (", ".join(v.ab_tests) or "(none)")]
    return "\n".join(out)


def rewrites_md(d: dict) -> str:
    r = d["verdict"].rewrites
    out = [f"# Rewrites: {d['inputs']['project']}", "", "## Title options"] + [f"{i}. {t}  ({len(t)} chars)" for i, t in enumerate(r.titles, 1)]
    out += ["", "## Thumbnail concepts"]
    for i, t in enumerate(r.thumbnails, 1):
        out += [f"### Concept {i}", f"- Text on thumbnail: {t.text}", f"- Visual direction: {t.visual}", f"- Emotion: {t.emotion}",
                f"- Colours: {t.colours}", f"- Remove: {t.remove}", ""]
    out += ["## Script hook (first 20 seconds)", r.script_hook, "", "## Script edits"]
    out += [f"- **{e.action.upper()}** {e.section}: {e.note}" for e in r.script_edits] or ["- (none)"]
    if r.shorts:
        out += ["", "## Best 2 moments to cut as Shorts"] + [f"- {s.moment} - {s.why}" for s in r.shorts]
    return "\n".join(out)


def write_all(d: dict, out: Path) -> list[Path]:
    members = {m["id"]: m for m in d["cfg"]["members"]}
    _w(out / "00_inputs_summary.md", inputs_md(d["inputs"], d["meta"], d["cfg"]))
    for mid, rep in d["reports"].items():
        _w(out / "01_independent" / f"{mid}.json", rep.model_dump_json(indent=2))
        _w(out / "01_independent" / f"{mid}.md", report_md(members[mid], rep))
    for mid, c in d["critiques"].items():
        _w(out / "02_critique" / f"{mid}.md", critique_md(members[mid], c, d["names"]))
        _w(out / "02_critique" / f"{mid}.json", c.model_dump_json(indent=2))
    for mid, r in d["rebuttals"].items():
        _w(out / "03_rebuttal" / f"{mid}.md", rebuttal_md(members[mid], r, d["names"]))
        _w(out / "03_rebuttal" / f"{mid}.json", r.model_dump_json(indent=2))
    _w(out / "debate_transcript.md", transcript_md(d))
    _w(out / "scorecard.md", scorecard_md(d))
    _w(out / "verdict.md", verdict_md(d))
    _w(out / "rewrites.md", rewrites_md(d))
    _w(out / "run_meta.json", json.dumps(d["meta"], indent=2))
    return sorted(p for p in out.rglob("*") if p.is_file() and ".checkpoints" not in p.parts)


def chat_summary(d: dict, out: Path) -> str:
    v: Verdict = d["verdict"]
    m = d["meta"]
    lines = [f"Mode {m['mode']}: {m['mode_note']}",
             "Verdicts: " + " | ".join(f"{a.asset}: {a.verdict}" for a in v.asset_verdicts),
             "Top 3 fixes:"]
    for i, f in enumerate(sorted(v.ranked_fixes, key=lambda f: (-f.impact, f.effort))[:3], 1):
        lines.append(f"{i}. [{f.asset}] {f.fix[:110]}")
    if v.disputes:
        x = v.disputes[0]
        who = list(x.positions)
        lines.append(f"Biggest disagreement: {x.topic} ({who[0]} vs {who[-1]}); ruling: {x.ruling[:120]}")
    if v.devils_advocate:
        lines.append("Note: panel agreed suspiciously closely; judge played devil's advocate.")
    if any(mm.get("real_person") for mm in d["cfg"]["members"]):
        lines.append("Reference-creator output is a simulated opinion based on public content, not the real person's view.")
    lines.append("Scores are judgment, not data.")
    lines.append(f"Files: {out}/ (verdict.md, rewrites.md, scorecard.md, debate_transcript.md)")
    return "\n".join(lines)
