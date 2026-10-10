#!/usr/bin/env python3
"""content-red-team runner.

  run_panel.py check-env                       which execution mode is possible (JSON)
  run_panel.py run  [intake flags] [--dry-run] Mode A: LangGraph, parallel + isolated + debate
  run_panel.py prepare [intake flags]          Mode B/C: create output dir + inputs.json
  run_panel.py emit --dir D --phase P          Mode B/C: write one isolated prompt file per member
  run_panel.py assemble --dir D --mode B|C     Mode B/C: validate checkpoints, write all outputs
  run_panel.py schema --phase P                print the JSON schema a phase must return

Exit codes: 0 ok, 2 bad input, 3 validation failed / needs input, 5 Mode A unavailable.
The API key is read from ANTHROPIC_API_KEY only. The model comes from LLM_MODEL or panel.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Annotated, Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intake  # noqa: E402
from crt import validate, writers  # noqa: E402
from crt.config import load_panel, load_rubric  # noqa: E402
from crt.engine import Engine  # noqa: E402
from crt.llm import LoggedLLM  # noqa: E402
from crt.models import Critique, MemberReport, Rebuttal, ValidationProblem, Verdict  # noqa: E402

SCHEMAS = {"phase1": MemberReport, "critique": Critique, "rebuttal": Rebuttal, "judge": Verdict}


def merge(a: dict | None, b: dict) -> dict:
    return {**(a or {}), **b}


class State(TypedDict, total=False):
    reports: Annotated[dict, merge]
    critiques: Annotated[dict, merge]
    rebuttals: Annotated[dict, merge]
    verdict: Any


def env_report() -> dict:
    mods = {}
    for m in ("langgraph", "anthropic", "pydantic", "yaml", "PIL"):
        try:
            __import__(m)
            mods[m] = True
        except ImportError:
            mods[m] = False
    py_ok = sys.version_info >= (3, 11)
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    a_ok = py_ok and key and mods["langgraph"] and mods["anthropic"] and mods["pydantic"]
    core_ok = py_ok and mods["pydantic"] and mods["yaml"] and mods["PIL"]
    return {
        "python": ".".join(map(str, sys.version_info[:3])), "python_ok": py_ok, "api_key_set": key, "modules": mods,
        "mode_a_possible": a_ok,
        "mode_b_c_helpers_possible": core_ok,
        "recommendation": "A" if a_ok else ("B (subagents, if the session supports them) else C, using emit/assemble helpers" if core_ok
                                            else "B or C without helpers: follow references/output_templates.md by hand"),
        "missing_for_a": [x for x, ok in (("python>=3.11", py_ok), ("ANTHROPIC_API_KEY", key), ("langgraph", mods["langgraph"]),
                                          ("anthropic", mods["anthropic"])) if not ok],
    }


# ---------------------------------------------------------------- Mode A graph
def build_graph(eng: Engine):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    ids = [m["id"] for m in eng.members]

    def analyze(p: dict) -> dict:
        return {"reports": {p["mid"]: eng.execute(eng.build_phase1(p["mid"]))}}

    def critique(p: dict) -> dict:
        return {"critiques": {p["mid"]: eng.execute(eng.build_critique(p["mid"], p["reports"]))}}

    def rebut(p: dict) -> dict:
        return {"rebuttals": {p["mid"]: eng.execute(eng.build_rebuttal(p["mid"], p["reports"], p["critiques"]))}}

    def judge(s: State) -> dict:
        return {"verdict": eng.execute(eng.build_judge(s["reports"], s["critiques"], s["rebuttals"]))}

    g = StateGraph(State)
    g.add_node("start", lambda s: {})
    g.add_node("analyze", analyze)
    g.add_node("after_p1", lambda s: {})
    g.add_node("critique", critique)
    g.add_node("after_p2", lambda s: {})
    g.add_node("rebut", rebut)
    g.add_node("judge", judge)
    g.add_edge(START, "start")
    g.add_conditional_edges("start", lambda s: [Send("analyze", {"mid": i}) for i in ids], ["analyze"])
    g.add_edge("analyze", "after_p1")
    g.add_conditional_edges("after_p1", lambda s: [Send("critique", {"mid": i, "reports": s["reports"]}) for i in ids], ["critique"])
    g.add_edge("critique", "after_p2")
    g.add_conditional_edges("after_p2", lambda s: [Send("rebut", {"mid": i, "reports": s["reports"], "critiques": s["critiques"]}) for i in ids], ["rebut"])
    g.add_edge("rebut", "judge")
    g.add_edge("judge", END)
    return g.compile()


def load_inputs_or_intake(a: argparse.Namespace) -> tuple[dict, Path]:
    if getattr(a, "resume", None):
        out = Path(a.resume)
        return json.loads((out / "inputs.json").read_text()), out
    stamp = time.strftime("%Y%m%d_%H%M")
    out = Path(a.out_root) / intake.slugify(a.project) / stamp
    out.mkdir(parents=True, exist_ok=True)
    a.out = str(out)
    inputs = intake.build(a)
    inputs["created"] = stamp
    if inputs["missing_essential"]:
        print(f"NEEDS INPUT: {', '.join(inputs['missing_essential'])}. Ask the user one short question.", file=sys.stderr)
        raise SystemExit(3)
    (out / "inputs.json").write_text(json.dumps(inputs, indent=2))
    return inputs, out


def finish(eng: Engine, inputs: dict, out: Path, reports, critiques, rebuttals, verdict, meta: dict) -> int:
    toward, total = validate.drift_ratio(reports, rebuttals)
    if total and toward / total > 0.8 and total >= 3:
        meta.setdefault("warnings", []).append(f"{toward}/{total} score changes moved toward the group mean: check for drift.")
    if len(validate.count_disagreements(reports)) < 1 and not verdict.devils_advocate:
        meta.setdefault("warnings", []).append("No opposing views detected between members.")
    d = {"inputs": inputs, "cfg": eng.cfg, "names": eng.names, "reports": reports, "critiques": critiques,
         "rebuttals": rebuttals, "verdict": verdict, "meta": meta}
    writers.write_all(d, out)
    print(writers.chat_summary(d, out))
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    env = env_report()
    if not a.dry_run and not env["mode_a_possible"]:
        print("Mode A unavailable. Missing: " + ", ".join(env["missing_for_a"]) +
              "\nUse Mode B (subagents) or C (sequential) via prepare/emit/assemble, see SKILL.md.", file=sys.stderr)
        return 5
    if a.dry_run:
        try:
            import langgraph  # noqa: F401
        except ImportError:
            print("--dry-run needs langgraph installed (pip install -r requirements.txt)", file=sys.stderr)
            return 5
    inputs, out = load_inputs_or_intake(a)
    cfg = load_panel(a.config)
    rubric = load_rubric()
    if a.dry_run:
        from crt.mock import MockLLM
        inner: Any = MockLLM(delay=a.mock_delay)
        note = "DRY-RUN with a mocked LLM: output is templated to exercise the pipeline, it is not a real review"
        model = "mock"
    else:
        from crt.llm import AnthropicLLM
        inner = AnthropicLLM(cfg["model"], cfg["max_tokens"])
        model = cfg["model"]
        note = f"LangGraph runner, {len(cfg['members'])} members run in parallel with isolated calls each phase; vision enabled for thumbnails"
    llm = LoggedLLM(inner, out / "prompts.jsonl")
    eng = Engine(cfg, inputs, rubric, llm, out, Path(a.cache_dir))
    t0 = time.time()
    try:
        state = build_graph(eng).invoke({}, config={"max_concurrency": cfg["max_concurrency"]})
    except ValidationProblem as e:
        print(f"VALIDATION FAILED: {e}\nCheckpoints kept in {out}/.checkpoints; fix and rerun with --resume {out}", file=sys.stderr)
        return 3
    meta = {"mode": "A", "mode_note": note, "model": model, "seconds": round(time.time() - t0, 1),
            "max_concurrent_calls": llm.max_active, "calls": len(llm.records), "warnings": []}
    return finish(eng, inputs, out, state["reports"], state["critiques"], state["rebuttals"], state["verdict"], meta)


# ---------------------------------------------------------------- Mode B/C helpers
def cmd_prepare(a: argparse.Namespace) -> int:
    inputs, out = load_inputs_or_intake(a)
    print(json.dumps({"dir": str(out), "assets": inputs["assets"], "assumptions": inputs["assumptions"]}, indent=2))
    return 0


def _engine_for_dir(a: argparse.Namespace) -> tuple[Engine, dict, Path]:
    out = Path(a.dir)
    inputs = json.loads((out / "inputs.json").read_text())
    eng = Engine(load_panel(a.config), inputs, load_rubric(), None, out, Path(a.cache_dir))  # type: ignore[arg-type]
    return eng, inputs, out


def _load_phase(eng: Engine, phase: str, ids: list[str]) -> dict:
    schema = SCHEMAS[phase]
    res = {}
    for mid in ids:
        obj = eng._load(phase, mid, schema)
        if obj is None:
            raise SystemExit(f"missing or invalid checkpoint {eng.ckpt / phase / (mid + '.json')}")
        res[mid] = obj
    return res


def cmd_emit(a: argparse.Namespace) -> int:
    eng, inputs, out = _engine_for_dir(a)
    ids = [m["id"] for m in eng.members]
    reports = _load_phase(eng, "phase1", ids) if a.phase != "phase1" else {}
    critiques = _load_phase(eng, "critique", ids) if a.phase in ("rebuttal", "judge") else {}
    rebuttals = _load_phase(eng, "rebuttal", ids) if a.phase == "judge" else {}
    if a.phase == "phase1":
        specs = {i: eng.build_phase1(i) for i in ids}
    elif a.phase == "critique":
        specs = {i: eng.build_critique(i, reports) for i in ids}
    elif a.phase == "rebuttal":
        specs = {i: eng.build_rebuttal(i, reports, critiques) for i in ids}
    else:
        specs = {"judge": eng.build_judge(reports, critiques, rebuttals)}
    schema_dir = out / "schemas"
    schema_dir.mkdir(exist_ok=True)
    sf = schema_dir / f"{a.phase}.schema.json"
    schema_json = json.dumps(SCHEMAS[a.phase].model_json_schema(), separators=(",", ":"))
    sf.write_text(json.dumps(SCHEMAS[a.phase].model_json_schema(), indent=2))
    written = []
    for mid, s in specs.items():
        imgs = "\n".join(f"- {p}" for p in s["images"]) or "(none)"
        target = eng.ckpt / a.phase / f"{mid}.json"
        body = (f"# TASK FOR PANEL MEMBER `{mid}` - phase `{a.phase}`\n\nYou see ONLY this file and the image files listed. "
                f"Do not read any other file in this directory.\n\nWrite your answer as ONE JSON object that validates against the JSON Schema below "
                f"(use exactly these field names; no extra wrapper keys) to:\n`{target}`\n\n## JSON SCHEMA\n```json\n{schema_json}\n```\n\n"
                f"## IMAGES TO LOOK AT (open and view each one)\n{imgs}\n\n## SYSTEM / PERSONA\n{s['system']}\n\n## TASK\n{s['user']}\n")
        f = out / "prompts" / a.phase / f"{mid}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
        written.append(str(f))
    print(json.dumps({"phase": a.phase, "prompt_files": written, "schema": str(sf)}, indent=2))
    return 0


def cmd_assemble(a: argparse.Namespace) -> int:
    eng, inputs, out = _engine_for_dir(a)
    ids = [m["id"] for m in eng.members]
    try:
        reports = _load_phase(eng, "phase1", ids)
        problems = [f"phase1/{i}: {e}" for i, r in reports.items() for e in validate.validate_report(r, inputs, eng.rubric)]
        critiques = _load_phase(eng, "critique", ids)
        problems += [f"critique/{i}: {e}" for i, c in critiques.items() for e in validate.validate_critique(c, i, reports)]
        rebuttals = _load_phase(eng, "rebuttal", ids)
        problems += [f"rebuttal/{i}: {e}" for i, r in rebuttals.items() for e in validate.validate_rebuttal(r, reports[i])]
        verdict = _load_phase(eng, "judge", ["judge"])["judge"]
        sus = validate.suspicious_consensus(reports, critiques)
        problems += [f"judge: {e}" for e in eng._check_verdict(verdict, sus)]
    except SystemExit as e:
        print(f"ASSEMBLE FAILED: {e}", file=sys.stderr)
        return 3
    if problems:
        print("VALIDATION FAILED:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 3
    note = {"B": "native parallel subagents, one per member; isolation by separate contexts",
            "C": "sequential passes in one session; ISOLATION WAS SIMULATED, not enforced"}[a.mode]
    meta = {"mode": a.mode, "mode_note": note, "model": "session model", "warnings": [] if a.mode == "B" else ["Isolation simulated (Mode C)."]}
    return finish(eng, inputs, out, reports, critiques, rebuttals, verdict, meta)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="panel.yaml (default: ./content-red-team.panel.yaml or bundled)")
    common.add_argument("--cache-dir", default=".cache")
    common.add_argument("--out-root", default="red-team-output")
    sub.add_parser("check-env")
    for name in ("run", "prepare"):
        p = sub.add_parser(name, parents=[common])
        intake.add_args(p)
        p.add_argument("--resume", help="existing output dir to continue (uses its checkpoints)")
        if name == "run":
            p.add_argument("--dry-run", action="store_true", help="mocked LLM; no key or network")
            p.add_argument("--mock-delay", type=float, default=0.05)
    pe = sub.add_parser("emit", parents=[common])
    pe.add_argument("--dir", required=True)
    pe.add_argument("--phase", required=True, choices=list(SCHEMAS))
    pa = sub.add_parser("assemble", parents=[common])
    pa.add_argument("--dir", required=True)
    pa.add_argument("--mode", choices=["B", "C"], required=True)
    ps = sub.add_parser("schema")
    ps.add_argument("--phase", required=True, choices=list(SCHEMAS))
    a = ap.parse_args(argv)
    if a.cmd == "check-env":
        print(json.dumps(env_report(), indent=2))
        return 0
    if a.cmd == "schema":
        print(json.dumps(SCHEMAS[a.phase].model_json_schema(), indent=2))
        return 0
    try:
        return {"run": cmd_run, "prepare": cmd_prepare, "emit": cmd_emit, "assemble": cmd_assemble}[a.cmd](a)
    except ValueError as e:  # config errors
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
