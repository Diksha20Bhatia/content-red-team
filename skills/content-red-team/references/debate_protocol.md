# Debate protocol

## Phases

| Phase | Name | Each member sees | Output |
|---|---|---|---|
| 1 | Independent analysis | own card, materials, rubric | `AssetReview` per asset |
| 2 | Cross-critique (round 1) | own card, materials, **all** phase-1 reports | challenges, endorsements, flags |
| 3 | Rebuttal (round 2) | own card, own report, critiques **aimed at them** | defend / concede / modify, score changes |
| 4 | Judge | everything | verdict, disputes with rulings, ranked fixes, rewrites |

Within a phase, calls are concurrent and isolated: no member sees another member's output from the same phase.

## Phase 1 rules

- Every `fix` point needs `evidence`: a quote, line number, timestamp, or thumbnail region (e.g. "top-left text at 120px").
- No vague praise. "Great hook" is rejected; "Opens with a concrete number in line 1" is accepted.
- Scores are 1-10 judgment on the dimensions in `rubric.yaml`. Never present them as data.
- Stay in character: use your card's bias and vocabulary. Do not hedge toward neutrality.
- With title/thumbnail variants, rank them and explain why.
- Thumbnail reviewers must describe what they can actually see in the image and the 120px preview.

## Phase 2 rules (cross-critique)

Each member must:
1. **Challenge at least 2** specific points from other members, quoting the claim exactly.
2. **Endorse at least 1** point they initially missed, quoting it.
3. **Flag** any point they think is wrong and say why.

## Phase 3 rules (rebuttal)

For each critique aimed at you: `defend`, `concede`, or `modify`, with reasoning. You may change a score only with a stated reason; every change is logged as (asset, dimension, before, after, because). A change without a reason fails validation and the run aborts.

## Anti-sycophancy

- Disagreement is expected. Conceding must be earned by a better argument, not by group pressure.
- No drift toward the group average. The scorecard reports how many changes moved toward the mean; a high ratio with weak reasons is called out.
- If all members agree on everything (overall-score spread of 1 or less on every asset and no real challenges), the run is flagged **suspicious** and the judge must open with a devil's-advocate section.
- The judge rules on disputes with reasons. Never "split the difference" or average.
- No invented statistics. Any metric is labelled `estimate` unless a real tool (e.g. vidIQ) supplied it, in which case name the tool.

## Real-person personas

Output from a persona built on a real creator is labelled "simulated opinion based on public content, not the real person's view". Never invent quotes or attribute statements to the person. Quote at most short snippets (under ~15 words) from transcripts.

## Claims policy

If the content makes claims about income, job guarantees, medical or legal matters, the Stakeholder and Domain Gatekeeper (or their config equivalents) must flag them with severity `major` or `blocker`, and the judge must address them in the verdict.
