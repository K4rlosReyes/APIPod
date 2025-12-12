import os
import re
import toml
import json
from typing import Dict, Any, List
from .IDetector import Detector


class FrameworkDetector(Detector):
    def detect(self) -> Dict[str, Any]:
        print("Scanning for frameworks and models...")
        config = {
            "pytorch": False,
            "tensorflow": False,
            "onnx": False,
            "transformers": False,
            "diffusers": False,
            "cuda": False,
            "python_version": "3.10",
            "model_files": []
        }

        # 1. Check Dependencies (pyproject.toml / requirements.txt)
        self._check_dependencies(config)

        # 2. Check Imports if not detected via deps
        if not (config["pytorch"] or config["tensorflow"] or config["onnx"] or config["transformers"] or config["diffusers"]):
            self._check_imports(config)

        # 3. Scan for model files
        self._scan_model_files(config)

        return config

    def _check_dependencies(self, config: Dict[str, Any]):
        dependencies = []

        # Check pyproject.toml
        pyproject_path = os.path.join(self.project_root, "pyproject.toml")
        if os.path.exists(pyproject_path):
            try:
                data = toml.load(pyproject_path)
                if "project" in data and "dependencies" in data["project"]:
                    dependencies.extend(data["project"]["dependencies"])
                if "tool" in data and "poetry" in data["tool"] and "dependencies" in data["tool"]["poetry"]:
                    dependencies.extend(data["tool"]["poetry"]["dependencies"].keys())

                if "project" in data and "requires-python" in data["project"]:
                    ver = data["project"]["requires-python"]
                    match = re.search(r'3\.(\d+)', ver)
                    if match:
                        config["python_version"] = f"3.{match.group(1)}"
            except Exception as e:
                print(f"Warning: Error parsing pyproject.toml: {e}")

        # Check requirements.txt
        requirements_path = os.path.join(self.project_root, "requirements.txt")
        if os.path.exists(requirements_path):
            try:
                with open(requirements_path, "r") as f:
                    dependencies.extend(f.readlines())
            except Exception as e:
                print(f"Warning: Error parsing requirements.txt: {e}")

        self._parse_dependencies(dependencies, config)

    def _parse_dependencies(self, dependencies: List[str], config: Dict[str, Any]):
        for dep in dependencies:
            dep_lower = dep.lower()

            if "torch" in dep_lower:
                config["pytorch"] = self._resolve_version(dep)
                if "cu1" in dep_lower or "cuda" in dep_lower:
                    config["cuda"] = True
            if "tensorflow" in dep_lower:
                config["tensorflow"] = self._resolve_version(dep)
            if "onnx" in dep_lower:
                config["onnx"] = self._resolve_version(dep)
            if "transformers" in dep_lower:
                config["transformers"] = self._resolve_version(dep)
            if "diffusers" in dep_lower:
                config["diffusers"] = self._resolve_version(dep)

    def _check_imports(self, config: Dict[str, Any]):
        for root, _, files in os.walk(self.project_root):
            if self.should_ignore(root):
                continue
            for file in files:
                if file.endswith(".py"):
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                            content = f.read()
                            if "torch" in content:
                                config["pytorch"] = True
                            if "tensorflow" in content:
                                config["tensorflow"] = True
                            if "onnx" in content: 
                                config["onnx"] = True
                            if "transformers" in content:
                                config["transformers"] = True
                            if "diffusers" in content:
                                config["diffusers"] = True
                    except Exception:
                        pass
            if any([config["pytorch"], config["tensorflow"], config["onnx"], config["transformers"], config["diffusers"]]):
                break

    def _scan_model_files(self, config: Dict[str, Any]):
        # Extensions commonly associated with model weights
        extensions = {".pt", ".pth", ".onnx", ".h5", ".safetensors", ".bin", ".gguf"}
        found_files = []

        for root, _, files in os.walk(self.project_root):
            if self.should_ignore(root):
                continue

            for file in files:
                file_path = os.path.join(root, file)
                _, ext = os.path.splitext(file)
                ext = ext.lower()

                if ext in extensions:
                    found_files.append(os.path.relpath(file_path, self.project_root))
                elif ext == ".json":
                    if self._is_model_json(file_path):
                        found_files.append(os.path.relpath(file_path, self.project_root))

        config["model_files"] = found_files

    def _is_model_json(self, file_path: str) -> bool:
        """
        Heuristic to determine if a JSON file is a model configuration or tokenizer file.
        """
        filename = os.path.basename(file_path).lower()
        # Known model json files
        if filename in ["config.json", "tokenizer.json", "tokenizer_config.json", "generation_config.json", "adapter_config.json"]:
            return True

        # Ignore standard project files
        if filename in ["package.json", "tsconfig.json", "apipod.json", "pyproject.json", "launch.json", "settings.json"]:
            return False

        # Inspect content for keys common in model configs
        try:
            # Only read the first 4KB to be safe/fast
            with open(file_path, "r", encoding="utf-8") as f:
                # We read a chunk, but for JSON we need valid syntax. 
                # If the file is huge, it's probably not a config.
                # But if it's model weights stored as JSON (rare), we might want it? 
                # Generally JSON weights are split or not just pure JSON.
                # Let's try to load it if it's small enough (< 1MB)
                if os.path.getsize(file_path) > 1024 * 1024: 
                    return False

                content = json.load(f)
                if isinstance(content, dict):
                    keys = content.keys()
                    # Common HF config keys
                    model_keys = {"architectures", "model_type", "vocab_size", "hidden_size", "layer_norm_epsilon"}
                    if any(k in keys for k in model_keys):
                        return True
                    # Common Tokenizer keys
                    if "version" in keys and "truncation" in keys:
                        return True
        except Exception:
            pass

        return False

    def _resolve_version(self, dependency: str) -> str:
        # Simple extraction logic reusing previous concepts
        if "=" in dependency and not any(op in dependency for op in [">=", "<=", "!=", "==", "~=", ">", "<"]):
            # TOML table or simple assignment
            match = re.search(r'["\']([^"\']+)["\']', dependency)
            return match.group(1) if match else "latest"

        version_operators = ["==", ">=", "<=", "!=", "~=", ">", "<"]
        for op in version_operators:
            if op in dependency:
                parts = dependency.split(op, 1)
                if len(parts) == 2:
                    # Clean up version string
                    version = re.split(r'[;\s]', parts[1].strip())[0].strip().strip('"\'')
                    return version
        return "latest"
