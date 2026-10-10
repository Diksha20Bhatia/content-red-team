#!/usr/bin/env bash
# Regenerates examples/sample_output from a --dry-run (mocked LLM, NOT a real review).
set -euo pipefail
cd "$(dirname "$0")/.."
S=skills/content-red-team
T=$(mktemp -d)
python3 $S/scripts/run_panel.py run --dry-run --mock-delay 0 --out-root "$T" --cache-dir "$T/cache" --project sample \
  --title $S/examples/sample_input/title.txt --thumbnail $S/examples/sample_input/thumbnail.png --thumb-text "STOP MEMORISING" \
  --script $S/examples/sample_input/script.md --brief $S/examples/sample_input/brief.md --format long \
  --audience "aspiring product managers" > "$T/summary.txt"
rm -rf $S/examples/sample_output && mkdir -p $S/examples/sample_output
RUN=$(echo "$T"/sample/*)
rsync -a --exclude '.checkpoints' --exclude 'prompts.jsonl' --exclude 'inputs.json' --exclude 'thumbs' "$RUN"/ $S/examples/sample_output/
sed "s#^Files: .*#Files: red-team-output/<project>/<timestamp>/ (verdict.md, rewrites.md, scorecard.md, debate_transcript.md)#" "$T/summary.txt" > $S/examples/sample_output/chat_summary.txt
cat > $S/examples/sample_output/README.md <<'MD'
# Sample output (DRY-RUN, mocked LLM)

Generated with `run_panel.py run --dry-run`. The content is templated, **not a real review**: it only shows the
file layout, scorecard format, dispute rulings and chat summary. Run without `--dry-run` (Mode A) for real output.
MD
echo "wrote $S/examples/sample_output"
