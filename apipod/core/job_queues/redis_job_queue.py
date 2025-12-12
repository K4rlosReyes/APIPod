import pickle
from typing import Optional, Callable, TypeVar
from datetime import datetime


from apipod.core.job_queues.job_queue_interface import JobQueueInterface
from apipod.core.job.base_job import BaseJob, JOB_STATUS


T = TypeVar('T', bound=BaseJob)


class RedisJobQueue(JobQueueInterface[T]):
    """
    Redis-backed JobQueue implementation.
    Persists jobs to Redis and uses Redis Lists/Streams for queuing.
    """

    def __init__(self, redis_url: str, delete_orphan_jobs_after_s: int = 60 * 30):
        try:
            import redis
        except ImportError:
            raise ImportError("Redis is required to use RedisJobQueue. Install with 'pip install redis'.")

        self.redis = redis.from_url(redis_url)
        self.queue_prefix = "apipod:queue"
        self.job_prefix = "apipod:job"
        self._delete_orphan_jobs_after_seconds = delete_orphan_jobs_after_s
        self.queue_sizes = {}  # Cache queue sizes locally or in redis? For now locally.

    def set_queue_size(self, job_function: Callable, queue_size: int = 500) -> None:
        # We could store this in Redis to enforce limits across multiple API instances
        key = f"{self.queue_prefix}:limit:{job_function.__name__}"
        self.redis.set(key, queue_size)

    def _get_queue_size(self, func_name: str) -> int:
        key = f"{self.queue_prefix}:limit:{func_name}"
        val = self.redis.get(key)
        return int(val) if val else 500

    def add_job(self, job_function: Callable, job_params: Optional[dict] = None) -> T:
        # 1. Create BaseJob instance locally to get ID and initial state
        job = BaseJob(job_function=job_function, job_params=job_params)

        func_name = job_function.__name__

        # 2. Check Queue Limit (Distributed check)
        queue_key = f"{self.queue_prefix}:{func_name}"
        current_depth = self.redis.llen(queue_key)
        max_size = self._get_queue_size(func_name)

        if current_depth >= max_size:
            job.status = JOB_STATUS.FAILED
            job.error = f"Queue size limit reached for {func_name}"
            # Even failed jobs might need to be stored briefly or just returned
            return job

        # 3. Serialize Job
        # We need to serialize the function reference + params
        # For simplicity, we assume job_params are JSON serializable.
        # For the function, we store the name. The Worker must have the same function registry.
        
        job_data = {
            "id": job.id,
            "function_name": func_name,
            # "function_module": job_function.__module__, # Needed for dynamic import
            "params": pickle.dumps(job.job_params).hex(), # Pickle for safety with complex types, or JSON
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "queued_at": datetime.utcnow().isoformat(),
            "timeout_seconds": 3600  # Should probably come from config
        }

        # 4. Save to Redis
        job_key = f"{self.job_prefix}:{job.id}"
        pipe = self.redis.pipeline()
        pipe.hset(job_key, mapping=job_data)
        pipe.expire(job_key, 3600 * 24) # Auto-expire old jobs
        pipe.rpush(queue_key, job.id)
        pipe.execute()
        
        job.status = JOB_STATUS.QUEUED
        return job

    def get_job(self, job_id: str) -> Optional[T]:
        job_key = f"{self.job_prefix}:{job_id}"
        data = self.redis.hgetall(job_key)
        
        if not data:
            return None
            
        # Decode data
        data = {k.decode('utf-8'): v.decode('utf-8') for k, v in data.items()}
        
        # Reconstruct BaseJob
        # Note: We might not have the original function here if this is just checking status.
        # We pass a dummy function or try to import if needed.
        # For status checking, the function object isn't strictly necessary.
        
        def dummy_func(): pass
        dummy_func.__name__ = data.get("function_name", "unknown")
        
        params = pickle.loads(bytes.fromhex(data["params"])) if "params" in data else {}
        
        job = BaseJob(job_function=dummy_func, job_params=params)
        job.id = data["id"]
        job.status = JOB_STATUS(data["status"])
        job.result = data.get("result") # Result might be stored as string/json
        job.error = data.get("error")
        
        # Rehydrate timestamps
        if "created_at" in data: job.created_at = datetime.fromisoformat(data["created_at"])
        if "queued_at" in data: job.queued_at = datetime.fromisoformat(data["queued_at"])
        if "execution_started_at" in data: job.execution_started_at = datetime.fromisoformat(data["execution_started_at"])
        if "execution_finished_at" in data: job.execution_finished_at = datetime.fromisoformat(data["execution_finished_at"])
        
        # Progress (Requires checking separate key or stream if we want live progress)
        # For now, assume progress is stored in the hash
        progress_val = data.get("progress", 0.0)
        progress_msg = data.get("progress_msg", "")
        job.job_progress.set_status(float(progress_val), progress_msg)
        
        return job

    def cancel_job(self, job_id: str) -> None:
        # Publish cancel event or set status
        job_key = f"{self.job_prefix}:{job_id}"
        self.redis.hset(job_key, "status", JOB_STATUS.FAILED.value)
        self.redis.hset(job_key, "error", "Job cancelled")
        # If using a worker, we might need to publish to a control channel
        self.redis.publish("apipod:control", f"cancel:{job_id}")

    def shutdown(self) -> None:
        self.redis.close()

