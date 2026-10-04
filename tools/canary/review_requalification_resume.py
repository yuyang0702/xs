"""Resume one existing Short run under exact Review requalification authority.

The command uses the application-owned RunTaskManager and normal Short pipeline.
It does not create a run, change role bindings, or generate a replacement for
the candidate named on the command line.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from novel_flywheel.app import create_app
from novel_flywheel.config import configure_runtime_environment
from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary
from novel_flywheel.secrets import KeyringSecretStore
from novel_flywheel.provider_response_capture import (
    ReviewDiagnosticCaptureObserverV1,
)


def canonical_candidate_sha256(path: Path) -> str:
    """Match the workflow's UTF-8 text authority across CRLF/LF storage."""

    return hashlib.sha256(
        path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--db", type=Path, required=True)
    result.add_argument("--workspace-root", type=Path, required=True)
    result.add_argument("--references-root", type=Path, required=True)
    result.add_argument("--project-id", required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--candidate", type=Path, required=True)
    result.add_argument("--candidate-sha256", required=True)
    result.add_argument("--max-dispatches", type=int, default=4)
    result.add_argument("--max-dispatches-per-route", type=int, default=2)
    result.add_argument("--authorization-revision", default="v1")
    result.add_argument("--allow-semantic-repair", action="store_true")
    result.add_argument("--capture-dir", type=Path)
    result.add_argument("--capture-provider-id")
    result.add_argument("--capture-model-id")
    result.add_argument("--capture-host")
    return result


async def run(args: argparse.Namespace) -> dict:
    configure_runtime_environment(args.db.parent)
    db = Database(args.db)
    db.migrate()
    run_record = db.get_run(args.run_id)
    if run_record is None:
        raise LookupError("run not found")
    if (
        str(run_record.get("project_id")) != args.project_id
        or str(run_record.get("workflow")) != "short-story"
    ):
        raise ValueError("run identity does not match the requested Short project")
    candidate = args.candidate.resolve()
    if not candidate.is_file():
        raise ValueError("candidate file is unavailable")
    candidate_bytes = candidate.read_bytes()
    candidate_sha256 = canonical_candidate_sha256(candidate)
    if candidate_sha256 != args.candidate_sha256:
        raise ValueError("candidate file hash is stale")

    references = ReferenceLibrary(db, args.references_root)
    app = create_app(
        db=db,
        secrets=KeyringSecretStore(),
        workspace_root=args.workspace_root,
        reference_library=references,
    )
    if args.capture_dir is not None:
        if not all((args.capture_provider_id, args.capture_model_id, args.capture_host)):
            raise ValueError("capture provider, model and host must be supplied together")
        observer = ReviewDiagnosticCaptureObserverV1(
            store_root=args.capture_dir,
            provider_id=args.capture_provider_id,
            model_id=args.capture_model_id,
            hostname=args.capture_host,
            context={
                "project_id": args.project_id,
                "run_id": args.run_id,
                "candidate_sha256": candidate_sha256,
                "authorization_revision": args.authorization_revision,
                "capture_scope": "single_formal_review_diagnostic_request",
            },
        )
        app.state.registry.attempt_observer = observer

    async def operation(existing_run_id: str):
        with app.state.workflows.authorize_review_contract_requalification(
            run_id=existing_run_id,
            candidate_sha256=candidate_sha256,
            max_dispatches=args.max_dispatches,
            max_dispatches_per_route=args.max_dispatches_per_route,
            authorization_revision=args.authorization_revision,
            allow_semantic_repair=args.allow_semantic_repair,
        ):
            return await app.state.workflows.run_short(
                args.project_id, use_crewai=False, run_id=existing_run_id,
            )

    app.state.run_tasks.resume(args.run_id, operation)
    task = app.state.run_tasks.tasks[args.run_id]
    await task
    if candidate.read_bytes() != candidate_bytes:
        raise RuntimeError("authorized Review resume changed the bound candidate file")
    final_run = db.get_run(args.run_id) or {}
    attempts = [
        item for item in db.list_workflow_attempts(args.run_id)
        if item.get("action") == "review_contract_requalification_dispatch"
    ]
    return {
        "run_id": args.run_id,
        "status": final_run.get("status"),
        "current_stage": final_run.get("current_stage"),
        "error": final_run.get("error"),
        "candidate_sha256": candidate_sha256,
        "candidate_unchanged": True,
        "review_requalification_attempts": attempts,
        "capture_dir": str(args.capture_dir.resolve()) if args.capture_dir else None,
        "capture_dispatch_count": (
            getattr(observer, "dispatch_count", None) if args.capture_dir else None
        ),
        "capture_response_count": (
            getattr(observer, "response_count", None) if args.capture_dir else None
        ),
        "capture_runtime_input_count": (
            getattr(observer, "runtime_input_count", None) if args.capture_dir else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
