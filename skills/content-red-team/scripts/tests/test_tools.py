import json
import zipfile

import intake
import persona_builder
import pytest
import thumb_preview
from conftest import SAMPLE, SCRIPTS
from PIL import Image


def test_thumb_preview_sizes(tmp_path):
    info = thumb_preview.make_previews(SAMPLE / "thumbnail.png", tmp_path, "A")
    for w in (1280, 360, 120):
        assert Image.open(info["previews"][str(w)]).width == w
    m = info["metrics"]
    assert 0 <= m["edge_density_120"] <= 1 and m["dominant_hex"].startswith("#")


def test_thumb_preview_bad_file(tmp_path):
    bad = tmp_path / "x.png"
    bad.write_text("not an image")
    assert thumb_preview.main([str(bad), "--out", str(tmp_path)]) == 2


def _docx(path, paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def test_intake_formats_and_variants(tmp_path):
    d = tmp_path / "s.docx"
    _docx(d, ["Line one of script", "Line two"])
    code = intake.main(["--project", "My Video!", "--title", "Title A", "--title", "Title B", "--script", str(d),
                        "--thumbnail", str(SAMPLE / "thumbnail.png"), "--format", "short", "--out", str(tmp_path)])
    data = json.loads((tmp_path / "inputs.json").read_text())
    assert code == 0 and data["slug"] == "my-video"
    assert [t["label"] for t in data["titles"]] == ["A", "B"]
    assert "Line two" in data["script"]["text"]
    assert data["assets"] == ["title", "thumbnail", "script"]


def test_intake_title_file_gives_variants(tmp_path):
    intake.main(["--title", str(SAMPLE / "title.txt"), "--script", "pasted script text", "--format", "long", "--out", str(tmp_path)])
    data = json.loads((tmp_path / "inputs.json").read_text())
    assert len(data["titles"]) == 2 and data["script"]["path"] is None


def test_intake_missing_essentials_asks(tmp_path, capsys):
    code = intake.main(["--title", "Only a title", "--out", str(tmp_path)])
    assert code == 3
    assert "NEEDS INPUT" in capsys.readouterr().err


def test_intake_pdf(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    p = tmp_path / "s.pdf"
    with p.open("wb") as f:
        w.write(f)
    text, src = intake.read_any(str(p))
    assert src == str(p) and isinstance(text, str)


def test_persona_builder_no_network_asks_user(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(persona_builder, "fetch_titles", lambda *a, **k: ([], [], []))
    code = persona_builder.main(["--handle", "x", "--channel", "https://youtube.com/@x", "--cache-dir", str(tmp_path)])
    assert code == persona_builder.EXIT_NEEDS_USER
    assert "paste 2-3 transcripts" in capsys.readouterr().err


def test_persona_builder_from_files_and_snippet_cap(tmp_path):
    t = tmp_path / "t1.txt"
    t.write_text("Okay so today we talk about something. " + "word " * 300 + "Why does this work? Let me show you.")
    assert persona_builder.main(["--handle", "h", "--cache-dir", str(tmp_path), "--from-files", str(t)]) == 0
    card = (tmp_path / "personas" / "h.md").read_text()
    assert "Simulated opinion based on public content" in card
    quoted = [q for q in __import__("re").findall(r'"([^"]+)"', card)]
    assert all(len(q.split()) <= persona_builder.MAX_SNIPPET_WORDS + 1 for q in quoted)
    mat = json.loads((tmp_path / "personas" / "h.material.json").read_text())
    assert all(len(x.split()) <= 201 for x in mat["transcripts"])  # no long transcripts stored


def test_persona_builder_from_json_and_cache(tmp_path):
    j = tmp_path / "m.json"
    j.write_text(json.dumps({"titles": ["7 Mistakes to Avoid?", "How I Did It"], "top_titles": ["10 Rules"], "transcripts": ["Hello. Is this on? Yes."]}))
    assert persona_builder.main(["--handle", "j", "--cache-dir", str(tmp_path), "--from-json", str(j)]) == 0
    assert "measured" in (tmp_path / "personas" / "j.md").read_text()
    # fresh cache short-circuits
    assert persona_builder.main(["--handle", "j", "--cache-dir", str(tmp_path)]) == 0


def test_cached_persona_is_used_by_panel(tmp_path):
    from crt.config import load_panel, persona_card
    (tmp_path / "personas").mkdir()
    (tmp_path / "personas" / "reference-creator.md").write_text("CACHED CARD MARKER")
    cfg = load_panel()
    ref = next(m for m in cfg["members"] if m["id"] == "reference_youtuber")
    card, src = persona_card(ref, tmp_path)
    assert "CACHED CARD MARKER" in card and "cache" in src
    assert SCRIPTS.exists()
