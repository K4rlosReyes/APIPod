import os
import ast
import re
from typing import Optional, Dict, List, Any
import toml


class ConfigDetector:
    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    def detect_runtime(self) -> Dict[str, Any]:
        """
        Detects the runtime requirements (pytorch, tensorflow, onnx, python version).
        Returns a dictionary with detected technologies and versions.
        """
        config = {
            "pytorch": False,
            "tensorflow": False,
            "onnx": False,
            "cuda": False,
            "python_version": "3.10"  # Default
        }

        # Check pyproject.toml
        pyproject_path = os.path.join(self.project_root, "pyproject.toml")
        if os.path.exists(pyproject_path):
            try:
                data = toml.load(pyproject_path)
                dependencies = []
                # Check standard location
                if "project" in data and "dependencies" in data["project"]:
                    dependencies.extend(data["project"]["dependencies"])
                # Check poetry
                if "tool" in data and "poetry" in data["tool"] and "dependencies" in data["tool"]["poetry"]:
                    dependencies.extend(data["tool"]["poetry"]["dependencies"].keys())

                self._parse_dependencies(dependencies, config)

                # Check python version in requires-python
                if "project" in data and "requires-python" in data["project"]:
                    ver = data["project"]["requires-python"]
                    match = re.search(r'3\.(\d+)', ver)
                    if match:
                        config["python_version"] = f"3.{match.group(1)}"

            except Exception as e:
                print(f"Warning: Error parsing pyproject.toml: {e}")

        # Check requirements.txt if not fully detected
        requirements_path = os.path.join(self.project_root, "requirements.txt")
        if os.path.exists(requirements_path) and not (config["pytorch"] or config["tensorflow"]):
            try:
                with open(requirements_path, "r") as f:
                    dependencies = f.readlines()
                self._parse_dependencies(dependencies, config)
            except Exception as e:
                print(f"Warning: Error parsing requirements.txt: {e}")

        # Fallback: Import detection
        if not (config["pytorch"] or config["tensorflow"] or config["onnx"]):
            self._detect_imports(config)

        return config

    def _parse_dependencies(self, dependencies: List[str], config: Dict[str, Any]):
        for dep in dependencies:
            dep_lower = dep.lower()
            if "torch" in dep_lower:
                config["pytorch"] = True
                if "cu1" in dep_lower or "cuda" in dep_lower:  # Heuristic for cuda in specific torch versions
                    config["cuda"] = True
            if "tensorflow" in dep_lower:
                config["tensorflow"] = True
            if "onnx" in dep_lower:
                config["onnx"] = True

    def _detect_imports(self, config: Dict[str, Any]):
        for root, _, files in os.walk(self.project_root):
            if "venv" in root or ".git" in root or "__pycache__" in root:
                continue
            for file in files:
                if file.endswith(".py"):
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                            content = f.read()
                            if "import torch" in content or "from torch" in content:
                                config["pytorch"] = True
                            if "import tensorflow" in content or "from tensorflow" in content:
                                config["tensorflow"] = True
                            if "import onnx" in content or "from onnx" in content:
                                config["onnx"] = True
                    except Exception:
                        pass
            if config["pytorch"] or config["tensorflow"] or config["onnx"]:
                break

    def detect_apipod_config(self) -> Optional[Dict[str, str]]:
        """
        Scans python files for APIPod(title="...") to get the service title.
        """
        for root, _, files in os.walk(self.project_root):
            if "venv" in root or ".git" in root or "__pycache__" in root:
                continue

            # Prioritize main.py or server.py
            priority_files = ["main.py", "server.py"]
            other_files = [f for f in files if f.endswith(".py") and f not in priority_files]

            for file_list in [priority_files, other_files]:
                for file in file_list:
                    file_path = os.path.join(root, file)
                    if not os.path.exists(file_path):
                        continue

                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        if "APIPod" in content:
                            tree = ast.parse(content)
                            for node in ast.walk(tree):
                                if isinstance(node, ast.Call):
                                    if isinstance(node.func, ast.Name) and node.func.id == "APIPod":
                                        # Found APIPod(...)
                                        for keyword in node.keywords:
                                            if keyword.arg == "title":
                                                if isinstance(keyword.value, ast.Constant):  # Python 3.8+
                                                    return {"title": keyword.value.value, "file": file}
                                                elif isinstance(keyword.value, ast.Str):  # Python < 3.8
                                                    return {"title": keyword.value.s, "file": file}
                    except Exception:
                        continue
        return None
