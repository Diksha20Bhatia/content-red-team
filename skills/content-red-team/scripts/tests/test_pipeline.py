import json
import re
import shutil

import pytest
import yaml
from conftest import SKILL, run
from crt import validate
from crt.models import MemberReport, Rebuttal, ScoreChange

FILES = ["00_inputs_summary.md", "debate_transcript.md", "scorecard.md", "verdict.md", "rewrites.md"]


def test_runs_and_all_output_files_exist(sample_run, capsys):
    assert sample_run.code == 0
    out = sample_run.out
    for f in FILES:
        assert (out / f).exists(), f
    for d in ("01_independent", "02_critique", "03_rebuttal"):
        assert len(list((out / d).glob("*.md"))) == 6
    assert len(list((out / "01_independent").glob("*.json"))) == 6


def test_chat_summary_short_and_honest(tmp_path, capsys):
    r = run(tmp_path)
    text = capsys.readouterr().out
    assert r.code == 0
    assert len(text.split()) < 250
    assert "Mode A" in text and "DRY-RUN" in text
    assert "simulated opinion" in text.lower()
    assert "Biggest disagreement" in text


def test_phase1_isolation(sample_run):
    p1 = sample_run.by_phase("phase1")
    assert len(p1) == 6
    cfg = yaml.safe_load((SKILL / "config" / "panel.yaml").read_text())
    for p in p1:
        text = p["system"] + p["user"]
        assert "[[OUT:" not in text, "phase 1 prompt contains another member's output"
        others = [m["name"] for m in cfg["members"] if m["id"] != p["member"]]
        for name in others:
            assert name not in text, f"{p['member']} prompt mentions {name}"


def test_debate_isolation(sample_run):
    ids = {p["member"] for p in sample_run.by_phase("phase1")}
    for p in sample_run.by_phase("critique"):
        t = p["user"]
        assert "[[OUT:p2:" not in t and "[[OUT:p3:" not in t, "critique prompt sees another critique"
        for o in ids - {p["member"]}:
            assert f"[[OUT:p1:{o}]]" in t
    for p in sample_run.by_phase("rebuttal"):
        t = p["user"]
        assert "[[OUT:p3:" not in t
        for o in ids - {p["member"]}:
            assert f"[[OUT:p1:{o}]]" not in t, "rebuttal prompt leaked another member's phase-1 report"
        assert f"[[OUT:p2:{p['member']}]]" not in t, "rebuttal contains own critique"


def test_each_phase_is_parallel(sample_run):
    for phase in ("phase1", "critique", "rebuttal"):
        rec = sample_run.by_phase(phase)
        assert len(rec) == 6
        assert max(r["start"] for r in rec) < min(r["end"] for r in rec), f"{phase} calls were not concurrent"


def test_real_disagreement_and_rulings(sample_run):
    reports = {p.stem: MemberReport.model_validate_json(p.read_text()) for p in (sample_run.out / "01_independent").glob("*.json")}
    assert len(validate.count_disagreements(reports)) >= 3
    verdict = (sample_run.out / ".checkpoints" / "judge" / "judge.json").read_text()
    disputes = json.loads(verdict)["disputes"]
    assert len(disputes) >= 3 and all(d["ruling"].strip() and d["reasoning"].strip() for d in disputes)
    assert "Ruling" in (sample_run.out / "verdict.md").read_text()


def test_every_score_change_has_reason(sample_run):
    n = 0
    for p in (sample_run.out / "03_rebuttal").glob("*.json"):
        for ch in json.loads(p.read_text())["score_changes"]:
            n += 1
            assert len(ch["because"]) >= validate.MIN_REASON_CHARS
    assert n >= 1, "fixture should exercise at least one score change"


def test_unexplained_score_change_fails_validation():
    from crt.models import AssetReview
    own = MemberReport(reviews=[AssetReview(asset="title", scores={"clarity": 6}, overall=6)])
    bad = Rebuttal(responses=[], score_changes=[ScoreChange(asset="title", dimension="clarity", before=6, after=4, because="")])
    assert validate.validate_rebuttal(bad, own)
    wrong_before = Rebuttal(responses=[], score_changes=[ScoreChange(asset="title", dimension="clarity", before=9, after=4, because="a perfectly good reason here")])
    assert validate.validate_rebuttal(wrong_before, own)
    ok = Rebuttal(responses=[], score_changes=[ScoreChange(asset="title", dimension="clarity", before=6, after=4, because="a perfectly good reason here")])
    assert not validate.validate_rebuttal(ok, own)


def test_run_aborts_when_llm_keeps_returning_unexplained_changes(tmp_path, monkeypatch):
    import crt.mock as mock
    orig = mock.rebuttal

    def bad(c):
        r = orig(c)
        rv = c.context["own"].reviews[0]
        d = next(iter(rv.scores))
        return Rebuttal(responses=r.responses, score_changes=[ScoreChange(asset=rv.asset, dimension=d, before=rv.scores[d], after=max(1, rv.scores[d] - 1) or 2, because="")])

    monkeypatch.setattr(mock, "rebuttal", bad)
    r = run(tmp_path)
    assert r.code == 3
    assert not (r.out / "verdict.md").exists()


def test_thumbnail_vision_evidence(sample_run):
    for p in sample_run.by_phase("phase1"):
        assert "A_120.png" in p["images"] and "A_1280.png" in p["images"], "thumbnail images not attached"
    for f in (sample_run.out / "01_independent").glob("*.json"):
        rep = MemberReport.model_validate_json(f.read_text())
        th = next(r for r in rep.reviews if r.asset == "thumbnail")
        assert any("120px" in x.evidence for x in th.keep + th.fix)


