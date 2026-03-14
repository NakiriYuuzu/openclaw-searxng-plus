import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from gateway.job_manager import JobManager


@pytest.fixture
def manager():
    return JobManager(max_concurrent=3)


@pytest.mark.asyncio
class TestJobManager:
    async def test_create_job(self, manager):
        async def dummy_task(job_id: str):
            await asyncio.sleep(10)

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock):
            job_id = await manager.create_job(dummy_task)
            assert job_id.startswith("job_")

            state = manager.get_local_state(job_id)
            assert state is not None
            assert state["status"] == "running"

            # Cleanup
            await manager.cancel_job(job_id)

    async def test_cancel_job(self, manager):
        event = asyncio.Event()

        async def blocking_task(job_id: str):
            await event.wait()

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock):
            job_id = await manager.create_job(blocking_task)
            result = await manager.cancel_job(job_id)
            assert result["status"] == "cancelled"

    async def test_cancel_nonexistent_job(self, manager):
        result = await manager.cancel_job("job_nonexistent")
        assert result is None

    async def test_max_concurrent_limit(self, manager):
        events = []

        async def blocking_task(job_id: str):
            e = asyncio.Event()
            events.append(e)
            await e.wait()

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock):
            for _ in range(3):
                await manager.create_job(blocking_task)

            with pytest.raises(RuntimeError, match="concurrent"):
                await manager.create_job(blocking_task)

            # Cleanup
            for e in events:
                e.set()
            await asyncio.sleep(0.1)

    async def test_job_completes_successfully(self, manager):
        async def quick_task(job_id: str):
            pass  # completes immediately

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock) as mock_set:
            job_id = await manager.create_job(quick_task)
            await asyncio.sleep(0.1)  # let task complete

            # Should have been called with "completed" status
            calls = [c for c in mock_set.call_args_list if c[0][1].get("status") == "completed"]
            assert len(calls) > 0

    async def test_job_failure_recorded(self, manager):
        async def failing_task(job_id: str):
            raise ValueError("something broke")

        with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock) as mock_set:
            job_id = await manager.create_job(failing_task)
            await asyncio.sleep(0.1)

            calls = [c for c in mock_set.call_args_list if c[0][1].get("status") == "failed"]
            assert len(calls) > 0

    async def test_recover_marks_running_as_failed(self, manager):
        with patch("gateway.job_manager.list_jobs_by_status", new_callable=AsyncMock, return_value=["job_old1", "job_old2"]):
            with patch("gateway.job_manager.get_job_state", new_callable=AsyncMock, return_value={"jobId": "job_old1", "status": "running"}):
                with patch("gateway.job_manager.set_job_state", new_callable=AsyncMock) as mock_set:
                    await manager.recover_stale_jobs()
                    failed_calls = [
                        c for c in mock_set.call_args_list
                        if c[0][1].get("status") == "failed"
                        and c[0][1].get("reason") == "server restarted"
                    ]
                    assert len(failed_calls) >= 1
