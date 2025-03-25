import functools
import inspect
from types import UnionType
from typing import Any, Union, get_type_hints, get_args, get_origin, Callable, List, Optional
from fastapi import HTTPException, Body
from fast_task_api.compatibility.LimitedUploadFile import LimitedUploadFile
from fast_task_api.compatibility.upload import is_param_media_toolkit_file
from fast_task_api.core.job.job_result import FileModel, JobResult
from fast_task_api.core.routers.router_mixins._base_file_handling_mixin import _BaseFileHandlingMixin
from fast_task_api.core.utils import get_func_signature, replace_func_signature
from media_toolkit import media_from_any, MediaFile


class _fast_api_file_handling_mixin(_BaseFileHandlingMixin):
    """
    Handles file uploads and parameter conversions for FastTaskAPI.

    This mixin provides functionality to:
    1. Convert function parameters to request body parameters
    2. Handle file uploads from various sources (UploadFile, FileModel, Base64, URLs)
    3. Convert MediaFile responses to FileModel for API documentation
    """
    def create_limited_upload_file(self, max_size_mb: float):
        """
        Factory function to create a subclass of LimitedUploadFile with a predefined max_size_mb.
        Needs to be done in factory function, because creating it directly causes pydantic errors
        """
        max_size_mb = max_size_mb if max_size_mb is not None else self.max_upload_file_size_mb
        class LimitedUploadFileWithMaxSize(LimitedUploadFile):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, max_size=max_size_mb, **kwargs)

        return LimitedUploadFileWithMaxSize

    def _get_media_file_annotation(self, annotation: Any, max_upload_file_size_mb: float):
        """Converts MediaFile-like annotations into appropriate UploadFile types."""
        _limited_upload_file = self.create_limited_upload_file(max_upload_file_size_mb)

        # Handle Union or direct media file type
        if get_origin(annotation) in [Union, UnionType]:
            arg_types = get_args(annotation)
            if any(is_param_media_toolkit_file(arg) for arg in arg_types):
                non_media_file_types = tuple(t for t in arg_types if not is_param_media_toolkit_file(t))
                return Union[(_limited_upload_file, FileModel, str, *non_media_file_types)]
        elif is_param_media_toolkit_file(annotation):
            return Union[_limited_upload_file, FileModel, str]
        elif inspect.isclass(annotation) and issubclass(annotation, FileModel):
            return Union[_limited_upload_file, FileModel, str]
        elif get_origin(annotation) in (List, list):
            sub_type = get_args(annotation)[0]
            if is_param_media_toolkit_file(sub_type) or (
                    inspect.isclass(annotation) and issubclass(annotation, FileModel)):
                return List[Union[_limited_upload_file, FileModel, str]]

        return annotation

    def _convert_params_to_body(self, func: Callable, max_upload_file_size_mb: float = None) -> dict:
        """
        Moves all parameters to the request body.
        Replaces MediaFile parameters with UploadFile in the function signature.
        This allows the API to accept file uploads from the client.
        """
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)

        field_definitions = {}
        for name, param in sig.parameters.items():
            annotation = type_hints.get(name, Any)
            default = param.default if param.default != inspect.Parameter.empty else ...

            # Check if the parameter was originally Optional
            is_optional = get_origin(annotation) in {Union, UnionType} and type(None) in get_args(annotation)

            # Convert and check if was converted
            _file_annotation = self._get_media_file_annotation(annotation, max_upload_file_size_mb)
            is_file_parameter = annotation != _file_annotation
            annotation = _file_annotation

            # Move to body parameters
            if not is_file_parameter:
                field_definitions[name] = (annotation, Body(default=None if is_optional else default))
            else:
                if is_optional:
                    file_args = get_args(_file_annotation)
                    # adding str, and None to the union to allow empty strings, and none values
                    annotation = Union[(*file_args, None)]

                    field_definitions[name] = (annotation, default if default is not ... else None)
                else:
                    field_definitions[name] = (annotation, default)

        return field_definitions

    def _update_signature(self, func: Callable, max_upload_file_size_mb: float = None) -> Callable:
        params_model = self._convert_params_to_body(func, max_upload_file_size_mb)
        parameters = [
            inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=param_type, default=default)
            for name, (param_type, default) in params_model.items()
        ]
        replace_func_signature(func, inspect.Signature(parameters=parameters))
        return func

    def _prepare_func_for_media_file_upload_with_fastapi(self, func: callable, max_upload_file_size_mb: float = None) -> callable:
        """
        Prepare a function for FastAPI
        1. Removes job progress parameter from the function signature
        2. Adds file upload logic to convert parameters
        3. Replaces upload file parameters with FastAPI File type
        """
        # Remove job progress parameter
        no_job_progress = self._remove_job_progress_from_signature(func)

        # Add file upload conversion logic
        file_upload_modified = self._handle_file_uploads(no_job_progress)

        # Update signature with file upload parameters
        with_file_upload_signature = self._update_signature(file_upload_modified, max_upload_file_size_mb)

        return with_file_upload_signature

    def _remove_job_progress_from_signature(self, func: Callable) -> Callable:
        """
        Remove job_progress parameter from function signature for API docs.

        Args:
            func: Function to modify

        Returns:
            Function with updated signature
        """
        sig = get_func_signature(func)
        new_sig = sig.replace(parameters=[
            p for p in sig.parameters.values()
            if p.name != "job_progress" and "FastJobProgress" not in str(p.annotation)
        ])

        return replace_func_signature(func, new_sig)