def test_real_person_label(sample_run):
    assert "Simulated opinion based on public content, not the real person's view" in (sample_run.out / "01_independent" / "reference_youtuber.md").read_text()
    assert "(simulated)" in (sample_run.out / "debate_transcript.md").read_text()
    assert "Simulated opinion" not in (sample_run.out / "01_independent" / "stakeholder.md").read_text()


def test_config_swap_and_seventh_member(tmp_path):
    cfg = yaml.safe_load((SKILL / "config" / "panel.yaml").read_text())
    for m in cfg["members"]:
        if m["id"] == "reference_youtuber":
            m.update(channel_urls=["https://www.youtube.com/@someone-else"], handle="someone-else")
        if m["id"] == "domain_gatekeeper":
            m["domain"] = "a senior oncology nurse"
        if m["id"] == "target_viewer":
            m["audience"] = "retired hobby gardeners"
    cfg["members"].append({"id": "skeptical_parent", "name": "Skeptical Parent", "role": "custom", "weight": 0.5,
                           "lens": "Would I let my teenager watch this?", "card": "Background: parent.\nKnown bias: distrusts hype."})
    p = tmp_path / "panel.yaml"
    p.write_text(yaml.safe_dump(cfg))
    r = run(tmp_path, ["--config", str(p)])
    assert r.code == 0
    assert len(list((r.out / "01_independent").glob("*.md"))) == 7
    gk = next(x for x in r.by_phase("phase1") if x["member"] == "domain_gatekeeper")
    assert "senior oncology nurse" in gk["system"]
    sp = next(x for x in r.by_phase("phase1") if x["member"] == "skeptical_parent")
    assert "distrusts hype" in sp["system"]


@pytest.mark.parametrize("n", [2, 11])
def test_member_count_limits(tmp_path, n):
    cfg = yaml.safe_load((SKILL / "config" / "panel.yaml").read_text())
    base = cfg["members"][0]
    cfg["members"] = [{**base, "id": f"m{i}", "name": f"M{i}"} for i in range(n)]
    p = tmp_path / "panel.yaml"
    p.write_text(yaml.safe_dump(cfg))
    assert run(tmp_path, ["--config", str(p)]).code == 2


def test_variants_ranked(tmp_path):
    r = run(tmp_path, ["--title", "A second title option", "--thumbnail", str(SKILL / "examples/sample_input/thumbnail.png")])
    assert r.code == 0
    rep = MemberReport.model_validate_json((r.out / "01_independent" / "stakeholder.json").read_text())
    assert "title" in rep.variant_ranking and "thumbnail" in rep.variant_ranking


def test_resume_uses_checkpoints(sample_run, tmp_path):
    out = tmp_path / "copy"
    shutil.copytree(sample_run.out, out)
    (out / "prompts.jsonl").unlink()
    (out / "verdict.md").unlink()
    code = __import__("run_panel").main(["run", "--dry-run", "--resume", str(out), "--cache-dir", str(tmp_path / "c")])
    assert code == 0 and (out / "verdict.md").exists()
    assert not (out / "prompts.jsonl").exists() or not (out / "prompts.jsonl").read_text().strip()


def test_mode_bc_emit_and_assemble(sample_run, tmp_path):
    import run_panel
    out = tmp_path / "bc"
    shutil.copytree(sample_run.out, out)
    for f in FILES:
        (out / f).unlink()
    assert run_panel.main(["emit", "--dir", str(out), "--phase", "critique"]) == 0
    prompt = (out / "prompts" / "critique" / "stakeholder.md").read_text()
    assert "[[OUT:p2:" not in prompt and "Stakeholder" in prompt
    assert run_panel.main(["assemble", "--dir", str(out), "--mode", "C"]) == 0
    assert "ISOLATION WAS SIMULATED" in (out / "00_inputs_summary.md").read_text()
    assert (out / "verdict.md").exists()
    # tamper: break a checkpoint's reason -> assemble must fail
    f = next((out / ".checkpoints" / "rebuttal").glob("*.json"))
    d = json.loads(f.read_text())
    if d["score_changes"]:
        d["score_changes"][0]["because"] = ""
        f.write_text(json.dumps(d))
        assert run_panel.main(["assemble", "--dir", str(out), "--mode", "B"]) == 3


def test_check_env_reports_mode(monkeypatch):
    import run_panel
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    e = run_panel.env_report()
    assert e["mode_a_possible"] is False and "ANTHROPIC_API_KEY" in e["missing_for_a"]
    assert run_panel.main(["run", "--title", "x", "--script", "y", "--format", "long"]) == 5


def test_no_key_in_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-SHOULD-NOT-APPEAR")
    r = run(tmp_path)
    for f in r.out.rglob("*"):
        if f.is_file() and f.suffix in {".md", ".json", ".jsonl"}:
            assert "SECRET-SHOULD-NOT-APPEAR" not in f.read_text()


def test_skill_md_contract():
    text = (SKILL / "SKILL.md").read_text()
    fm = yaml.safe_load(text.split("---")[1])
    assert fm["name"] == "content-red-team" == SKILL.name
    assert 0 < len(fm["description"]) < 1024
    assert len(text.splitlines()) < 500
    for kw in ("review", "critique", "red-team", "stress-test", "what do you think"):
        assert kw in fm["description"].lower()
    for ref in re.findall(r"references/[a-z_]+\.md", text):
        assert (SKILL / ref).exists(), ref
