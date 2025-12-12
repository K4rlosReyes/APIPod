import os
from typing import Dict, Any
from .IDetector import Detector


class EnvDetector(Detector):
    def detect(self) -> Dict[str, Any]:
        print("Scanning for environment variables...")
        env_file = os.path.join(self.project_root, ".env")
        if os.path.exists(env_file):
            print("Warning: .env file detected. Make sure to configure environment variables in your apipod.json.")
            return {"has_env_file": True}
        return {"has_env_file": False}
