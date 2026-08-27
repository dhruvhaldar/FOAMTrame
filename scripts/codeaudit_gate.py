"""Run CodeAudit with a severity threshold suitable for CI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def collect_findings(scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten CodeAudit's per-file result into stable finding records."""
    findings: list[dict[str, Any]] = []
    for file_result in scan_result.get("file_security_info", {}).values():
        file_path = str(file_result.get("FilePath", file_result.get("FileName", "?")))
        for finding in file_result.get("sast_result", {}).values():
            findings.append({"path": file_path, **finding})
    return sorted(
        findings,
        key=lambda item: (item["path"], int(item.get("line", 0))),
    )


def blocks_build(finding: dict[str, Any], minimum_severity: str) -> bool:
    severity = str(finding.get("severity", "low")).lower()
    return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[minimum_severity]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", default=".", help="File or directory to scan"
    )
    parser.add_argument(
        "--fail-on",
        choices=tuple(SEVERITY_RANK),
        default="medium",
        help="Minimum severity that fails the audit (default: medium)",
    )
    args = parser.parse_args(argv)

    try:
        from codeaudit.api_interfaces import (  # ty: ignore[unresolved-import, unused-ignore-comment]
            filescan,
        )
    except ImportError:
        parser.error(
            "CodeAudit is unavailable; use Python 3.11+ and install dev dependencies"
        )

    scan_root = Path(args.path).resolve()
    findings = collect_findings(filescan(str(scan_root), nosec=True))
    blocking = [item for item in findings if blocks_build(item, args.fail_on)]

    for finding in findings:
        path = Path(finding["path"])
        try:
            display_path = path.resolve().relative_to(scan_root).as_posix()
        except ValueError:
            display_path = str(path)
        print(
            f"{display_path}:{finding.get('line', 0)}: "
            f"{finding.get('severity', 'Unknown')} "
            f"{finding.get('validation', 'unknown')}"
        )

    print(
        f"CodeAudit: {len(findings)} unsuppressed finding(s); "
        f"{len(blocking)} at or above {args.fail_on}."
    )
    return 3 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
