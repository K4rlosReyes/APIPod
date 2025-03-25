import functools
import inspect
from types import UnionType
from typing import Any, Union, get_type_hints, get_args, get_origin, Callable, List, Optional, Type

from fast_task_api.core.job.job_result import FileModel
from media_toolkit import media_from_any, MediaFile
from fast_task_api.compatibility.upload import is_param_media_toolkit_file


class _BaseFileHandlingMixin:
    """
    Base mixin for handling file uploads and parameter conversions across different deployment environments.

    Provides core functionality for:
    1. Identifying media-related parameters
    2. Supporting complex parameter types including optional and list parameters
    3. Flexible file conversion strategies
    """

    def __init__(self, max_upload_file_size_mb: float = None, *args, **kwargs):
        """
        Initialize the FileHandlingMixin.

        Args:
            max_upload_file_size_mb: Default maximum file size in MB for uploads
        """
        self.max_upload_file_size_mb = max_upload_file_size_mb

    def _is_media_param(self, annotation: Any) -> bool:
        """
        Determine if a parameter is a media-related type.

        Args:
            annotation: Type annotation to check

        Returns:
            bool: True if the parameter is a media-related type
        """
        # Check for Union/UnionType with media file types
        if get_origin(annotation) in [Union, UnionType, List, list]:
            return any(is_param_media_toolkit_file(arg) for arg in get_args(annotation))

        # Direct media file type check
        return is_param_media_toolkit_file(annotation)

    def _get_media_target_type(self, annotation: Any) -> Type:
        """
        Determine the most appropriate MediaFile type for conversion.

        Args:
            annotation: Type annotation to extract media type from

        Returns:
            Type: Target MediaFile type
        """
        # Handle Union/UnionType with multiple types
        org_annotation = get_origin(annotation)
        if org_annotation in [Union, UnionType, List, list]:
            media_file_types = [t for t in get_args(annotation) if is_param_media_toolkit_file(t)]
            return media_file_types[0] if media_file_types else MediaFile

        # Direct media file type
        return annotation if is_param_media_toolkit_file(annotation) else MediaFile

    def _convert_param_to_media_file(self, param_value: Any, annotation: Any) -> Any:
        """
        Convert a parameter to the appropriate MediaFile type.

        Args:
            param_value: Value to convert
            annotation: Type annotation guiding conversion

        Returns:
            Converted MediaFile or original value
        """
        # Handle list inputs
        if isinstance(param_value, list):
            return [self._convert_single_param(val, annotation) for val in param_value]

        return self._convert_single_param(param_value, annotation)

    def _convert_single_param(self, param_value: Any, annotation: Any) -> Any:
        """
        Convert a single parameter to MediaFile, with fallback mechanisms.

        Args:
            param_value: Value to convert
            annotation: Type annotation guiding conversion

        Returns:
            Converted MediaFile or original value
        """
        # Skip conversion if not a media-related parameter
        if not self._is_media_param(annotation):
            return param_value

        try:
            # Determine target type for conversion
            target_type = self._get_media_target_type(annotation)

            # Attempt conversion
            return media_from_any(
                param_value,
                target_type,
                use_temp_file=True,
                allow_reads_from_disk=False
            )
        except Exception as e:
            # If strict conversion fails and it's a Union type, return original
            if get_origin(annotation) in [Union, UnionType]:
                return param_value

            # If conversion fails for a specific type, raise an error
            raise ValueError(f"Invalid upload file format: {str(e)}")

    def _get_media_params(self, func: Callable) -> dict:
        """
        Identify media-related parameters in a function.

        Args:
            func: Function to analyze

        Returns:
            dict: Media parameters with their original type annotations
        """
        type_hints = get_type_hints(func)
        return {
            param_name: type_hint
            for param_name, type_hint in type_hints.items()
            if self._is_media_param(type_hint)
        }

    def _handle_file_uploads(self, func: Callable) -> Callable:
        """
        Wrap a function to handle file uploads and conversions.

        Args:
            func: Original function to wrap

        Returns:
            Wrapped function with file conversion logic
        """
        media_params = self._get_media_params(func)

        @functools.wraps(func)
        def file_upload_wrapper(*args, **kwargs):
            # Map positional arguments to parameter names
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            named_args = {param_names[i]: arg for i, arg in enumerate(args) if i < len(param_names)}
            named_args.update(kwargs)

            # Convert media-related parameters
            processed_files = {
                param_name: self._convert_param_to_media_file(param_value, media_params[param_name])
                for param_name, param_value in named_args.items()
                if param_name in media_params
            }

            # Update arguments with converted files
            named_args.update(processed_files)
            return func(**named_args)

        return file_upload_wrapper