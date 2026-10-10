#!/usr/bin/env bash
# Builds dist/content-red-team.zip for upload to Claude Desktop / claude.ai
# (Settings > Capabilities > Skills). The zip has ONE top-level folder, content-red-team/,
# with SKILL.md directly inside it. Tests and caches are excluded.
set -euo pipefail
cd "$(dirname "$0")/.."
SKILL=skills/content-red-team
[ -f "$SKILL/SKILL.md" ] || { echo "missing $SKILL/SKILL.md" >&2; exit 1; }

# sanity-check the frontmatter before packaging
python3 - "$SKILL/SKILL.md" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
m = re.match(r"---\n(.*?)\n---\n", t, re.S)
assert m, "SKILL.md must start with YAML frontmatter"
fm = m.group(1)
name = re.search(r"^name:\s*(\S+)", fm, re.M).group(1)
desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1)
assert name == "content-red-team", name
assert 0 < len(desc) <= 1024, f"description length {len(desc)}"
assert len(t.splitlines()) < 500, "SKILL.md must stay under 500 lines"
print(f"ok: name={name}, description={len(desc)} chars")
PY

rm -rf dist
mkdir -p dist
( cd skills && zip -rq ../dist/content-red-team.zip content-red-team \
    -x '*/__pycache__/*' '*/.pytest_cache/*' '*/.ruff_cache/*' '*.pyc' '*/scripts/tests/*' '*/.cache/*' '*/red-team-output/*' '*.DS_Store' )
echo "built dist/content-red-team.zip"
unzip -l dist/content-red-team.zip | tail -n +4 | awk '{print $4}' | grep -v '^$' | head -40
