# content-red-team

An installable [Agent Skill](https://agentskills.io/specification) that red-teams a YouTube **title, thumbnail and script** with a panel of **6 simulated reviewers plus a judge**.

1. **Independent analysis.** Every member reviews alone, in parallel, without seeing anyone else's notes.
2. **Debate.** Round 1: each challenges 2+ points from others, endorses 1, flags errors. Round 2: each rebuts, concedes or modifies, and any score change needs a stated reason.
3. **Judge.** Verdict per asset (ship / fix then ship / rework), right and wrong lists tagged by who agreed, rulings on disputes, ranked fixes, and rewrites (3 titles, 2-3 thumbnail concepts, a better first-20-seconds hook, cuts, and Shorts moments).

Creator- and niche-agnostic: the panel, weights, models and rubric live in `config/`. Nothing about a specific creator is hardcoded.

> The reference-YouTuber member is a **simulated opinion based on public content, not the real person's view**. All its output is labelled that way, quotes are capped at a few words, and nothing is invented or attributed to them.

## Install (three ways)

Commands below were checked against the current docs for the [skills CLI](https://github.com/vercel-labs/skills), [Claude Code plugins](https://code.claude.com/docs/en/plugins/create-marketplace) and [custom Claude skills](https://claude.com/docs/skills/how-to).

Replace `OWNER/REPO` with the GitHub repo you pushed this to (e.g. `Diksha20Bhatia/Youtube_script_argument_skill`, or `<you>/content-red-team` if you rename it).

### 1. `npx skills` (Claude Code and other agents)

```bash
npx skills add OWNER/REPO --list                      # preview: should list content-red-team
npx skills add OWNER/REPO --skill content-red-team    # interactive: pick agents and scope
npx skills add OWNER/REPO --skill content-red-team -a claude-code -g -y   # non-interactive, global, Claude Code only
npx skills ls                                         # verify it is installed
```

The CLI discovers `skills/content-red-team/SKILL.md` in the repo. In Claude Code it then appears under `/skills` and triggers on requests like "red team my video title and script". Install from a local clone with `npx skills add ./path/to/clone`.

### 2. Claude Code plugin / marketplace

```bash
claude plugin marketplace add OWNER/REPO
claude plugin install content-red-team@content-red-team
```

Or inside a session: `/plugin marketplace add OWNER/REPO`, then `/plugin install content-red-team@content-red-team`. The skill is then namespaced: `/content-red-team:content-red-team`. Local development: `claude --plugin-dir .`.

### 3. Claude Desktop / claude.ai (zip upload)

```bash
./scripts/build_zip.sh        # creates dist/content-red-team.zip
```

Then in Claude: **Customize > Skills** (claude.ai/customize/skills; older builds call it Settings > Capabilities > Skills) → upload `dist/content-red-team.zip` → turn the skill on. The zip has a single top-level `content-red-team/` folder with `SKILL.md` inside, as the docs require. Custom skills need a paid plan with code execution enabled. Note: Mode A (the Python runner) needs network access to the Anthropic API and Python packages, which the claude.ai sandbox may not allow; there the skill falls back to Mode B/C automatically.

### Update / uninstall

| | Update | Uninstall |
|---|---|---|
| skills CLI | `npx skills update content-red-team` (add `-g` for global) | `npx skills remove content-red-team` |
| Plugin | `claude plugin marketplace update content-red-team` then `claude plugin update content-red-team@content-red-team` | `claude plugin uninstall content-red-team@content-red-team`, `claude plugin marketplace remove content-red-team` |
| Zip | Rebuild, delete the old skill under Customize > Skills, upload again | Delete it under Customize > Skills |

## What you provide

| Needed for | What |
|---|---|
| Any review | Script (md/txt/pdf/docx or pasted) and the format (`long` / `short` / `webinar`) |
| Better review | Title(s), thumbnail image(s) + on-image text, brief/creator profile, target audience, goal |
| Reference-creator persona | Channel URL(s) in `config/panel.yaml`, or 2-3 pasted transcripts |
| Mode A (best) | Python 3.11+, `pip install -r skills/content-red-team/scripts/requirements.txt`, `export ANTHROPIC_API_KEY=...` (read from env only, never stored) |

## Use it

Just ask: *"Red team my video title, thumbnail and script"* and attach or point to the files. The agent asks one short question only if the script or format is missing.

Run the runner directly (Mode A):

```bash
export ANTHROPIC_API_KEY=...        # never commit this
python3 skills/content-red-team/scripts/run_panel.py run --project "My video" \
  --title title.txt --thumbnail thumb_a.png --thumbnail thumb_b.png --thumb-text "TEXT A" --thumb-text "TEXT B" \
  --script script.md --brief brief.md --format long --audience "first-time founders" --goal "grow subscribers"

python3 skills/content-red-team/scripts/run_panel.py run --dry-run ...   # mocked LLM, no key (demo/CI only)
python3 skills/content-red-team/scripts/run_panel.py check-env           # which mode is possible here
```

A titles file with several lines, or repeated `--title` / `--thumbnail`, creates A/B/C variants that members rank. Model: env `LLM_MODEL` or `model:` in `panel.yaml` (never hardcoded). If a run fails validation, fix and resume with `--resume <output dir>`; completed calls are checkpointed.

Output goes to `./red-team-output/<project>/<YYYYMMDD_HHMM>/`:

```
00_inputs_summary.md   01_independent/<member>.{json,md}   02_critique/<member>.md
03_rebuttal/<member>.md   debate_transcript.md   scorecard.md   verdict.md   rewrites.md
```

See `skills/content-red-team/examples/` for sample inputs and a (mocked) sample output.

### Execution modes (SKILL.md picks at runtime and always says which ran)

| Mode | When | Isolation |
|---|---|---|
| A. LangGraph runner | Python 3.11+, API key, deps installed | Real: one API call per member, concurrent (`Send` fan-out), checkpointed |
| B. Native subagents | No Python/key, but the session can spawn subagents (Claude Code) | Real: one subagent per member, given only its own prompt file |
| C. Sequential passes | Neither | Simulated, and the user is told so |

B and C use `run_panel.py prepare / emit / assemble`, so validation and the output files are identical to Mode A.

## Edit the panel (no code changes)

Edit `skills/content-red-team/config/panel.yaml`, or copy it to `./content-red-team.panel.yaml` in your project (auto-detected) or pass `--config`.

- **Reference creator:** set `channel_urls` and `handle`. Then build the persona card: `python3 scripts/persona_builder.py --handle <handle> --channel <url>` (or `--from-json` / `--from-files` with transcripts). Cached at `.cache/personas/<handle>.md`, refreshed after `persona_cache_days`.
- **Target viewer:** set `audience`. **Domain gatekeeper:** set `domain` (hiring manager, clinician, senior engineer...).
- **Add a 7th member:** copy a block, give it a new `id`, and write an inline `card:`. Min 3, max 10 members plus the judge. Reweight with `weight:`; disable with `enabled: false`.
- **Scoring dimensions:** `config/rubric.yaml`. Persona card format and writing guide: `references/personas.md`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `npx skills add` finds nothing | The repo must contain `skills/content-red-team/SKILL.md` on the default branch (push first). `--list` shows what it sees. |
| Not under `/skills` | Restart the Claude Code session; check scope (`-g` vs project) with `npx skills ls`. |
| `Mode A unavailable` (exit 5) | `check-env` lists what is missing: Python 3.11+, `ANTHROPIC_API_KEY`, `pip install -r .../requirements.txt`. Or continue in Mode B/C. |
| `VALIDATION FAILED` (exit 3) | A member broke the protocol (e.g. score change without a reason, quote that matches nothing). Re-run with `--resume`; the message names the member. |
| `NEEDS_USER` from persona_builder (exit 4) | Nothing could be fetched. Paste 2-3 transcripts to files and use `--from-files`. |
| PDF script unreadable | `pip install pypdf`, or paste the text. |
| Zip rejected on upload | Re-run `build_zip.sh`; check `unzip -l` shows every entry under `content-red-team/`. If the upload UI rejects the description length, shorten the `description:` in SKILL.md. |
| Thumbnail not reviewed | Pass `--thumbnail` as png/jpg/webp. Reviewers see 1280px and 120px versions. |

## Known limitations

- Reviews are simulated opinions, not audience data. Scores are judgment; figures are estimates unless a named tool (e.g. vidIQ) supplied them. A/B test before betting on a verdict.
- The persona of a real creator is only as good as the public material available (titles, transcripts) and is a stylistic approximation.
- Mode A costs roughly 20-25 model calls per run (6 members × 3 phases + judge), more with long scripts. Mode A prompts include the full script each phase.
- Video content itself (footage, audio, pacing on screen) is not analysed, only the text and thumbnail image.
- Mode B/C isolation depends on the agent following the instructions; only Mode A and B enforce it structurally.
- Dry-run output is templated and exists only to test the pipeline.

## Develop

```bash
pip install -r skills/content-red-team/scripts/requirements.txt pytest ruff
ruff check . && python -m pytest skills/content-red-team/scripts/tests -q   # mocked LLM, no secrets
./scripts/build_zip.sh
./scripts/make_sample_output.sh
```

Tests cover: prompt isolation per phase, concurrency per phase, real disagreement with judge rulings, mandatory reasons for score changes, config swap and a 7th member, thumbnail vision inputs, Mode B/C assemble, persona fallbacks, and the SKILL.md contract. CI (`.github/workflows/ci.yml`) runs them plus a `--dry-run` with no secrets.

MIT licensed.
