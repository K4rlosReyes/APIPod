from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader


class DockerFactory:
    """
    Encapsulates all Docker-related operations:
    - base image recommendation
    - Dockerfile rendering
    - Dockerfile persistence
    - docker build execution
    """

    DEFAULT_IMAGES = [
        "python:3.10-slim",
        "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
    ]

    def __init__(
        self,
        project_root: Path,
        deploy_dir: Path,
        template_dir: Optional[Path] = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.deploy_dir = Path(deploy_dir)
        self.template_dir = template_dir or Path(__file__).parent

        self.template_env = Environment(
            loader=FileSystemLoader(str(self.template_dir))
        )
        self.docker_template = self.template_env.get_template("docker_template.j2")
        self.images = self._load_images(self.template_dir / "docker_images.txt")

    def _load_images(self, images_path: Path) -> List[str]:
        if images_path.exists():
            try:
                with images_path.open("r", encoding="utf-8") as f:
                    images = [line.strip() for line in f if line.strip()]
                    if images:
                        return images
            except Exception:
                # Fall back to defaults if the list cannot be read
                pass
        return self.DEFAULT_IMAGES.copy()

    def recommend_image(self, config: Dict[str, Any]) -> str:
        """
        Select an image that matches the detected framework requirements.
        """
        if config.get("pytorch") and config.get("cuda"):
            for img in self.images:
                if "runpod/pytorch" in img:
                    return img
            return "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"

        python_version = str(config.get("python_version") or "")
        if python_version:
            for img in self.images:
                if f"python:{python_version}-slim" in img:
                    return img

        return self.DEFAULT_IMAGES[0]

    def render_dockerfile(self, base_image: str, config: Dict[str, Any]) -> str:
        has_requirements = (self.project_root / "requirements.txt").exists()
        entrypoint = config.get("entrypoint", "main.py")
        entrypoint_module = (
            Path(entrypoint).with_suffix("").as_posix().replace("/", ".").replace("\\", ".")
        )

        context = {
            "base_image": base_image,
            "has_requirements": has_requirements,
            "entrypoint_module": entrypoint_module,
            "install_cudnn": bool(config.get("tensorflow") or config.get("onnx")),
            "system_packages": config.get("system_packages", []),
        }
        return self.docker_template.render(**context)

    def write_dockerfile(self, content: str, dockerfile_path: Path) -> Path:
        self.deploy_dir.mkdir(parents=True, exist_ok=True)
        dockerfile_path = Path(dockerfile_path)
        dockerfile_path.write_text(content, encoding="utf-8")
        print(f"Dockerfile created at {dockerfile_path}")
        return dockerfile_path

    def build_image(self, tag: str, dockerfile_path: Path, context_dir: Path) -> bool:
        cmd = ["docker", "build", "-t", tag, "-f", str(dockerfile_path), str(Path(context_dir))]
        print(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
            print("Build completed successfully.")
            return True
        except FileNotFoundError:
            print("Error: 'docker' command not found. Is Docker installed and in your PATH?")
        except subprocess.CalledProcessError:
            print("Docker build failed.")
        return False
