import os
import sys
import time
import base64
import requests

GITHUB_API = "https://api.github.com"

IGNORED_DIRS = {".venv", "venv", "__pycache__", ".git", ".idea", ".vscode"}
IGNORED_FILES = {".DS_Store", "Thumbs.db"}

def collect_project_files(root_dir: str):
    collected = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Filter out ignored directories
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        for f in filenames:
            if f in IGNORED_FILES or f.endswith(('.pyc', '.pyo')):
                continue
            full_path = os.path.join(dirpath, f)
            rel_path = os.path.relpath(full_path, root_dir).replace('\\', '/')
            collected.append((rel_path, full_path))
    return collected

def deploy_to_github(token: str, repo_name: str = "nexora", is_private: bool = False):
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # 1. Verify user token
    print("Verifying GitHub authentication...")
    user_res = requests.get(f"{GITHUB_API}/user", headers=headers)
    if user_res.status_code != 200:
        print(f"Authentication failed ({user_res.status_code}): {user_res.text}")
        return False, None

    user_info = user_res.json()
    username = user_info.get("login")
    print(f"Authenticated as GitHub user: @{username}")

    # 2. Check if repository exists or create it
    repo_res = requests.get(f"{GITHUB_API}/repos/{username}/{repo_name}", headers=headers)
    if repo_res.status_code == 404:
        print(f"Creating new repository '{repo_name}' on GitHub...")
        create_res = requests.post(f"{GITHUB_API}/user/repos", headers=headers, json={
            "name": repo_name,
            "description": "Nexora: Autonomous Document Intelligence & Cross-Verification Platform",
            "private": is_private,
            "auto_init": False
        })
        if create_res.status_code not in (200, 201):
            print(f"Failed to create repo ({create_res.status_code}): {create_res.text}")
            return False, None
        print(f"Repository created: https://github.com/{username}/{repo_name}")
    elif repo_res.status_code == 200:
        print(f"Using repository: https://github.com/{username}/{repo_name}")
    else:
        print(f"Error checking repository ({repo_res.status_code}): {repo_res.text}")
        return False, None

    # 3. Collect project files
    project_dir = os.path.dirname(os.path.abspath(__file__))
    files = collect_project_files(project_dir)
    # Ensure README.md is uploaded first to initialize the main branch
    files.sort(key=lambda x: 0 if x[0] == "README.md" else 1)
    print(f"Uploading {len(files)} files to repository...")

    # 4. Upload each file using the GitHub Contents API with retry handling
    success_count = 0
    for rel_path, full_path in files:
        url = f"{GITHUB_API}/repos/{username}/{repo_name}/contents/{rel_path}"
        with open(full_path, "rb") as f:
            b64_content = base64.b64encode(f.read()).decode("utf-8")
        
        for attempt in range(4):
            try:
                # Check if file already exists to get its sha
                sha = None
                get_res = requests.get(url, headers=headers, timeout=15)
                if get_res.status_code == 200:
                    sha = get_res.json().get("sha")

                payload = {
                    "message": f"Update {rel_path}",
                    "content": b64_content,
                    "branch": "main"
                }
                if sha:
                    payload["sha"] = sha

                put_res = requests.put(url, headers=headers, json=payload, timeout=20)
                if put_res.status_code in (200, 201):
                    print(f"  [+] {rel_path}")
                    success_count += 1
                    break
                else:
                    print(f"  [-] Failed {rel_path} ({put_res.status_code}): {put_res.text}")
                    break
            except Exception as err:
                if attempt < 3:
                    time.sleep(2)
                    continue
                print(f"  [-] Connection error on {rel_path}: {err}")

    repo_url = f"https://github.com/{username}/{repo_name}"
    print(f"\nSuccessfully uploaded {success_count}/{len(files)} files!")
    print(f"Live repository: {repo_url}")
    return True, repo_url

if __name__ == "__main__":
    token = os.getenv("GITHUB_TOKEN")
    if not token and len(sys.argv) > 1:
        token = sys.argv[1]
    
    if not token:
        print("Usage: python deploy_github.py <YOUR_GITHUB_TOKEN>")
        sys.exit(1)

    repo_name = sys.argv[2] if len(sys.argv) > 2 else "nexora"
    success, url = deploy_to_github(token, repo_name)
    if success:
        print(f"\nDone! View your repository: {url}")
    else:
        sys.exit(1)
