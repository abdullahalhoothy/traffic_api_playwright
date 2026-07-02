import asyncio
import os
import sys

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from worker_pool import WorkerPool


# Mock worker entrypoint for testing
async def mock_worker_loop(job_queue, result_queue):
    while True:
        try:
            job = job_queue.get()
            if job == "STOP":
                break
            job_id, data = job
            # Simulate processing time
            await asyncio.sleep(data.get("delay", 0.1))
            result_queue.put((job_id, {"ok": True, "data": data["val"]}))
        except Exception:
            break


def mock_worker_entrypoint(job_queue, result_queue):
    asyncio.run(mock_worker_loop(job_queue, result_queue))


# Override the worker_entrypoint in the pool for this test
import worker_pool

worker_pool.worker_entrypoint = mock_worker_entrypoint


async def test_concurrency():
    print("🧪 Starting WorkerPool concurrency test...")
    pool = WorkerPool(num_workers=2)

    # We need a dummy loop for start()
    pool.start()

    try:
        # Launch multiple jobs concurrently
        tasks = []
        for i in range(10):
            # Interleave delays to ensure jobs finish out of order
            delay = 0.5 if i % 2 == 0 else 0.1
            print(f"  Dispatching job {i} with value {i*10} and delay {delay}s")
            fut = pool.dispatch({"val": i * 10, "delay": delay})
            tasks.append((i, i * 10, fut))

        # Verify results match
        success = True
        for i, expected_val, fut in tasks:
            res = await fut
            if res["data"] == expected_val:
                print(f"  ✅ Result for job {i} matches correctly: {res['data']}")
            else:
                print(
                    f"  ❌ Result for job {i} MISMATCH! Expected {expected_val}, got {res['data']}"
                )
                success = False

        if success:
            print(
                "\n🎉 Verification SUCCESS: No cross-talk detected! Job correlation is working perfectly."
            )
        else:
            print("\n🚨 Verification FAILED: Result mix-up detected.")

    finally:
        pool.stop()


if __name__ == "__main__":
    asyncio.run(test_concurrency())
