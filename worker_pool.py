#!/usr/bin/python3

from multiprocessing import Process, Queue
from typing import Any, Dict, List

from traffic_worker import worker_entrypoint


class WorkerPool:
    def __init__(self, num_workers: int):
        self.num_workers = num_workers
        self.job_queue = Queue()
        self.result_queue = Queue()
        self.processes: List[Process] = []

    def start(self):
        for _ in range(self.num_workers):
            p = Process(
                target=worker_entrypoint,
                args=(self.job_queue, self.result_queue),
                daemon=True,
            )
            p.start()
            self.processes.append(p)

    def stop(self):
        for _ in range(self.num_workers):
            self.job_queue.put("STOP")

        for p in self.processes:
            p.join()

    def dispatch(self, idx: int, loc_dict: Dict[str, Any]):
        """
        Send one job to workers.
        """
        self.job_queue.put((idx, loc_dict))

    def get_result(self):
        """
        Blocking call — workers will push results here.
        """
        return self.result_queue.get()
