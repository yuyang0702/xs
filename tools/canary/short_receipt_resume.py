"""Actual launcher for a bounded, receipt-only Short recovery operation.

The default command is a zero-dispatch preflight. ``--execute`` is fail-closed
unless a positive dispatch allowance is supplied by the caller.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from novel_flywheel.app import create_app
from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.secrets import KeyringSecretStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--db", type=Path, required=True)
    result.add_argument("--workspace-root", type=Path, required=True)
    result.add_argument("--references-root", type=Path, required=True)
    result.add_argument("--project-id", required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--candidate", required=True)
    result.add_argument("--candidate-sha256", required=True)
    result.add_argument("--task-id", required=True)
    result.add_argument("--execute", action="store_true")
    result.add_argument("--max-dispatches", type=int, default=0)
    return result


async def run(args: argparse.Namespace) -> dict:
    db = Database(args.db)
    db.migrate()
    references = ReferenceLibrary(db, args.references_root)
    app = create_app(
        db=db,
        secrets=KeyringSecretStore(),
        workspace_root=args.workspace_root,
        reference_library=references,
    )
    return await app.state.workflows.resume_short_receipt(
        args.project_id,
        run_id=args.run_id,
        candidate_relative_path=args.candidate,
        candidate_sha256=args.candidate_sha256,
        task_id=args.task_id,
        execute=args.execute,
        max_dispatches=args.max_dispatches,
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
