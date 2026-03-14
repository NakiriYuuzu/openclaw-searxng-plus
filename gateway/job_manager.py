import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from .cache import get_job_state, list_jobs_by_status, set_job_state

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, max_concurrent: int = 10):
        self._max_concurrent = max_concurrent
        self._tasks: dict[str, asyncio.Task] = {}
        self._local_state: dict[str, dict[str, Any]] = {}

    def _generate_id(self) -> str:
        return f"job_{uuid.uuid4().hex[:12]}"

    @property
    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())

    def get_local_state(self, job_id: str) -> dict[str, Any] | None:
        return self._local_state.get(job_id)

    async def create_job(
        self,
        coro_fn: Callable[[str], Coroutine[Any, Any, None]],
    ) -> str:
        if self.active_count >= self._max_concurrent:
            raise RuntimeError(
                f"Max concurrent site crawl jobs ({self._max_concurrent}) reached"
            )

        job_id = self._generate_id()
        now = datetime.now(timezone.utc).isoformat()

        state = {
            "jobId": job_id,
            "status": "running",
            "startedAt": now,
        }
        self._local_state[job_id] = state
        await set_job_state(job_id, state)

        task = asyncio.create_task(self._run_job(job_id, coro_fn))
        self._tasks[job_id] = task

        return job_id

    async def _run_job(
        self,
        job_id: str,
        coro_fn: Callable[[str], Coroutine[Any, Any, None]],
    ) -> None:
        try:
            await coro_fn(job_id)
            state = {
                "jobId": job_id,
                "status": "completed",
                "completedAt": datetime.now(timezone.utc).isoformat(),
            }
        except asyncio.CancelledError:
            state = {
                "jobId": job_id,
                "status": "cancelled",
            }
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            state = {
                "jobId": job_id,
                "status": "failed",
                "error": str(exc),
            }

        self._local_state[job_id] = state
        await set_job_state(job_id, state)

    async def cancel_job(self, job_id: str) -> dict[str, Any] | None:
        task = self._tasks.get(job_id)
        if task is None:
            return None

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        state = {
            "jobId": job_id,
            "status": "cancelled",
        }
        self._local_state[job_id] = state
        await set_job_state(job_id, state)
        return state

    async def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        local = self._local_state.get(job_id)
        if local:
            return local
        return await get_job_state(job_id)

    async def recover_stale_jobs(self) -> None:
        running_ids = await list_jobs_by_status("running")
        for job_id in running_ids:
            state = await get_job_state(job_id)
            if state:
                state["status"] = "failed"
                state["reason"] = "server restarted"
                await set_job_state(job_id, state)
                logger.info("Marked stale job %s as failed (server restarted)", job_id)
