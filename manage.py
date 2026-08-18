from __future__ import annotations

import argparse
import sys

from database import database
from runtime import configure_logging, format_preflight, run_preflight, settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FOAMTrame administration commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Validate the runtime environment")
    doctor.add_argument(
        "--skip-docker", action="store_true", help="Do not check for the Docker CLI"
    )
    subparsers.add_parser(
        "init-db", help="Initialize or upgrade the application database"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()

    if args.command == "doctor":
        result = run_preflight(check_docker=not args.skip_docker)
        print(format_preflight(result))
        return 0 if result["ok"] else 1

    if args.command == "init-db":
        database.initialize()
        print(f"Initialized FOAMTrame database: {settings.database_path}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
