import os
import toml
from typing import Dict, Any, Set
from .IDetector import Detector


class DependencyDetector(Detector):
    def detect(self) -> Dict[str, Any]:
        print("Scanning for system dependencies...")
        system_deps = {
            "gcc": False,  # note that we now always install gcc for reliability; this detection thus is obsolete
            "libturbojpg": False
        }

        found_python_deps = self._gather_python_dependencies()

        # Triggers for gcc
        gcc_triggers = {
            "tokenizers", "pyannote.audio", "faiss", "faiss-cpu", "faiss-gpu",
            "dlib", "mediapipe", "pytorch3d", "xformers", "mmcv", "pynvml"
        }

        # Triggers for libturbojpg
        turbojpg_triggers = {"pillow-simd", "jpeg4py", "turbojpeg"}

        for dep in found_python_deps:
            if dep in gcc_triggers:
                print(f"Found gcc trigger: {dep}")
                system_deps["gcc"] = True
            if dep in turbojpg_triggers:
                print(f"Found libturbojpg trigger: {dep}")
                system_deps["libturbojpg"] = True

        return system_deps

    def _gather_python_dependencies(self) -> Set[str]:
        deps = set()

        # 1. Check pyproject.toml
        pyproject_path = os.path.join(self.project_root, "pyproject.toml")
        if os.path.exists(pyproject_path):
            try:
                data = toml.load(pyproject_path)
                if "project" in data and "dependencies" in data["project"]:
                    for d in data["project"]["dependencies"]:
                        deps.add(self._extract_name(d))
                if "tool" in data and "poetry" in data["tool"] and "dependencies" in data["tool"]["poetry"]:
                    for d in data["tool"]["poetry"]["dependencies"].keys():
                        deps.add(d.lower())
            except Exception:
                pass

        # 2. Check requirements.txt
        requirements_path = os.path.join(self.project_root, "requirements.txt")
        if os.path.exists(requirements_path):
            try:
                with open(requirements_path, "r") as f:
                    for line in f:
                        if line.strip() and not line.startswith("#"):
                            deps.add(self._extract_name(line))
            except Exception:
                pass

        return deps

    def _extract_name(self, dependency_string: str) -> str:
        # Extract package name from requirement string (e.g. "numpy==1.21.0" -> "numpy")
        # Remove comments
        dependency_string = dependency_string.split('#')[0].strip()
        # Split by operators
        import re
        name = re.split(r'[=<>!~;]', dependency_string)[0].strip()
        return name.lower()
