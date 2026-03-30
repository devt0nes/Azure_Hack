#!/usr/bin/env python3
"""ACR connectivity and image access preflight check.

Usage:
  python test_acr_access.py
  python test_acr_access.py --repo nexus-test-runner --tag latest --pull
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Tuple


def _normalize_registry(registry: str) -> str:
    value = str(registry or "").strip()
    value = re.sub(r"^https?://", "", value, flags=re.IGNORECASE).strip("/")
    if "/" in value:
        value = value.split("/", 1)[0]
    if value and "." not in value:
        value = f"{value}.azurecr.io"
    return value


def _acr_name(registry: str) -> str:
    host = _normalize_registry(registry)
    if host.endswith(".azurecr.io"):
        return host.split(".", 1)[0]
    return host.split(".", 1)[0] if host else ""


def _run(cmd: list[str], timeout: int = 30) -> Tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ACR/image accessibility for ACI runs")
    parser.add_argument("--registry", default=os.getenv("AZURE_CONTAINER_REGISTRY", ""))
    parser.add_argument("--repo", default=os.getenv("AZURE_CONTAINER_REPOSITORY", "nexus-test-runner"))
    parser.add_argument("--tag", default=os.getenv("AZURE_CONTAINER_TAG", "latest"))
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Also try docker login + docker pull (requires docker daemon)",
    )
    args = parser.parse_args()

    registry = _normalize_registry(args.registry)
    repo = str(args.repo or "").strip().strip("/")
    tag = str(args.tag or "latest").strip()
    if not registry:
        print("ERROR: registry missing. Set AZURE_CONTAINER_REGISTRY or pass --registry", file=sys.stderr)
        return 2
    if not repo:
        print("ERROR: repository missing. Set AZURE_CONTAINER_REPOSITORY or pass --repo", file=sys.stderr)
        return 2

    image = f"{registry}/{repo}:{tag}"
    acr_name = _acr_name(registry)

    print("== ACR Preflight ==")
    print(f"Registry host : {registry}")
    print(f"ACR name      : {acr_name}")
    print(f"Repository    : {repo}")
    print(f"Tag           : {tag}")
    print(f"Image         : {image}")

    if not shutil.which("az"):
        print("ERROR: Azure CLI (`az`) not found in PATH", file=sys.stderr)
        return 3

    # 1) Registry reachable and exists
    rc, out, err = _run(["az", "acr", "show", "-n", acr_name, "-o", "json"], timeout=30)
    if rc != 0:
        print(f"ERROR: az acr show failed: {err or out}", file=sys.stderr)
        return 4
    with suppress_json_decode():
        payload = json.loads(out)
        login_server = str(payload.get("loginServer") or "")
        if login_server and login_server != registry:
            print(f"WARN: loginServer mismatch: {login_server} (expected {registry})")
    print("OK: Registry exists and is reachable via Azure CLI")

    # 2) Credentials present (or at least retrievable)
    rc, out, err = _run(["az", "acr", "credential", "show", "-n", acr_name, "-o", "json"], timeout=30)
    if rc != 0:
        print(
            "WARN: Could not retrieve ACR credentials via CLI. "
            "If ACI pull still works via managed identity/RBAC, this may be fine."
        )
        print(f"      Details: {err or out}")
    else:
        print("OK: ACR credentials are retrievable via Azure CLI")

    # 3) Repo/tag existence
    rc, out, err = _run(
        ["az", "acr", "repository", "show-tags", "-n", acr_name, "--repository", repo, "-o", "json"],
        timeout=40,
    )
    if rc != 0:
        print(f"ERROR: Could not list tags for repo '{repo}': {err or out}", file=sys.stderr)
        return 5
    tags = []
    with suppress_json_decode():
        data = json.loads(out)
        if isinstance(data, list):
            tags = [str(x) for x in data]
    if tag not in tags:
        print(f"ERROR: Tag '{tag}' not found in repo '{repo}'. Available: {tags[:10]}", file=sys.stderr)
        return 6
    print(f"OK: Tag '{tag}' exists in repository '{repo}'")

    # 4) Optional docker pull
    if args.pull:
        if not shutil.which("docker"):
            print("ERROR: docker not found but --pull was requested", file=sys.stderr)
            return 7

        user = (
            os.getenv("AZURE_CONTAINER_REGISTRY_USERNAME")
            or os.getenv("AZURE_ACR_USERNAME")
            or os.getenv("ACR_USERNAME")
            or ""
        ).strip()
        pwd = (
            os.getenv("AZURE_CONTAINER_REGISTRY_PASSWORD")
            or os.getenv("AZURE_ACR_PASSWORD")
            or os.getenv("ACR_PASSWORD")
            or ""
        ).strip()

        if not user or not pwd:
            print("ERROR: Missing ACR username/password in env for --pull test", file=sys.stderr)
            return 8

        login_cmd = ["docker", "login", registry, "-u", user, "--password-stdin"]
        try:
            proc = subprocess.run(
                login_cmd,
                input=pwd,
                text=True,
                capture_output=True,
                timeout=30,
            )
        except Exception as exc:
            print(f"ERROR: docker login failed: {exc}", file=sys.stderr)
            return 9

        if proc.returncode != 0:
            print(f"ERROR: docker login failed: {proc.stderr or proc.stdout}", file=sys.stderr)
            return 10
        print("OK: docker login succeeded")

        rc, out, err = _run(["docker", "pull", image], timeout=240)
        if rc != 0:
            print(f"ERROR: docker pull failed: {err or out}", file=sys.stderr)
            return 11
        print("OK: docker pull succeeded")

    print("SUCCESS: ACR preflight checks passed")
    return 0


class suppress_json_decode:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is json.JSONDecodeError


if __name__ == "__main__":
    raise SystemExit(main())
