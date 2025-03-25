import functools
import inspect
from types import UnionType
from typing import Any, Union, get_type_hints, get_args, get_origin, Callable, List, Optional
from fastapi import HTTPException, Body
from fast_task_api.compatibility.LimitedUploadFile import LimitedUploadFile
from fast_task_api.compatibility.upload import is_param_media_toolkit_file
from fast_task_api.core.job.job_result import FileModel, JobResult
from fast_task_api.core.utils import get_func_signature, replace_func_signature
from media_toolkit import media_from_any, MediaFile


class _FileHandlingMixin:
    """
    Handles file uploads and parameter conversions for FastTaskAPI.

    This mixin provides functionality to:
    1. Convert function parameters to request body parameters
    2. Handle file uploads from various sources (UploadFile, FileModel, Base64, URLs)
    3. Convert MediaFile responses to FileModel for API documentation
    """

    def __init__(self, max_upload_file_size_mb: float = None, *args, **kwargs):
        """
        Initialize the FileHandlingMixin.

        Args:
            max_upload_file_size_mb: Default maximum file size in MB for uploads
        """
        self.max_upload_file_size_mb = max_upload_file_size_mb

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

        if get_origin(annotation) in [Union, UnionType]:
            arg_types = get_args(annotation)
            if any(is_param_media_toolkit_file(arg) for arg in arg_types):
                non_media_file_types = (t for t in arg_types if not is_param_media_toolkit_file(t))
                return Union[(_limited_upload_file, FileModel, *non_media_file_types)]
        elif is_param_media_toolkit_file(annotation):
            return Union[_limited_upload_file, FileModel, str]
        elif inspect.isclass(annotation) and issubclass(annotation, FileModel):
            return Union[_limited_upload_file, FileModel]
        elif get_origin(annotation) in (List, list):
            sub_type = get_args(annotation)[0]
            if is_param_media_toolkit_file(sub_type):
                return List[_limited_upload_file]

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

    def _handle_file_uploads(self, func: Callable) -> Callable:
        upload_param_types = {
            param.name: self._get_media_file_annotation(param.annotation, self.max_upload_file_size_mb)
            for param in get_func_signature(func).parameters.values()
        }

        @functools.wraps(func)
        def file_upload_wrapper(*args, **kwargs):
            param_names = list(upload_param_types.keys())
            nkwargs = {param_names[i]: arg for i, arg in enumerate(args) if i < len(param_names)}
            nkwargs.update(kwargs)

            files = {k: v for k, v in nkwargs.items() if k in upload_param_types}
            try:
                read_files = {
                    k: media_from_any(v, upload_param_types[k], use_temp_file=True, allow_reads_from_disk=False)
                    for k, v in files.items()}
            except Exception:
                raise HTTPException(400, "Error in file upload. Check file type and try again.")

            nkwargs.update(read_files)
            return func(**nkwargs)

        return file_upload_wrapper


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

    def _prepare_func_for_media_file_upload_with_fastapi(self, func: callable, max_upload_file_size_mb: float = None) -> callable:
        """
        Prepare a function
        Replaces the function signature by converting MediaFile parameters to UploadFile.
        This allows fastapi to accept file uploads from the client.
        Reads the files and adds them to the function arguments
        also removes the job progress parameter from the function signature
        """
        # PREPARE FUNCTION FOR FASTAPI
        # 1. remove the job progress parameter from the function signature
        no_job_progress = self._remove_job_progress_from_signature(func)

        # 2. Add the file upload logic to the function
        # Handle file uploads with original parameters to be able to convert to appropriate MediaFile types
        file_upload_modified = self._handle_file_uploads(no_job_progress)

        # 3. Replace upload file parameters, MediaFile, FileModel etc. with FastAPI File. Limit the file size
        with_file_upload_signature = self._update_signature(file_upload_modified, max_upload_file_size_mb)

        return with_file_upload_signature

