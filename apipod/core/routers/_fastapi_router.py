import functools
import inspect
from typing import Union, Callable
from fastapi import APIRouter, FastAPI, Response

from apipod.settings import APIPOD_PORT, APIPOD_HOST, SERVER_DOMAIN
from apipod.CONSTS import SERVER_HEALTH
from apipod.core.job.job_result import JobResultFactory, JobResult
from apipod.core.routers._socaity_router import _SocaityRouter
from apipod.core.routers.router_mixins._queue_mixin import _QueueMixin
from apipod.core.routers.router_mixins._fast_api_file_handling_mixin import _fast_api_file_handling_mixin
from apipod.core.utils import normalize_name
from apipod.core.routers.router_mixins._fast_api_exception_handling import _FastAPIExceptionHandler


class SocaityFastAPIRouter(APIRouter, _SocaityRouter, _QueueMixin, _fast_api_file_handling_mixin, _FastAPIExceptionHandler):
    """
    FastAPI router extension that adds support for task endpoints.

    Task endpoints run as jobs in the background and return job information
    that can be polled for status and results.
    """

    def __init__(
            self,
            title: str = "APIPod",
            summary: str = "Create web-APIs for long-running tasks",
            app: Union[FastAPI, None] = None,
            prefix: str = "",  # "/api",
            max_upload_file_size_mb: float = None,
            job_queue=None,
            *args,
            **kwargs):
        """
        Initialize the SocaityFastAPIRouter.

        Args:
            title: The title of the app
            summary: The summary of the app
            app: Existing FastAPI app to use (optional)
            prefix: The API route prefix
            max_upload_file_size_mb: Maximum file size in MB for uploads
            job_queue: Optional custom JobQueue implementation
            args: Additional arguments
            kwargs: Additional keyword arguments
        """
        # Initialize parent classes
        api_router_params = inspect.signature(APIRouter.__init__).parameters
        api_router_kwargs = {k: kwargs.get(k) for k in api_router_params if k in kwargs}

        APIRouter.__init__(self, **api_router_kwargs)
        _SocaityRouter.__init__(self, title=title, summary=summary, *args, **kwargs)
        _QueueMixin.__init__(self, job_queue=job_queue, *args, **kwargs)
        _fast_api_file_handling_mixin.__init__(self, max_upload_file_size_mb=max_upload_file_size_mb, *args, **kwargs)

        # Create job queue (already handled in _QueueMixin if passed, otherwise default)
        # self.job_queue = JobQueue() # REMOVED as it is set in _QueueMixin
        self.status = SERVER_HEALTH.INITIALIZING

        # Create or use provided FastAPI app
        if app is None:
            app = FastAPI(
                title=self.title,
                summary=self.summary,
                contact={"name": "SocAIty", "url": "https://www.socaity.ai"}
            )

        self.app: FastAPI = app
        self.prefix = prefix
        self.add_standard_routes()

        # excpetion handling
        _FastAPIExceptionHandler.__init__(self, *args, **kwargs)
        if not getattr(self.app.state, "_socaity_exception_handler_added", False):
            self.app.add_exception_handler(Exception, self.global_exception_handler)
            self.app.state._socaity_exception_handler_added = True

        # Save original OpenAPI function and replace it
        self._orig_openapi_func = self.app.openapi
        self.app.openapi = self.custom_openapi

    def add_standard_routes(self):
        """Add standard API routes for status and health checks."""
        self.api_route(path="/status", methods=["POST"])(self.get_job)
        self.api_route(path="/health", methods=["GET"])(self.get_health)

    def get_health(self) -> Response:
        """
        Get server health status.

        Returns:
            HTTP response with health status
        """
        stat, message = self._health_check.get_health_response()
        return Response(status_code=stat, content=message)

    def custom_openapi(self):
        """
        Customize OpenAPI schema with APIPod version information.

        Returns:
            Modified OpenAPI schema
        """
        if not self.app.openapi_schema:
            self._orig_openapi_func()

        self.app.openapi_schema["info"]["apipod"] = self.version
        return self.app.openapi_schema

    def get_job(self, job_id: str, return_format: str = 'json') -> JobResult:
        """
        Get the status and result of a job.

        Args:
            job_id: The ID of the job
            return_format: Response format ('json' or 'gzipped')

        Returns:
            JobResult with status and results
        """
        # sometimes job-id is inserted with leading " or other unwanted symbols. Remove those.
        job_id = job_id.strip().strip("\"").strip("\'").strip('?').strip("#")

        base_job = self.job_queue.get_job(job_id)
        if base_job is None:
            return JobResultFactory.job_not_found(job_id)

        ret_job = JobResultFactory.from_base_job(base_job)
        ret_job.refresh_job_url = f"{SERVER_DOMAIN}/status?job_id={ret_job.id}"
        ret_job.cancel_job_url = f"{SERVER_DOMAIN}/cancel?job_id={ret_job.id}"

        if return_format != 'json':
            ret_job = JobResultFactory.gzip_job_result(ret_job)

        return ret_job

    @functools.wraps(APIRouter.api_route)
    def endpoint(self, path: str, methods: list[str] = None, max_upload_file_size_mb: int = None, *args, **kwargs):
        """
        Endpoint with file upload support; without job queue functionality.
        """
        # normalize path
        path = normalize_name(path, preserve_paths=True)
        if len(path) > 0 and path[0] != "/":
            path = "/" + path

        # FastAPI route decorator
        fastapi_route_decorator = self.api_route(
            path=path,
            methods=["POST"] if methods is None else methods,
            *args,
            **kwargs
        )

        def file_result_modification_decorator(func: Callable) -> Callable:
            """Wrap endpoint result and serialize it."""
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                return JobResultFactory._serialize_result(result)
            return sync_wrapper

        def decorator(func: Callable) -> Callable:
            result_modified = file_result_modification_decorator(func)
            with_file_upload_signature = self._prepare_func_for_media_file_upload_with_fastapi(result_modified, max_upload_file_size_mb)
            return fastapi_route_decorator(with_file_upload_signature)

        return decorator

    def task_endpoint(
            self,
            path: str,
            queue_size: int = 500,
            methods: list[str] = None,
            max_upload_file_size_mb: int = None,
            *args,
            **kwargs
    ):
        """
        Create a task endpoint that runs as a background job.

        Args:
            path: API endpoint path
            queue_size: Maximum job queue size
            methods: HTTP methods (default: ["POST"])
            max_upload_file_size_mb: Maximum file size in MB
            args: Additional arguments
            kwargs: Additional keyword arguments

        Returns:
            Decorator function for endpoint
        """
        path = normalize_name(path, preserve_paths=True)
        if len(path) > 0 and path[0] != "/":
            path = "/" + path

        # FastAPI route decorator
        fastapi_route_decorator = self.api_route(
            path=path,
            methods=["POST"] if methods is None else methods,
            response_model=JobResult,
            *args,
            **kwargs
        )

        # Queue decorator
        queue_decorator = super().job_queue_func(
            path=path,
            queue_size=queue_size,
            *args,
            **kwargs
        )

        def decorator(func: Callable) -> Callable:
            # Add job queue functionality. Also function will get return type JobResult
            queue_decorated = queue_decorator(func)

            # PREPARE FUNCTION FOR FASTAPI
            # converts MediaFile parameters to UploadFile, reads the files and adds them to the function arguments
            # also removes the job progress parameter from the function signature
            upload_enabled = self._prepare_func_for_media_file_upload_with_fastapi(queue_decorated, max_upload_file_size_mb)

            # Add route to FastAPI
            return fastapi_route_decorator(upload_enabled)

        return decorator

    def get(self, path: str = None, queue_size: int = 100, *args, **kwargs):
        """
        Create a GET task endpoint.

        Args:
            path: API endpoint path
            queue_size: Maximum job queue size
            args: Additional arguments
            kwargs: Additional keyword arguments

        Returns:
            Task endpoint decorator
        """
        return self.task_endpoint(path=path, queue_size=queue_size, methods=["GET"], *args, **kwargs)

    def post(self, path: str = None, queue_size: int = 100, *args, **kwargs):
        """
        Create a POST task endpoint.

        Args:
            path: API endpoint path
            queue_size: Maximum job queue size
            args: Additional arguments
            kwargs: Additional keyword arguments

        Returns:
            Task endpoint decorator
        """
        return self.task_endpoint(path=path, queue_size=queue_size, methods=["POST"], *args, **kwargs)

    def start(self, port: int = APIPOD_PORT, host: str = APIPOD_HOST, *args, **kwargs):
        """
        Start the FastAPI server.

        Args:
            port: Server port
            host: Server host
            args: Additional arguments
            kwargs: Additional keyword arguments
        """
        # Create app if not provided
        if self.app is None:
            self.app = FastAPI()

        # Include this router in the app
        self.app.include_router(self)

        # Print help information
        print_host = "localhost" if host == "0.0.0.0" or host is None else host
        print(
            f"APIPod {self.app.title} started. Use http://{print_host}:{port}/docs to see the API documentation.")

        # Start server
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)
