"""npm audit with reviewed exceptions for development-only tooling.

`npm audit --audit-level=high` cannot ignore one advisory, so an advisory without a fix in
a lint tool would block every pull request. This runs the audit twice:

- production dependencies only: any high or critical advisory fails, with no exceptions;
- all dependencies: a high or critical advisory fails unless frontend/npm-audit-exceptions.json
  lists it with a reason and an expiry date. An expired exception fails too, so it is
  reviewed again; one no longer reported is flagged for removal.

Run from the frontend directory.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

FAILING = {"high", "critical"}
EXCEPTIONS = Path("npm-audit-exceptions.json")


def advisories(*options: str) -> dict[str, str]:
    """High and critical advisories as {GHSA id: "package: title"}."""
    result = subprocess.run(
        ["npm", "audit", "--json", *options], capture_output=True, text=True, check=False
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(f"npm audit did not return a report (exit {result.returncode})")
    if "vulnerabilities" not in report:
        sys.exit(f"npm audit failed: {report.get('error', report)}")
    found: dict[str, str] = {}
    for vulnerability in report["vulnerabilities"].values():
        for cause in vulnerability.get("via", []):
            # Strings name another vulnerable package; only objects are advisories.
            if isinstance(cause, dict) and cause.get("severity") in FAILING:
                advisory = str(cause.get("url", "")).rsplit("/", 1)[-1] or str(cause["source"])
                found[advisory] = f"{cause.get('name')}: {cause.get('title')}"
    return found


def main() -> int:
    failures: list[str] = []
    for advisory, what in sorted(advisories("--omit=dev").items()):
        failures.append(f"{advisory} ({what}) is in a production dependency")

    exceptions = {item["id"]: item for item in json.loads(EXCEPTIONS.read_text("utf-8"))}
    today = date.today()
    for advisory, item in sorted(exceptions.items()):
        if date.fromisoformat(item["expires"]) < today:
            failures.append(f"the exception for {advisory} expired on {item['expires']}")

    reported = advisories()
    for advisory, what in sorted(reported.items()):
        if advisory not in exceptions:
            failures.append(f"{advisory} ({what})")
        else:
            print(f"Accepted until {exceptions[advisory]['expires']}: {advisory} ({what})")
    for advisory in sorted(exceptions.keys() - reported.keys()):
        print(f"::warning::{advisory} is no longer reported; remove it from {EXCEPTIONS}")

    for failure in failures:
        print(f"::error::{failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
