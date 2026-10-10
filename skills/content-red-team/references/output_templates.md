# Output templates

All files go to `./red-team-output/<project-slug>/<YYYYMMDD_HHMM>/`. The runner writes them; in Mode B/C use `run_panel.py assemble` so the format is identical.

```
00_inputs_summary.md
01_independent/<member>.json + .md
02_critique/<member>.md   (+ .json)
03_rebuttal/<member>.md   (+ .json)
debate_transcript.md
scorecard.md
verdict.md
rewrites.md
run_meta.json             (mode, model, timings, warnings)
```

## Chat reply (max ~250 words)

```
Mode: A (LangGraph, 6 parallel members, model X) [or B / C, isolation simulated]
Verdicts: title: fix then ship | thumbnail: rework | script: fix then ship
Top 3 fixes:
1. ...
2. ...
3. ...
Biggest disagreement: <topic> - <member> vs <member>; judge ruled <...>
Files: red-team-output/<slug>/<stamp>/ (verdict.md, rewrites.md, scorecard.md, debate_transcript.md)
```

Never paste the transcript into chat. Mention that scores are judgment, and that any figure is an estimate unless a named tool supplied it.
