---
name: content-red-team
description: Red-teams YouTube titles, thumbnails, scripts and Shorts with a panel of 6 simulated reviewers (reference creator, stakeholder, target viewer, retention analyst, cold scroller, domain gatekeeper) plus a judge. Members review independently, cross-critique, rebut, then the judge rules and gives ship/fix/rework verdicts, disagreements and improved rewrites. Use when the user asks to review, critique, red-team, stress-test, tear apart, or "what do you think of" a YouTube title, thumbnail, script, hook or Short, or wants panel, debate or multi-perspective feedback on video content before publishing.
license: MIT
compatibility: Mode A needs Python 3.11+, ANTHROPIC_API_KEY and `pip install -r scripts/requirements.txt`. Modes B/C need only the agent session (helpers need pydantic, pyyaml, pillow).
metadata:
  version: "1.0.0"
---

# content-red-team

A panel of simulated reviewers stress-tests a title, thumbnail and script, argues about it for two rounds, and a judge rules. Nothing is hardcoded to a creator or niche: members, weights, models and rubric come from `config/` and the user's inputs.

Paths below are relative to this skill's folder (`SKILL_DIR` = the folder containing this SKILL.md; in Claude Code it is `${CLAUDE_SKILL_DIR}`). Run scripts as `python3 SKILL_DIR/scripts/<name>.py`. Output goes to `./red-team-output/<project-slug>/<YYYYMMDD_HHMM>/` in the user's current directory.

## Workflow

### 0. Intake
Collect (from the message, attached files or paths): title(s), thumbnail image(s) + on-image text, script (md/txt/pdf/docx or pasted), optional brief/creator profile/agency plan, reference channel URL, target audience, format (`long`, `short`, `webinar`), goal. Multiple titles/thumbnails are variants A/B/C and are ranked against each other.

- If the **script** or **format** is missing, ask ONE short question. Otherwise proceed and state assumptions.
- Thumbnail previews (1280/360/120px) are made by `intake.py` via `thumb_preview.py`. Reviewers must actually look at the images.
- Do not review what was not supplied (no thumbnail = skip that asset).

### 1. Pick the execution mode and tell the user which one ran
Run `python3 SKILL_DIR/scripts/run_panel.py check-env` (JSON). If `python3` is missing, go to Mode C by hand.

| Mode | When | Isolation |
|---|---|---|
| **A** LangGraph runner | `mode_a_possible: true` (Python 3.11+, key, deps) | Real: one separate API call per member, concurrent |
| **B** Native subagents | Mode A impossible AND the session can spawn subagents (Claude Code `Agent` tool) | Real: one subagent per member, concurrent |
| **C** Sequential passes | Neither | Simulated: say so plainly |

If only dependencies are missing, offer `pip install -r SKILL_DIR/scripts/requirements.txt` and `export ANTHROPIC_API_KEY=...` (never print or store the key). Otherwise fall through to B/C without nagging.

### 2. Reference creator persona (before the panel)
If `panel.yaml` has `channel_urls` for the reference member, build/refresh the card (cache lives in `.cache/personas/<handle>.md`, refreshed when older than `persona_cache_days`):

1. If a YouTube/vidIQ MCP tool is available in this session, pull recent titles, top videos and 3-5 transcripts with it, save as JSON `{"titles":[], "top_titles":[], "transcripts":[]}`, then `persona_builder.py --handle H --from-json file.json`.
2. Else `persona_builder.py --handle H --channel URL` (uses yt-dlp / youtube-transcript-api if installed).
3. If exit code is 4 (nothing fetchable): **ask the user to paste 2-3 transcripts or describe the creator**, save to files, run `--from-files`, and continue. If they decline, continue with the generic card.

Honesty rules for this persona: all its output is labelled "simulated opinion based on public content, not the real person's view". Never invent quotes or attribute fake statements; quote at most ~15 words of a transcript. Never use it to deceive anyone. See `references/personas.md`.

