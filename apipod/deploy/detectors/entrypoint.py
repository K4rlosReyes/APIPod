import os
import ast
from typing import Dict, Any
from .IDetector import Detector


class EntrypointDetector(Detector):
    def detect(self) -> Dict[str, Any]:
        print("Scanning for entrypoint and service configuration...")

        result = {
            "file": None,
            "title": "apipod-service",  # Default
            "found_config": False
        }

        # Define search order
        priority_files = ["main.py", "app.py", "api.py", "serve.py"]

        # 1. Check priority files first
        for filename in priority_files:
            path = os.path.join(self.project_root, filename)
            if os.path.exists(path):
                result["file"] = filename
                # Scan this file for title
                self._scan_file_for_title(path, result)
                if result["found_config"]:
                    print(f"Found entrypoint and config in: {filename}")
                    return result
                print(f"Found entrypoint file: {filename} (no config detected)")
                # We continue scanning other files for config? 
                # Usually if we have main.py, that's the entrypoint. 
                # But maybe the config is elsewhere? Unlikely for APIPod pattern.
                return result

        # 2. Scan all python files if no priority file found OR to find config/entrypoint pattern
        print("No standard entrypoint file found. Scanning file contents...")
        for root, _, files in os.walk(self.project_root):
            if self.should_ignore(root):
                continue

            for file in files:
                if file.endswith(".py") and file not in priority_files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.project_root)

                    if self._scan_file_for_indicators(file_path, result):
                        result["file"] = rel_path
                        print(f"Found entrypoint in code pattern: {rel_path}")
                        return result

        if result["file"] is None:
            print("No entrypoint detected.")

        return result

    def _scan_file_for_title(self, file_path: str, result: Dict[str, Any]):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if "APIPod" in content:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name) and node.func.id == "APIPod":
                            for keyword in node.keywords:
                                if keyword.arg == "title":
                                    if isinstance(keyword.value, ast.Constant):  # Python 3.8+
                                        result["title"] = keyword.value.value
                                        result["found_config"] = True
                                    elif isinstance(keyword.value, ast.Str):  # Python < 3.8
                                        result["title"] = keyword.value.s
                                        result["found_config"] = True
        except Exception:
            pass

    def _scan_file_for_indicators(self, file_path: str, result: Dict[str, Any]) -> bool:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Check for APIPod config
            if "APIPod" in content:
                self._scan_file_for_title(file_path, result)
                if result["found_config"]:
                    return True

            # Check for other indicators
            if "app.start()" in content or "uvicorn.run" in content:
                return True

            return False
        except Exception:
            return False
