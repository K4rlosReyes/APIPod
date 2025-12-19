import functools
import inspect
import traceback
from datetime import datetime, timezone
from typing import Union, Callable, get_type_hints
import uuid
import time

from httpx import request

from pydantic import BaseModel

from apipod import CONSTS
from apipod.core.job.base_job import JOB_STATUS
from apipod.core.job.job_progress import JobProgressRunpod, JobProgress
from apipod.core.job.job_result import JobResultFactory, JobResult
from apipod.core.routers._socaity_router import _SocaityRouter
from apipod.core.routers.router_mixins._base_file_handling_mixin import _BaseFileHandlingMixin
from apipod.core.routers import schemas

from apipod.core.utils import normalize_name
from apipod.settings import APIPOD_DEPLOYMENT, APIPOD_PORT, DEFAULT_DATE_TIME_FORMAT


class SocaityRunpodRouter(_SocaityRouter, _BaseFileHandlingMixin):
    """
    Adds routing functionality for the runpod serverless framework.
    Provides enhanced file handling and conversion capabilities.
    """
    def __init__(self, title: str = "APIPod for ", summary: str = None, *args, **kwargs):
        super().__init__(title=title, summary=summary, *args, **kwargs)
        self.routes = {}  # routes are organized like {"ROUTE_NAME": "ROUTE_FUNCTION"}

        self.add_standard_routes()

    def add_standard_routes(self):
        self.endpoint(path="openapi.json")(self.get_openapi_schema)


    def endpoint(self, path: str = None, *args, **kwargs):
        """
        Adds an endpoint route to the app for serverless execution.
        """
        path = normalize_name(path, preserve_paths=True)
        if len(path) > 0 and path[0] == "/":
            path = path[1:]

        # Map Request Models to (Response Model, Type String) for "Smart Responses"
        model_map = {
            schemas.ChatCompletionRequest: (schemas.ChatCompletionResponse, "chat"),
            schemas.CompletionRequest: (schemas.CompletionResponse, "completion"),
            schemas.EmbeddingRequest: (schemas.EmbeddingResponse, "embedding"),
        }

        def decorator(func):
            # 1. Inspect function to find Pydantic models safely
            try:
                type_hints = get_type_hints(func)
            except Exception:
                type_hints = {}

            sig = inspect.signature(func)
            request_model = None
            response_model = None
            endpoint_type_str = None
            target_param_name = None 

            for name, param in sig.parameters.items():
                ann = type_hints.get(name, param.annotation)
                
                if inspect.isclass(ann) and issubclass(ann, BaseModel):
                    request_model = ann
                    target_param_name = name
                    
                    if ann in model_map:
                        response_model, endpoint_type_str = model_map[ann]
                    break

            @functools.wraps(func)
            def wrapper(*wrapped_args, **wrapped_kwargs):
                self.status = CONSTS.SERVER_HEALTH.BUSY
                
                # --- A. Input Processing (Map Dict -> Pydantic Object) ---
                openai_req = None
                final_kwargs = wrapped_kwargs.copy()

                if request_model and target_param_name:
                    try:
                        # CASE 1: Explicit Argument Provided (e.g. input={"payload": {...}})
                        if target_param_name in wrapped_kwargs:
                            val = wrapped_kwargs[target_param_name]
                            if isinstance(val, dict):
                                openai_req = request_model.model_validate(val)
                                final_kwargs[target_param_name] = openai_req
                        
                        # CASE 2: Flat/Implicit Arguments (e.g. input={"model": "...", "messages": ...})
                        else:
                            openai_req = request_model.model_validate(wrapped_kwargs)
                            final_kwargs[target_param_name] = openai_req
                            
                            # Cleanup raw fields only for implicit case
                            cleaned_kwargs = {}
                            for k, v in final_kwargs.items():
                                if k in sig.parameters:
                                    cleaned_kwargs[k] = v
                            final_kwargs = cleaned_kwargs
                        
                    except Exception as e:
                        # If validation fails, we proceed with raw kwargs.
                        pass

                # --- B. Execution (Sync or Async) ---
                try:
                    if inspect.iscoroutinefunction(func):
                        # Handle Async Function in Sync Context
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        if loop.is_running():
                             future = asyncio.run_coroutine_threadsafe(func(*wrapped_args, **final_kwargs), loop)
                             result = future.result()
                        else:
                             result = loop.run_until_complete(func(*wrapped_args, **final_kwargs))
                    else:
                        # Standard Sync Call
                        result = func(*wrapped_args, **final_kwargs)
                finally:
                    self.status = CONSTS.SERVER_HEALTH.RUNNING

                # --- C. Response Wrapping (Smart Logic) ---
                if response_model and endpoint_type_str:
                    timestamp = int(time.time())
                    model_name = getattr(openai_req, "model", "unknown") if openai_req else "unknown"

                    if isinstance(result, response_model):
                        return result

                    # Convert Dictionary to Object
                    if isinstance(result, dict):
                        if "choices" in result:
                            return response_model(
                                id=result.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
                                object=result.get("object", "chat.completion"),
                                created=result.get("created", timestamp),
                                model=result.get("model", model_name),
                                choices=result["choices"],
                                usage=result.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                            )
                        elif "data" in result and endpoint_type_str == "embedding":
                            return response_model(
                                object=result.get("object", "list"),
                                data=result["data"],
                                model=result.get("model", model_name),
                                usage=result.get("usage", {"prompt_tokens": 0, "total_tokens": 0})
                            )
                        try:
                            return response_model.model_validate(result)
                        except: pass

                    # Fallback wrapping (Raw Content)
                    if endpoint_type_str == "chat":
                        content = result
                        if isinstance(result, dict):
                            content = result.get("content", result.get("message", str(result)))
                        
                        return response_model(
                            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            object="chat.completion",
                            created=timestamp,
                            model=model_name,
                            choices=[{
                                "index": 0,
                                "message": {"role": "assistant", "content": str(content)},
                                "finish_reason": "stop"
                            }],
                            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                        )
                    
                    elif endpoint_type_str == "embedding":
                        embedding = result
                        if isinstance(result, dict):
                            embedding = result.get("embedding")
                        
                        if isinstance(embedding, list):
                            return response_model(
                                object="list",
                                data=[{
                                    "object": "embedding",
                                    "embedding": embedding,
                                    "index": 0
                                }],
                                model=model_name,
                                usage={"prompt_tokens": 0, "total_tokens": 0}
                            )

                return result

            self.routes[path] = wrapper
            return wrapper

        return decorator

    def get(self, path: str = None, *args, **kwargs):
        return self.endpoint(path=path, *args, **kwargs)

    def post(self, path: str = None, *args, **kwargs):
        return self.endpoint(path=path, *args, **kwargs)

    def _add_job_progress_to_kwargs(self, func, job, kwargs):
        """
        Add job_progress parameter to function arguments if necessary.

        Args:
            func: Original function
            job: Runpod job
            kwargs: Current function arguments

        Returns:
            Updated kwargs with job_progress added
        """
        job_progress_params = []
        for param in inspect.signature(func).parameters.values():
            if param.annotation in (JobProgress, JobProgressRunpod) or param.name == "job_progress":
                job_progress_params.append(param.name)

        if job_progress_params:
            jp = JobProgressRunpod(job)
            for job_progress_param in job_progress_params:
                kwargs[job_progress_param] = jp

        return kwargs

    def _router(self, path, job, **kwargs):
        """
        Internal app function that routes the path to the correct function.

        Args:
            path: Route path
            job: Runpod job
            kwargs: Function arguments

        Returns:
            JSON-encoded job result
        """
        if not isinstance(path, str):
            raise Exception("Path must be a string")

        path = normalize_name(path, preserve_paths=True)
        path = path.strip("/")

        route_function = self.routes.get(path, None)
        if route_function is None:
            raise Exception(f"Route {path} not found")

        # Add job progress to kwargs if necessary
        kwargs = self._add_job_progress_to_kwargs(route_function, job, kwargs)

        # Check for missing arguments
        sig = inspect.signature(route_function)
        missing_args = [arg for arg in sig.parameters if arg not in kwargs]
        if missing_args:
            raise Exception(f"Arguments {missing_args} are missing")

        # Handle file uploads and conversions
        route_function = self._handle_file_uploads(route_function)

        # Prepare result tracking
        start_time = datetime.now(timezone.utc)
        # result = JobResultFactory.from_base_job(job)
        result = JobResult(id=job['id'], execution_started_at=start_time.strftime("%Y-%m-%dT%H:%M:%S.%f%z"))

        try:
            # Execute the function (Sync or Async Handling)
            # Since route_function might have been wrapped by _handle_file_uploads (which can be async)
            # OR wrapped by endpoint (which handles its own async logic inside 'wrapper')
            
            if inspect.iscoroutinefunction(route_function):
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop.is_running():
                    # If we are somehow inside a loop, we must use threadsafe execution or await if this function was async
                    # But _router is Sync.
                     future = asyncio.run_coroutine_threadsafe(route_function(**kwargs), loop)
                     res = future.result()
                else:
                     res = loop.run_until_complete(route_function(**kwargs))
            else:
                res = route_function(**kwargs)

            # Convert result to JSON if it's a MediaFile / MediaList / Pydantic Model
            res = JobResultFactory._serialize_result(res)

            result.result = res
            result.status = JOB_STATUS.FINISHED.value
        except Exception as e:
            result.error = str(e)
            result.status = JOB_STATUS.FAILED.value
            print(f"Job {job['id']} failed: {str(e)}")
            traceback.print_exc()
        finally:
            result.execution_finished_at = datetime.now(timezone.utc).strftime(DEFAULT_DATE_TIME_FORMAT)

        result = result.model_dump_json()
        return result

    def handler(self, job):
        """
        The handler function that is called by the runpod serverless framework.
        We wrap it to provide internal routing in the serverless framework.
        Args:
            job: the job that is passed by the runpod serverless framework. Must include "path" in the input.
        Returns: the result of the path function.
        """
        inputs = job["input"]
        if "path" not in inputs:
            raise Exception("No path provided")

        route = inputs["path"]
        del inputs["path"]

        return self._router(route, job, **inputs)

    def start_runpod_serverless_localhost(self, port):
        # add the -rp_serve_api to the command line arguments to allow debugging
        import sys
        sys.argv.append("--rp_serve_api")
        sys.argv.extend(["--rp_api_port", str(port)])

        # overwrite runpod variables. Little hacky but runpod does not expose the variables in a nice way.
        import runpod.serverless
        from runpod.serverless.modules import rp_fastapi
        rp_fastapi.TITLE = self.title + " " + rp_fastapi.TITLE
        rp_fastapi.DESCRIPTION = self.summary + " " + rp_fastapi.DESCRIPTION
        desc = '''\
                        In input declare your path as route for the function. Other parameters follow in the input as usual.
                        The APIPod app will use the path argument to route to the correct function declared with
                        @endpoint(path="your_path").
                        { "input": { "path": "your_path", "your_other_args": "your_other_args" } }
                    '''
        rp_fastapi.RUN_DESCRIPTION = desc + "\n" + rp_fastapi.RUN_DESCRIPTION

        # hack to print version also in runpod
        version = self.version

        class WorkerAPIWithModifiedInfo(rp_fastapi.WorkerAPI):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._orig_openapi_func = self.rp_app.openapi
                self.rp_app.openapi = self.custom_openapi

            def custom_openapi(self):
                if not self.rp_app.openapi_schema:
                    self._orig_openapi_func()
                self.rp_app.openapi_schema["info"]["apipod"] = version
                self.rp_app.openapi_schema["info"]["runpod"] = rp_fastapi.runpod_version
                return self.rp_app.openapi_schema

        rp_fastapi.WorkerAPI = WorkerAPIWithModifiedInfo

        runpod.serverless.start({"handler": self.handler})

    def _create_openapi_compatible_function(self, func: Callable) -> Callable:
        """
        Create a function compatible with FastAPI OpenAPI generation by applying 
        the same conversion logic as the FastAPI mixin, but without runtime dependencies.

        This generates the rich schema with proper file upload handling.

        Args:
            func: Original function to convert
            max_upload_file_size_mb: Maximum file size in MB

        Returns:
            Function with FastAPI-compatible signature for OpenAPI generation
        """
        # Import FastAPI-specific conversion logic
        from apipod.core.routers.router_mixins._fast_api_file_handling_mixin import _fast_api_file_handling_mixin
        from apipod.core.job.job_result import JobResult
        import inspect
        from apipod.core.utils import replace_func_signature
        # Create a temporary instance of the FastAPI mixin to use its conversion methods
        temp_mixin = _fast_api_file_handling_mixin(max_upload_file_size_mb=5)
        # Apply the same preparation logic as FastAPI router
        with_file_upload_signature = temp_mixin._prepare_func_for_media_file_upload_with_fastapi(func, 5)
        # 4. Set proper return type for job-based endpoints

        sig = inspect.signature(with_file_upload_signature)
        job_result_sig = sig.replace(return_annotation=JobResult)
        # Update the signature

        final_func = replace_func_signature(with_file_upload_signature, job_result_sig)
        return final_func

    def get_openapi_schema(self):
        from fastapi.openapi.utils import get_openapi
        from fastapi.routing import APIRoute

        fastapi_routes = []
        for path, func in self.routes.items():
            # Create FastAPI-compatible function for rich OpenAPI generation
            try:
                compatible_func = self._create_openapi_compatible_function(func)
                fastapi_routes.append(APIRoute(
                    path=f"/{path.strip('/')}", 
                    endpoint=compatible_func, 
                    methods=["POST"]
                ))
            except Exception as e:
                print(f"Error creating OpenAPI compatible function for {path}: {e}")
                # Fallback to safe function approach
                try:
                    safe_func = self._create_openapi_safe_function(func)
                    fastapi_routes.append(APIRoute(
                        path=f"/{path.strip('/')}",
                        endpoint=safe_func,
                        methods=["POST"],
                        response_model=None
                    ))
                except Exception as e2:
                    print(f"Error creating safe function for {path}: {e2}")
                    # Ultimate fallback - create minimal route

                    def minimal_func():
                        return {"message": "Documentation not available"}

                    fastapi_routes.append(APIRoute(
                        path=f"/{path.strip('/')}",
                        endpoint=minimal_func,
                        methods=["POST"],
                        response_model=None
                    ))

        # Generate the OpenAPI schema dict (similar to FastAPI openapi())
        schema = get_openapi(
            title=self.title,
            version="1.0.0",
            routes=fastapi_routes,
            summary=self.summary,
            description=self.summary,
        )

        # Add APIPod version information like the FastAPI router
        schema["info"]["apipod"] = self.version

        return schema

    def start(self, deployment: Union[CONSTS.APIPOD_DEPLOYMENT, str] = APIPOD_DEPLOYMENT, port: int = APIPOD_PORT, *args, **kwargs):
        if type(deployment) is str:
            deployment = APIPOD_DEPLOYMENT(deployment)

        if deployment == deployment.LOCALHOST:
            self.start_runpod_serverless_localhost(port=port)
        elif deployment == deployment.SERVERLESS:
            import runpod.serverless
            runpod.serverless.start({"handler": self.handler})
        else:
            raise Exception(f"Not implemented for environment {deployment}")
