import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SKILL = SCRIPTS.parent
SAMPLE = SKILL / "examples" / "sample_input"
sys.path.insert(0, str(SCRIPTS))

import run_panel  # noqa: E402


def run_args(tmp: Path, extra: list[str] | None = None, **over) -> list[str]:
    args = [
        "run", "--dry-run", "--mock-delay", "0.15", "--out-root", str(tmp / "out"), "--cache-dir", str(tmp / "cache"),
        "--project", over.get("project", "PM interview prep"),
        "--title", str(SAMPLE / "title.txt"), "--thumbnail", str(SAMPLE / "thumbnail.png"),
        "--thumb-text", "STOP MEMORISING", "--script", str(SAMPLE / "script.md"), "--brief", str(SAMPLE / "brief.md"),
        "--format", "long", "--audience", "aspiring product managers",
    ]
    return args + (extra or [])


class Result:
    def __init__(self, code: int, out: Path):
        self.code, self.out = code, out
        self.prompts = [json.loads(x) for x in (out / "prompts.jsonl").read_text().splitlines()] if (out / "prompts.jsonl").exists() else []

    def by_phase(self, phase: str):
        return [p for p in self.prompts if p["phase"] == phase]


def run(tmp: Path, extra=None, capsys=None, **over) -> Result:
    code = run_panel.main(run_args(tmp, extra, **over))
    dirs = sorted((tmp / "out").glob("*/*")) if (tmp / "out").exists() else []
    return Result(code, dirs[-1] if dirs else tmp)


@pytest.fixture(scope="session")
def sample_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sample")
    return run(tmp)
