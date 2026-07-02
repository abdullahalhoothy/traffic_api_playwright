import asyncio
import threading
import uuid
from multiprocessing import Process, Queue
from typing import Any, Dict, List, Optional

from config import logger
from traffic_worker import worker_entrypoint


class WorkerPool:
    def __init__(self, num_workers: int):
        self.num_workers = num_workers
        self.job_queue = Queue()
        self.result_queue = Queue()
        self.processes: List[Process] = []
        self._pending_jobs: Dict[str, asyncio.Future] = {}
        self._loop = None
        self._result_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()

        # Start workers
        for i in range(self.num_workers):
            self._spawn_worker(i)

        # Start result collection thread
        self._result_thread = threading.Thread(
            target=self._result_collector, daemon=True
        )
        self._result_thread.start()
        logger.info(f"🚀 WorkerPool started with {self.num_workers} workers")

    def _spawn_worker(self, index: int):
        p = Process(
            target=worker_entrypoint,
            args=(self.job_queue, self.result_queue),
            name=f"TrafficWorker-{index}",
            daemon=True,
        )
        p.start()
        if index < len(self.processes):
            self.processes[index] = p
        else:
            self.processes.append(p)

    def _result_collector(self):
        """
        Background thread that pulls results from the multiprocessing queue
        and resolves the corresponding asyncio Futures.
        """
        while not self._stop_event.is_set():
            try:
                result_data = self.result_queue.get(timeout=1.0)
                if result_data == "STOP":
                    break

                job_id, result = result_data
                if job_id in self._pending_jobs:
                    future = self._pending_jobs.pop(job_id)
                    if not future.done():
                        if self._loop is None:
                            self._loop = asyncio.get_running_loop()
                        self._loop.call_soon_threadsafe(future.set_result, result)
            except Exception:
                continue

    def stop(self):
        self._stop_event.set()
        for _ in range(self.num_workers):
            self.job_queue.put("STOP")

        if self._result_thread:
            self.result_queue.put("STOP")
            self._result_thread.join(timeout=5)

        for p in self.processes:
            if p.is_alive():
                p.terminate()
            p.join()

        logger.info("🛑 WorkerPool stopped")

    def dispatch(self, loc_dict: Dict[str, Any]) -> asyncio.Future:
        """
        Send a job to workers and return a future that will resolve with the result.
        """
        job_id = str(uuid.uuid4())

        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        future = self._loop.create_future()
        self._pending_jobs[job_id] = future

        self.job_queue.put((job_id, loc_dict))
        return future

    def check_health(self):
        """
        Check if processes are alive and restart if necessary.
        """
        for i, p in enumerate(self.processes):
            if not p.is_alive():
                logger.warning(f"⚠️ Worker process {p.name} died. Restarting...")
                self._spawn_worker(i)
