import argparse
import os
import sys
import subprocess
from typing import Optional

from apipod.deploy.deploy import DeploymentManager


def input_yes_no(question: str, default: bool = True) -> bool:
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    prompt = " [Y/n] " if default else " [y/N] "
    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if choice == "":
            return default
        if choice in valid:
            return valid[choice]
        sys.stdout.write("Please respond with 'yes' or 'no' (or 'y'/'n').\n")


def input_choice(question: str, choices: list, default: Optional[str] = None) -> str:
    prompt = f" [{'/'.join(choices)}]"
    if default:
        prompt += f" (default: {default})"
    prompt += ": "

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower().strip()
        if choice == "" and default:
            return default
        if choice in choices:
            return choice
        sys.stdout.write(f"Please respond with one of: {', '.join(choices)}\n")


def main():
    parser = argparse.ArgumentParser(description="APIPod CLI")
    parser.add_argument("-build", action="store_true", help="Build the service container")
    parser.add_argument("-serverless", action="store_true", help="Use serverless deployment configuration")
    parser.add_argument("-pod", action="store_true", help="Use pod deployment configuration")

    args = parser.parse_args()

    if args.build:
        run_build(args)
    else:
        parser.print_help()


def run_build(args):
    project_root = os.getcwd()
    manager = DeploymentManager(project_root)

    # 1. Check existing config
    dockerfile_path = os.path.join(project_root, "Dockerfile")
    deploy_dockerfile_path = os.path.join(project_root, "deploy", "Dockerfile")  # Handling potential deploy/ location

    if os.path.exists(dockerfile_path) or os.path.exists(deploy_dockerfile_path):
        if not input_yes_no("Deployment config exists. Overwrite your deployment config?"):
            print("Aborting build configuration.")
            return

    # 2. Deployment Type
    deployment_type = "pod"  # default
    if args.serverless:
        deployment_type = "serverless"
    elif args.pod:
        deployment_type = "pod"
    else:
        choice = input_choice("How do you want to deploy the service?", ["serverless", "pod"], default="pod")
        deployment_type = choice

    # 3. Detect Config and Propose Image
    print("Detecting project configuration...")
    config = manager.detector.detect_runtime()

    # Detect APIPod title
    apipod_config = manager.detector.detect_apipod_config()
    service_title = apipod_config.get("title", "apipod-service") if apipod_config else "apipod-service"
    entrypoint_file = apipod_config.get("file", "main.py") if apipod_config else "main.py"

    recommended_image = manager.recommend_image(config)
    print(f"Detected configuration: Python {config.get('python_version')}, PyTorch: {config.get('pytorch')}, TensorFlow: {config.get('tensorflow')}")
    print(f"Recommended Base Image: {recommended_image}")

    use_image = input_yes_no("Is this correct?")
    final_image = recommended_image
    
    if not use_image:
        print("Select a base image:")
        for i, img in enumerate(manager.images):
            print(f"{i + 1}. {img}")
        print(f"{len(manager.images) + 1}. Enter custom image")
        
        while True:
            try:
                selection = input("Selection: ")
                idx = int(selection) - 1
                if 0 <= idx < len(manager.images):
                    final_image = manager.images[idx]
                    break
                elif idx == len(manager.images):
                    final_image = input("Enter custom base image: ").strip()
                    if final_image:
                        break
            except ValueError:
                pass
            print("Invalid selection.")

    if final_image == "Enter custom base image":  # Fallback if logic falls through
        print("Please write your own Dockerfile and config.")
        return

    # 4. Check requirements
    has_toml = os.path.exists(os.path.join(project_root, "pyproject.toml"))
    has_req = os.path.exists(os.path.join(project_root, "requirements.txt"))

    if not has_toml and not has_req:
        print("Warning: No pyproject.toml or requirements.txt found.")
        if not input_yes_no("Proceed anyway?", default=False):
            print("Please configure dependencies and try again.")
            return

    # Generate Dockerfile
    print(f"Generating Dockerfile for {deployment_type} deployment...")
    dockerfile_content = manager.generate_dockerfile(deployment_type, final_image, entrypoint_file)
    manager.write_dockerfile(dockerfile_content)
    print("Dockerfile created.")

    # 5. Build Application
    if input_yes_no(f"Build the application now using docker? (Tag: {service_title})"):
        try:
            cmd = ["docker", "build", "-t", service_title, "."]
            print(f"Running: {' '.join(cmd)}")
            subprocess.check_call(cmd)
            print("Build completed successfully.")
        except subprocess.CalledProcessError:
            print("Docker build failed.")
        except FileNotFoundError:
            print("Error: 'docker' command not found. Is Docker installed and in your PATH?")


if __name__ == "__main__":
    main()
