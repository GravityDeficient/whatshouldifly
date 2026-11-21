#!/usr/bin/env python3
"""Push a local directory to a GitHub repo via the REST API.

Why this exists: the Agent Vault proxy only rewrites auth on api.github.com, so
plain `git push` over https://github.com fails with 401. The REST API works
because the vault injects the token into api.github.com requests. So we build
the commit with the Git Data API instead of a git remote.

Usage: python3 scripts/ghpush.py <owner/repo> <local_dir> "<commit message>"
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"


def call(method, path, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", ""),
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "belle-ghpush",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        raise SystemExit(f"{method} {path} -> {e.code}\n{detail}")


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    repo, local, message = sys.argv[1], sys.argv[2], sys.argv[3]

    info = call("GET", f"/repos/{repo}")
    branch = info.get("default_branch", "main")

    # current head, if the repo has commits
    try:
        ref = call("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        parent = ref["object"]["sha"]
        base_tree = call("GET", f"/repos/{repo}/git/commits/{parent}")["tree"]["sha"]
    except SystemExit:
        parent, base_tree = None, None

    entries = []
    for root, _, files in os.walk(local):
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, local).replace(os.sep, "/")
            if rel.startswith(".git/"):
                continue
            with open(full, "rb") as fh:
                data = fh.read()
            blob = call("POST", f"/repos/{repo}/git/blobs", {
                "content": base64.b64encode(data).decode(),
                "encoding": "base64",
            })
            entries.append({
                "path": rel,
                "mode": "100755" if os.access(full, os.X_OK) else "100644",
                "type": "blob",
                "sha": blob["sha"],
            })
            print(f"  blob {rel} ({len(data)} bytes)")

    tree_body = {"tree": entries}
    if base_tree:
        tree_body["base_tree"] = base_tree
    tree = call("POST", f"/repos/{repo}/git/trees", tree_body)

    commit_body = {"message": message, "tree": tree["sha"]}
    if parent:
        commit_body["parents"] = [parent]
    commit = call("POST", f"/repos/{repo}/git/commits", commit_body)

    if parent:
        call("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", {
            "sha": commit["sha"], "force": False,
        })
    else:
        call("POST", f"/repos/{repo}/git/refs", {
            "ref": f"refs/heads/{branch}", "sha": commit["sha"],
        })

    print(f"pushed {len(entries)} files -> {repo}@{branch} {commit['sha'][:12]}")


if __name__ == "__main__":
    main()
