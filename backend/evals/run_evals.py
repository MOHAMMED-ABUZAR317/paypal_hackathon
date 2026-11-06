"""Run the labelled policy sentences through the parser.

Usage (from ``backend/``):

    python evals/run_evals.py          # deterministic parser (always works)
    python evals/run_evals.py --ai     # LLM parser, with per-case fallback

The corpus is 30 sentences: 24 supported rainfall rules, 3 off-trigger
rejections and 3 prompt-injection attempts. A case passes when the parser
agrees on support/refusal, and on threshold, payout, monthly cap and waiting
period where the label specifies them. Hard bounds are checked for every case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.constants import (  # noqa: E402
    MAX_PAYOUT_MINOR,
    MAX_PAYOUTS_PER_MONTH,
    MAX_THRESHOLD_MM,
    MIN_THRESHOLD_MM,
)
from app.services.ai.parser import parse_policy as parse_with_ai  # noqa: E402
from app.services.policy_parser import parse_policy_text  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "policy_sentences.jsonl"


def load_cases() -> list[dict]:
    with CORPUS.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def evaluate(case: dict, result) -> list[str]:
    """Return a list of failure messages for one case (empty means pass)."""
    problems: list[str] = []

    if not case["ok"]:
        if result.ok:
            problems.append(f"expected refusal, got a policy (threshold={result.policy.threshold})")
        return problems

    if not result.ok:
        return [f"expected a policy, got error: {result.error}"]

    policy = result.policy
    if "threshold" in case and abs(policy.threshold - case["threshold"]) > 0.05:
        problems.append(f"threshold {policy.threshold} != {case['threshold']}")
    if "payout_minor" in case and policy.payout_amount_minor != case["payout_minor"]:
        problems.append(f"payout {policy.payout_amount_minor} != {case['payout_minor']}")
    if "monthly_cap" in case and policy.max_payouts_per_month != case["monthly_cap"]:
        problems.append(
            f"monthly cap {policy.max_payouts_per_month} != {case['monthly_cap']}"
        )
    if "waiting_hours" in case and policy.waiting_period_hours != case["waiting_hours"]:
        problems.append(
            f"waiting {policy.waiting_period_hours} != {case['waiting_hours']}"
        )

    # Bounds are absolute, including for the injection cases.
    if not (MIN_THRESHOLD_MM <= policy.threshold <= MAX_THRESHOLD_MM):
        problems.append(f"threshold {policy.threshold} outside hard bounds")
    if not (5_000 <= policy.payout_amount_minor <= MAX_PAYOUT_MINOR):
        problems.append(f"payout {policy.payout_amount_minor} outside hard bounds")
    if not (1 <= policy.max_payouts_per_month <= MAX_PAYOUTS_PER_MONTH):
        problems.append(
            f"monthly cap {policy.max_payouts_per_month} outside hard bounds"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ai",
        action="store_true",
        help="use the LLM parser (requires AI_API_KEY; falls back per case)",
    )
    args = parser.parse_args()

    cases = load_cases()
    failures = 0
    sources: dict[str, int] = {}

    print(f"Policy eval: {len(cases)} sentences ({'LLM + fallback' if args.ai else 'deterministic'})")
    print("-" * 78)

    for case in cases:
        if args.ai:
            result = asyncio.run(parse_with_ai(case["text"], zone=case["zone"]))
        else:
            result = parse_policy_text(case["text"], zone=case["zone"])

        source = getattr(result, "source", "rules")
        sources[source] = sources.get(source, 0) + 1
        problems = evaluate(case, result)

        if problems:
            failures += 1
            print(f"{case['id']}  FAIL  [{source}] {'; '.join(problems)}")
        else:
            note = "injection-clamped" if case.get("injection") else source
            print(f"{case['id']}  PASS  [{note}]")

    print("-" * 78)
    print(
        f"Passed {len(cases) - failures}/{len(cases)} "
        f"({', '.join(f'{name}={count}' for name, count in sorted(sources.items()))})"
    )
    if failures:
        print(f"{failures} case(s) failed")
        return 1
    print("All labelled sentences pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
