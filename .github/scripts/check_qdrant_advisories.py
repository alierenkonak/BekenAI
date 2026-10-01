"""Fail if the pinned Qdrant image falls in a published Qdrant security advisory.

pip-audit and npm audit never see the database server, which is how CVE-2026-25628
went unnoticed. The version comes from docker-compose.yml; the server's unit must pin
the same image.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ADVISORIES = "https://api.github.com/repos/qdrant/qdrant/security-advisories?per_page=100"


def version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.strip().lstrip("v").split("."))


def affected(pinned: tuple[int, ...], vulnerable_range: str) -> bool:
    """`>= 1.9.3, < 1.15.6`-style ranges, as GitHub advisories write them."""
    for condition in vulnerable_range.split(","):
        match = re.fullmatch(r"\s*(>=|<=|>|<|=)?\s*v?(\d+(?:\.\d+)*)\s*", condition)
        if match is None:
            raise ValueError(f"Unsupported version range: {vulnerable_range!r}")
        operator, bound = match.group(1) or "=", version(match.group(2))
        holds = {
            ">=": pinned >= bound,
            "<=": pinned <= bound,
            ">": pinned > bound,
            "<": pinned < bound,
            "=": pinned == bound,
        }[operator]
        if not holds:
            return False
    return True


def main() -> int:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(r"qdrant/qdrant:v(\d+\.\d+\.\d+)@sha256:[0-9a-f]{64}", compose)
    if match is None:
        print("docker-compose.yml does not pin a Qdrant image by version and digest")
        return 1
    unit = Path("deploy/oracle/bekenai-qdrant.service").read_text(encoding="utf-8")
    if match.group(0) not in unit:
        print("docker-compose.yml and the server unit pin different Qdrant images")
        return 1
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(ADVISORIES, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        advisories = json.load(response)
    pinned = version(match.group(1))
    found = [
        advisory
        for advisory in advisories
        if any(
            vulnerability.get("vulnerable_version_range")
            and affected(pinned, vulnerability["vulnerable_version_range"])
            for vulnerability in advisory.get("vulnerabilities") or []
        )
    ]
    for advisory in found:
        print(f"{advisory['ghsa_id']} ({advisory['severity']}): {advisory['summary']}")
    print(f"Qdrant {match.group(1)}: {len(found)} of {len(advisories)} advisories apply")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
