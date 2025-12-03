import os
from typing import List, Dict, Any
from jinja2 import Environment, FileSystemLoader
from .config_detector import ConfigDetector


class DeploymentManager:
    def __init__(self, project_root: str = "."):
        self.project_root = project_root
        self.detector = ConfigDetector(project_root)
        self.images = self._load_images()
        self.template_env = Environment(loader=FileSystemLoader(os.path.dirname(__file__)))
        self.docker_template = self.template_env.get_template("docker_template.j2")

    def _load_images(self) -> List[str]:
        try:
            images_path = os.path.join(os.path.dirname(__file__), "docker_images")
            if os.path.exists(images_path):
                with open(images_path, "r") as f:
                    return [line.strip() for line in f if line.strip()]
        except Exception:
            pass
        # Fallback defaults if file missing
        return [
            "python:3.10-slim",
            "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
        ]

    def recommend_image(self, config: Dict[str, Any]) -> str:
        """
        Selects a base image based on detected configuration.
        """
        if config.get("pytorch") and config.get("cuda"):
            # Try to find a runpod pytorch image
            for img in self.images:
                if "runpod/pytorch" in img:
                    # Simple heuristic: prefer ubuntu2204 and recent python if possible
                    # Real implementation would be more complex matching versions
                    return img
            # Fallback specific
            return "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"

        if config.get("python_version"):
            ver = config["python_version"]
            # Try to find matching python slim image
            for img in self.images:
                if f"python:{ver}-slim" in img:
                    return img

        return "python:3.10-slim"

    def generate_dockerfile(self, deployment_type: str, base_image: str, entrypoint_module: str = "main") -> str:
        has_requirements = os.path.exists(os.path.join(self.project_root, "requirements.txt"))

        context = {
            "deployment_type": deployment_type,
            "base_image": base_image,
            "has_requirements": has_requirements,
            "entrypoint_module": entrypoint_module.replace(".py", "")
        }

        return self.docker_template.render(**context)

    def write_dockerfile(self, content: str):
        deploy_dir = os.path.join(self.project_root, "deploy")
        os.makedirs(deploy_dir, exist_ok=True)

        # Write to Dockerfile in root
        with open(os.path.join(self.project_root, "Dockerfile"), "w") as f:
            f.write(content)
