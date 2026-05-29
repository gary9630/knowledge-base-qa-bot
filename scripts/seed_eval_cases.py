from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.evals.cases import load_default_seed_cases, seed_eval_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed eval cases into the database.")
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Optional JSON seed file. Uses bundled defaults when omitted.",
    )
    namespace = parser.parse_args(argv)

    try:
        cases = load_default_seed_cases(namespace.file)
        with SessionLocal() as session:
            summary, _ = seed_eval_cases(session, cases)
            session.commit()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        "Seeded eval cases: "
        f"{summary.created} created, {summary.updated} updated, {summary.total} total."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
