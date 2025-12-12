from apipod import CONSTS
from apipod.settings import APIPOD_BACKEND, APIPOD_DEPLOYMENT, APIPOD_QUEUE_BACKEND
from apipod.core.routers._socaity_router import _SocaityRouter
from apipod.core.routers._runpod_router import SocaityRunpodRouter
from apipod.core.routers._fastapi_router import SocaityFastAPIRouter
from apipod.core.job_queues.job_queue_interface import JobQueueInterface

from typing import Union
import os


def APIPod(
        backend: Union[CONSTS.APIPOD_BACKEND, str, object] = APIPOD_BACKEND,
        deployment: Union[CONSTS.APIPOD_DEPLOYMENT, str] = APIPOD_DEPLOYMENT,
        queue_backend: Union[CONSTS.APIPOD_QUEUE_BACKEND, str] = APIPOD_QUEUE_BACKEND,
        redis_url: str = None,
        *args, **kwargs
) -> Union[_SocaityRouter, SocaityRunpodRouter, SocaityFastAPIRouter]:
    """
    Initialize a _SocaityRouter with the appropriate backend running in the specified environment
    This function is a factory function that returns the appropriate app based on the backend and environment
    Args:
        backend: fastapi, runpod
        deployment: localhost, serverless
        queue_backend: "local" or "redis". Default is None (no queue).
        redis_url: URL for redis if queue_backend is redis. Defaults to env APIPOD_REDIS_URL
        host: The host to run the uvicorn host on.
        port: The port to run the uvicorn host on.
        *args:
        **kwargs:

    Returns: _SocaityRouter
    """

    backend_class = _get_backend_class(backend)
    job_queue = _get_queue_backend(queue_backend, backend_class, redis_url)

    deployment = _get_deployment_type(deployment)

    if backend_class == SocaityFastAPIRouter:
        backend_instance = backend_class(deployment=deployment, job_queue=job_queue, *args, **kwargs)
    else:
        backend_instance = backend_class(deployment=deployment, *args, **kwargs)

    return backend_instance


def _get_backend_class(backend: Union[CONSTS.APIPOD_BACKEND, str, object]) -> type:
    if backend is None:
        backend = APIPOD_BACKEND

    if isinstance(backend, str):
        backend = CONSTS.APIPOD_BACKEND(backend)

    backend_class = SocaityFastAPIRouter
    if isinstance(backend, CONSTS.APIPOD_BACKEND):
        class_map = {
            CONSTS.APIPOD_BACKEND.FASTAPI: SocaityFastAPIRouter,
            CONSTS.APIPOD_BACKEND.RUNPOD: SocaityRunpodRouter
        }
        if backend not in class_map:
            raise Exception(f"Backend {backend.value} not found")
        backend_class = class_map[backend]
    if type(backend) in [SocaityFastAPIRouter, SocaityRunpodRouter]:
        backend_class = backend

    return backend_class


def _get_deployment_type(deployment: Union[CONSTS.APIPOD_DEPLOYMENT, str]):
    if deployment is None:
        deployment = CONSTS.APIPOD_DEPLOYMENT.LOCALHOST
    deployment = CONSTS.APIPOD_DEPLOYMENT(deployment) if type(deployment) is str else deployment
    return deployment


def _get_queue_backend(queue_backend: str, backend_class: type, redis_url: str = None) -> JobQueueInterface:
    """
    Get the job queue backend for the given backend class and queue backend
    """
    if backend_class == SocaityRunpodRouter and queue_backend == CONSTS.APIPOD_QUEUE_BACKEND.REDIS:
        print("Runpod router does not support redis queue. Will use runpod platform mechanism instead.")
        return None

    # Determine Queue Backend
    if queue_backend is None:
        # Check env if passed param is None, but the param default comes from settings which reads env.
        # If settings is None, then it is None.
        pass

    # If explicitly None, return None (No queue)
    if not queue_backend:
        return None

    # Handle string input
    if isinstance(queue_backend, str):
        try:
            queue_backend = CONSTS.APIPOD_QUEUE_BACKEND(queue_backend)
        except ValueError:
            # Fallback or error?
            pass

    job_queue = None
    if queue_backend == CONSTS.APIPOD_QUEUE_BACKEND.REDIS:
        if redis_url is None:
            redis_url = os.environ.get("APIPOD_REDIS_URL")
        if not redis_url:
            raise ValueError("redis_url must be provided or set in APIPOD_REDIS_URL env var when using redis queue")
        print(f"Initializing Redis Job Queue with URL: {redis_url}")

        from apipod.core.job_queues.redis_job_queue import RedisJobQueue
        job_queue = RedisJobQueue(redis_url=redis_url)
    elif queue_backend == CONSTS.APIPOD_QUEUE_BACKEND.LOCAL:
        # Default to local
        from apipod.core.job_queues.job_queue import JobQueue
        job_queue = JobQueue()
    else:
        # Unknown or None
        return None

    return job_queue
