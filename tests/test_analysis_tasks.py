import asyncio

from novel_flywheel.analysis_tasks import ReferenceAnalysisTaskManager


async def test_reference_analysis_task_records_failure() -> None:
    manager = ReferenceAnalysisTaskManager()

    async def fail(_progress):
        raise RuntimeError("provider timeout")

    manager.start("source-1", fail)
    await asyncio.sleep(0)

    state = manager.get_for_source("source-1")
    assert state["status"] == "failed"
    assert state["error"] == "provider timeout"
    assert state["finished_at"]


async def test_reference_analysis_task_names_an_error_without_a_message() -> None:
    manager = ReferenceAnalysisTaskManager()

    async def fail(_progress):
        raise TimeoutError()

    manager.start("source-1", fail)
    await asyncio.sleep(0)

    assert manager.get_for_source("source-1")["error"] == (
        "TimeoutError (provider returned no error detail)"
    )


async def test_reference_analysis_task_can_be_cancelled() -> None:
    manager = ReferenceAnalysisTaskManager()
    blocker = asyncio.Event()

    async def wait(_progress):
        await blocker.wait()

    started = manager.start("source-1", wait)
    cancelled = manager.cancel(started["id"])
    await asyncio.sleep(0)

    assert cancelled["status"] == "cancelled"
    assert manager.get_for_source("source-1")["phase"] == "cancelled"


async def test_reference_analysis_task_exposes_resume_progress() -> None:
    manager = ReferenceAnalysisTaskManager()
    blocker = asyncio.Event()

    async def resume(progress):
        progress({
            "phase": "analyzing_windows", "completed_windows": 9, "total_windows": 15,
            "reused_windows": 9, "current_window": 10,
        })
        await blocker.wait()

    manager.start("source-1", resume)
    await asyncio.sleep(0)

    state = manager.get_for_source("source-1")
    assert state["reused_windows"] == 9
    assert state["current_window"] == 10

    blocker.set()
    await asyncio.sleep(0)
