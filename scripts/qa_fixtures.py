"""Run the golden QA fixtures against a local RainCheck server.

Read-only by default? No: the fixture file has three sections and enrollment
and storm cases mutate the demo pool. The runner is therefore sandbox-only. It
refuses to mutate a server that is not in ``mock`` PayPal mode unless you pass
``--allow-sandbox-mutations`` explicitly, and it resets the demo when it is done.

Usage::

    python scripts/qa_fixtures.py                     # local mock server
    python scripts/qa_fixtures.py --read-only         # parse cases only
    python scripts/qa_fixtures.py --base-url http://127.0.0.1:8000 \
        --operator-key dev-operator-key

Exit code 0 means every fixture matched. Nothing here touches real money.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES = ROOT / "fixtures" / "qa_scenarios.json"


class CheckFailure(AssertionError):
    pass


def request(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict]:
    data = None
    all_headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def get_path(payload: dict, path: str):
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise CheckFailure(f"missing field {path!r}")
        current = current[part]
    return current


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def match_expectations(payload: dict, expect: dict, label: str) -> None:
    for path, wanted in expect.items():
        actual = get_path(payload, path)
        check(actual == wanted, f"{label}: {path} expected {wanted!r}, got {actual!r}")


def run_parse(base: str, fixture: dict) -> None:
    status, body = request(
        "POST",
        f"{base}/api/policies/parse",
        body={"text": fixture["text"], "zone": fixture["zone"]},
    )
    check(status == 200, f"parse {fixture['id']}: HTTP {status}")
    match_expectations(body, fixture.get("expect", {}), f"parse {fixture['id']}")
    warnings = " ".join((body.get("policy") or {}).get("warnings", []))
    wanted_warning = fixture.get("warnings_include")
    if wanted_warning:
        check(
            wanted_warning.lower() in warnings.lower(),
            f"parse {fixture['id']}: warning missing {wanted_warning!r} (got {warnings!r})",
        )
    wanted_error = fixture.get("error_includes")
    if wanted_error:
        check(
            wanted_error.lower() in (body.get("error") or "").lower(),
            f"parse {fixture['id']}: error missing {wanted_error!r} (got {body.get('error')!r})",
        )


def run_enrollment(
    base: str, operator: dict[str, str], fixture: dict, enrolled: dict[str, dict]
) -> None:
    if fixture.get("action") == "sybil_demo":
        status, body = request(
            "POST", f"{base}/api/operator/demo/fraud-attempt", headers=operator
        )
        check(status == 200, f"enrollment {fixture['id']}: HTTP {status}")
        expect = fixture.get("expect", {})
        check(body.get("blocked") is True, f"enrollment {fixture['id']}: not blocked")
        score = body.get("screening", {}).get("score", 0)
        minimum = expect.get("screening.score_at_least", 0)
        check(score >= minimum, f"enrollment {fixture['id']}: score {score} < {minimum}")
        flags = body.get("screening", {}).get("flags", [])
        minimum_flags = fixture.get("flags_at_least", 0)
        check(
            len(flags) >= minimum_flags,
            f"enrollment {fixture['id']}: {len(flags)} flags < {minimum_flags}",
        )
        return

    if "duplicate_email_of" in fixture:
        earlier = enrolled[fixture["duplicate_email_of"]]
        status, body = request("POST", f"{base}/api/policies", body=earlier["payload"])
        wanted = fixture.get("expect_http", 409)
        check(
            status == wanted,
            f"enrollment {fixture['id']}: expected HTTP {wanted}, got {status} ({body})",
        )
        return

    parsed_status, parsed = request(
        "POST",
        f"{base}/api/policies/parse",
        body={"text": fixture["source_text"], "zone": fixture["member"]["zone"]},
    )
    check(parsed_status == 200, f"enrollment {fixture['id']}: parse HTTP {parsed_status}")
    check(parsed.get("ok") is True, f"enrollment {fixture['id']}: parse failed {parsed}")
    payload = {
        "member": fixture["member"],
        "policy": parsed["policy"],
        "source_text": fixture["source_text"],
    }
    status, body = request("POST", f"{base}/api/policies", body=payload)
    check(status == 201, f"enrollment {fixture['id']}: HTTP {status}: {body}")
    match_expectations(body, fixture.get("expect", {}), f"enrollment {fixture['id']}")
    wanted_flag = fixture.get("flags_include")
    if wanted_flag:
        codes = [flag.get("code") for flag in body.get("screening", {}).get("flags", [])]
        check(wanted_flag in codes, f"enrollment {fixture['id']}: flag {wanted_flag} missing")
    enrolled[fixture["id"]] = {"payload": payload, "response": body}


def run_simulate(
    base: str, operator: dict[str, str], fixture: dict, event_ids: dict[str, str]
) -> None:
    pause = fixture.get("pause_first")
    if pause:
        status, body = request(
            "POST", f"{base}/api/operator/pause", body=pause, headers=operator
        )
        check(status == 200, f"simulate {fixture['id']}: pause HTTP {status}: {body}")

    try:
        payload = {
            "zone": fixture["zone"],
            "rainfall_mm": fixture["rainfall_mm"],
            "days": fixture["days"],
            "event_key": fixture["event_key"],
        }
        status, body = request(
            "POST", f"{base}/api/events/simulate", body=payload, headers=operator
        )
        check(status == 200, f"simulate {fixture['id']}: HTTP {status}: {body}")
        match_expectations(body, fixture.get("expect", {}), f"simulate {fixture['id']}")

        wanted_reason = fixture.get("reason_codes_include")
        if wanted_reason:
            codes = [row.get("code") for row in body.get("reasons", [])]
            check(
                wanted_reason in codes,
                f"simulate {fixture['id']}: reason {wanted_reason} missing ({codes})",
            )

        reference = fixture.get("same_event_as")
        if reference:
            wanted_id = event_ids.get(reference)
            actual_id = get_path(body, "event.id")
            check(
                actual_id == wanted_id,
                f"simulate {fixture['id']}: event {actual_id} != {wanted_id}",
            )

        event_ids[fixture["id"]] = body["event"]["id"]
    finally:
        if fixture.get("resume_after"):
            request(
                "POST",
                f"{base}/api/operator/pause",
                body={"paused": False},
                headers=operator,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--operator-key",
        default=os.environ.get("OPERATOR_API_KEY", "dev-operator-key"),
    )
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="run the parse section only; do not enroll or simulate anything",
    )
    parser.add_argument(
        "--allow-sandbox-mutations",
        action="store_true",
        help="allow enrollment/storm fixtures when PayPal is in sandbox mode",
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    operator = {"X-Operator-Key": args.operator_key}

    try:
        status, health = request("GET", f"{base}/api/health")
    except OSError as exc:
        print(f"FAIL cannot reach {base}: {exc}")
        return 2
    check(status == 200, f"health: HTTP {status}")
    check(health.get("database") == "ok", f"health: database not ok ({health})")
    mode = health.get("paypal_mode")
    print(f"server: {base}  paypal_mode={mode}  ai_mode={health.get('ai_mode')}")

    raw = args.fixtures.read_text(encoding="utf-8").replace(
        "{{timestamp}}", str(int(time.time()))
    )
    fixtures = json.loads(raw)

    passed = 0
    failed = 0

    def run(label: str, fn) -> None:
        nonlocal passed, failed
        try:
            fn()
        except (CheckFailure, KeyError, ValueError, AttributeError, TypeError) as exc:
            failed += 1
            print(f"FAIL {label}: {exc}")
        else:
            passed += 1
            print(f"PASS {label}")

    for fixture in fixtures.get("parse", []):
        run(f"parse/{fixture['id']}", lambda f=fixture: run_parse(base, f))

    if args.read_only:
        print("\nread-only run: enrollment and storm fixtures skipped")
    elif mode != "mock" and not args.allow_sandbox_mutations:
        print(
            "\nrefusing to mutate PayPal mode "
            f"{mode!r}; re-run with --allow-sandbox-mutations or use --read-only"
        )
        failed += 1
    else:
        enrolled: dict[str, dict] = {}
        event_ids: dict[str, str] = {}
        try:
            for fixture in fixtures.get("enrollment", []):
                run(
                    f"enrollment/{fixture['id']}",
                    lambda f=fixture: run_enrollment(base, operator, f, enrolled),
                )
            for fixture in fixtures.get("simulate", []):
                run(
                    f"simulate/{fixture['id']}",
                    lambda f=fixture: run_simulate(base, operator, f, event_ids),
                )
        finally:
            status, body = request(
                "POST", f"{base}/api/operator/demo/reset", headers=operator
            )
            if status == 200:
                print(
                    "demo reset:",
                    body.get("rehearsal_members_removed"),
                    "rehearsal member(s) removed",
                )
            else:
                print(f"WARN demo reset failed: HTTP {status}: {body}")

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
