from pathlib import Path


def find_project_root(start_path: Path = None) -> Path:
    """Find the project root by searching for project markers with max depth limit."""
    start_path = Path(start_path) if start_path else Path.cwd()
    current = start_path.resolve()
    start_depth = len(current.parents)
    max_depth = 8
    # Define markers: (name, is_directory)
    markers = [
        ("apipod-deploy", True),    # folder
        ("pyproject.toml", False),  # file
        (".git", True),             # folder
        ("setup.cfg", False),       # file
        ("setup.py", False)         # file
    ]
    # Walk up the directory tree until we find project markers or hit max depth
    while current.parent != current:  # Stop at filesystem root
        # Check depth limit
        current_depth = len(current.parents)
        if start_depth - current_depth >= max_depth:
            break
        # Check for project markers
        for marker_name, is_directory in markers:
            marker_path = current / marker_name
            if is_directory and marker_path.is_dir():
                return current
            elif not is_directory and marker_path.is_file():
                return current
        current = current.parent
    # If no markers found within max depth, abort
    raise FileNotFoundError(
        f"Could not find project root within {max_depth} directory levels. "
        f"Expected one of: {', '.join(name for name, _ in markers)}"
    )
