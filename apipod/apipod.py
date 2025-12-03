from apipod.CONSTS import APIPOD_BACKEND, APIPOD_DEPLOYMENT
from apipod.settings import APIPOD_BACKEND, APIPOD_DEPLOYMENT
from apipod.core.routers._socaity_router import _SocaityRouter
from apipod.core.routers._runpod_router import SocaityRunpodRouter
from apipod.core.routers._fastapi_router import SocaityFastAPIRouter
from typing import Union


def APIPod(
        backend: Union[APIPOD_BACKEND, str, object] = APIPOD_BACKEND,
        deployment: Union[APIPOD_DEPLOYMENT, str] = APIPOD_DEPLOYMENT,
        *args, **kwargs
) -> Union[_SocaityRouter, SocaityRunpodRouter, SocaityFastAPIRouter]:
    """
    Initialize a _SocaityRouter with the appropriate backend running in the specified environment
    This function is a factory function that returns the appropriate app based on the backend and environment
    Args:
        backend: fastapi, runpod
        deployment: localhost, serverless
        host: The host to run the uvicorn host on.
        port: The port to run the uvicorn host on.
        *args:
        **kwargs:

    Returns: _SocaityRouter
    """
    if backend is None:
        backend = APIPOD_BACKEND

    if isinstance(backend, str):
        backend = APIPOD_BACKEND(backend)

    backend_class = SocaityFastAPIRouter
    if isinstance(backend, APIPOD_BACKEND):
        class_map = {
            APIPOD_BACKEND.FASTAPI: SocaityFastAPIRouter,
            APIPOD_BACKEND.RUNPOD: SocaityRunpodRouter
        }
        if backend not in class_map:
            raise Exception(f"Backend {backend.value} not found")
        backend_class = class_map[backend]

    if type(backend) in [SocaityFastAPIRouter, SocaityRunpodRouter]:
        backend_class = backend

    if deployment is None:
        deployment = APIPOD_DEPLOYMENT.LOCALHOST
    deployment = APIPOD_DEPLOYMENT(deployment) if type(deployment) is str else deployment

    print(f"Init apipod with backend {backend} in deployment mode {deployment} ")
    backend_instance = backend_class(deployment=deployment, *args, **kwargs)

    # ToDo: add default endpoints status, get_job here instead of the subclasses
    # app.add_route(path="/status")(app.get_status)
    # app.add_route(path="/job")(app.get_job)

    return backend_instance