### 3. Run the panel

**Mode A**
```
python3 SKILL_DIR/scripts/run_panel.py run --project "<name>" \
  --title "<text or file>" [--title ...] --thumbnail img.png [--thumbnail ...] --thumb-text "<text>" \
  --script script.md [--brief brief.md] --format long --audience "<who>" --goal "<goal>" [--config panel.yaml]
```
It runs Phase 1 (parallel isolated) → round 1 critique → round 2 rebuttal → judge, validates the protocol, writes all files and prints the short summary. `--dry-run` uses a mocked LLM (for demos/CI; say it is not a real review). Exit 3 = validation failed (resume with `--resume <dir>`), 5 = Mode A unavailable.

**Mode B (subagents)** and **Mode C (sequential)** use the same helper commands so outputs are identical:
```
python3 SKILL_DIR/scripts/run_panel.py prepare  <same intake flags>      # prints {"dir": D}
python3 SKILL_DIR/scripts/run_panel.py emit --dir D --phase phase1        # writes D/prompts/phase1/<member>.md
```
For each phase in order `phase1 → critique → rebuttal → judge` (run `emit --phase <p>` first each time):
- **B:** spawn ONE subagent per member **in a single parallel batch**. Its instruction is only: "Read `D/prompts/<phase>/<member>.md` (it embeds the exact JSON schema), view the images it lists, do the task, write the JSON to the path it names. Read no other files." Wait for all before the next phase.
- **C:** do the members one at a time. For each, read only that member's prompt file, answer in character, write its JSON, and do NOT reread other members' outputs until the next phase's prompt file includes them. Tell the user: "isolation was simulated".
- The judge phase is one pass (`prompts/judge/judge.md`).
- Valid JSON shape: `python3 .../run_panel.py schema --phase <p>`.

Finally: `python3 SKILL_DIR/scripts/run_panel.py assemble --dir D --mode B` (or `C`). It validates every checkpoint (exit 3 lists problems: fix those member files and rerun) and writes the output tree and summary.

If Python is unavailable entirely (Mode C by hand): follow `references/debate_protocol.md` and write the files listed in `references/output_templates.md` yourself.

### 4. Reply in chat (about 250 words max)
Relay the script's summary: **mode that ran**, verdict per asset, top 3 fixes, biggest disagreement and the ruling, file paths. Never paste the transcript. Remind once that scores are judgment, figures are estimates unless a named tool supplied them, and (if used) that the reference-creator output is simulated.

## Optional evidence boost
If a vidIQ/YouTube MCP tool is available, pull real benchmarks (title score, similar videos, the channel's top titles/thumbnails) and append them to the brief file as "MEASURED (tool: X)". The analyst may cite them. Never required; never invent numbers.

## Panel and rules (summary)
- Members, weights, model, concurrency: `config/panel.yaml` (3-10 members + judge). Users add/remove/reweight/rewrite members there, including inline `card:` text, without touching code. Dimensions per asset: `config/rubric.yaml`.
- Protocol, anti-sycophancy, validation rules: `references/debate_protocol.md`. Rubrics: `references/rubric_title.md`, `rubric_thumbnail.md`, `rubric_script.md`. Persona cards and how to write new ones: `references/personas.md`. Output formats: `references/output_templates.md`.
- Every fix needs evidence. Score changes need reasons (run fails otherwise). Unanimous panels are flagged and the judge plays devil's advocate. The judge rules with reasons, never by averaging.
- Claims about income, job guarantees, medical or legal matters must be flagged by Stakeholder and Gatekeeper.
- Model comes from env `LLM_MODEL` or `panel.yaml`, never hardcoded. API keys are read from the environment only.

## Editing the panel
Tell the user to edit `config/panel.yaml` in the installed skill folder, or copy it to `./content-red-team.panel.yaml` in their project (picked up automatically) or pass `--config`.
