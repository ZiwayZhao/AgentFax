#!/usr/bin/env python3
"""Start the XMTP Bridge process.

Reads wallet.json from the data directory, sets up environment variables,
and launches the Node.js XMTP bridge. Manages the bridge lifecycle.

The bridge port is auto-assigned (finds a free port starting from 3500)
and saved to <data_dir>/bridge_port so other scripts can discover it.

Supports Docker mode for systems with older GLIBC (< 2.34):
  python3 start_bridge.py ~/.bot-matcher --docker

Usage:
  python3 start_bridge.py <data_dir> [--env ENV] [--docker] [--stop]

Example:
  python3 start_bridge.py ~/.bot-matcher
  python3 start_bridge.py ~/.bot-matcher --docker
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


def find_free_port(start: int = 3500, attempts: int = 100) -> int:
    """Find a free TCP port starting from `start`."""
    for offset in range(attempts):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}-{start + attempts}")


def find_node() -> str:
    """Find a working Node.js binary (>= v22)."""
    import shutil
    for name in ("node", "nodejs"):
        path = shutil.which(name)
        if path:
            try:
                out = subprocess.check_output([path, "--version"], text=True).strip()
                major = int(out.lstrip("v").split(".")[0])
                if major >= 22:
                    return path
            except (subprocess.CalledProcessError, ValueError):
                continue
    return None


def check_glibc_version() -> tuple:
    """Check system GLIBC version. Returns (major, minor) or None if unknown."""
    try:
        result = subprocess.run(["ldd", "--version"], capture_output=True, text=True)
        output = result.stdout or result.stderr
        for line in output.split("\n"):
            if "GLIBC" in line or "ldd" in line.lower():
                # Extract version like "2.32" or "2.34"
                import re
                match = re.search(r"(\d+)\.(\d+)", line)
                if match:
                    return (int(match.group(1)), int(match.group(2)))
    except (FileNotFoundError, OSError):
        pass
    return None


def check_npm_deps(xmtp_dir: Path) -> bool:
    """Check if npm dependencies are installed."""
    return (xmtp_dir / "node_modules").exists()


def install_npm_deps(xmtp_dir: Path, node_path: str):
    """Install npm dependencies."""
    import shutil
    npm_path = shutil.which("npm")
    if not npm_path:
        raise RuntimeError("npm not found. Install Node.js >= 22 with npm.")
    print("[Bridge] Installing npm dependencies...")
    result = subprocess.run(
        [npm_path, "install", "--production"],
        cwd=str(xmtp_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"npm install failed:\n{result.stderr}")
    print("[Bridge] Dependencies installed.")


def _check_bridge_running(data_dir: Path):
    """Check if bridge is already running via saved port. Returns status dict or None."""
    port_file = data_dir / "bridge_port"
    if port_file.exists():
        try:
            saved_port = int(port_file.read_text().strip())
            req = Request(f"http://127.0.0.1:{saved_port}/health")
            with urlopen(req, timeout=3) as resp:
                health = json.loads(resp.read())
                if health.get("status") == "connected":
                    return {
                        "status": "already_running",
                        "address": health.get("address"),
                        "env": health.get("env"),
                        "port": saved_port,
                    }
        except (URLError, OSError, ValueError):
            pass
    return None


def _wait_for_ready(port: int, proc_or_container, data_dir: Path, is_docker: bool = False) -> dict:
    """Wait up to 30s for the bridge to become ready."""
    log_path = data_dir / "bridge.log"
    for attempt in range(30):
        time.sleep(1)
        if not is_docker and proc_or_container.poll() is not None:
            log_content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            return {"error": f"Bridge exited with code {proc_or_container.returncode}",
                    "log": log_content[-500:]}
        try:
            req = Request(f"http://127.0.0.1:{port}/health")
            with urlopen(req, timeout=3) as resp:
                health = json.loads(resp.read())
                if health.get("status") == "connected":
                    return {
                        "status": "started",
                        "address": health.get("address"),
                        "inboxId": health.get("inboxId"),
                        "env": health.get("env"),
                        "port": port,
                        "mode": "docker" if is_docker else "native",
                        "log_path": str(log_path),
                    }
        except (URLError, OSError):
            continue
    return {"error": "Bridge did not become ready within 30 seconds"}


# ---------------------------------------------------------------------------
# Native mode (Node.js directly)
# ---------------------------------------------------------------------------
def start_bridge_native(
    data_dir: Path,
    env: str = "dev",
) -> dict:
    """Start the XMTP bridge as a native Node.js process."""
    # 1. Load wallet
    wallet_path = data_dir / "wallet.json"
    if not wallet_path.exists():
        return {"error": f"No wallet.json found at {wallet_path}. Register on ERC-8004 first."}

    wallet = json.loads(wallet_path.read_text(encoding="utf-8"))
    private_key = wallet.get("private_key", "")
    if not private_key:
        return {"error": "wallet.json has no private_key"}

    # 2. Find Node.js
    node_path = find_node()
    if not node_path:
        return {"error": "Node.js >= 22 not found. Install: https://nodejs.org/ or use --docker"}

    # 3. Check bridge script exists
    script_dir = Path(__file__).parent
    xmtp_dir = script_dir / "xmtp"
    bridge_script = xmtp_dir / "xmtp_bridge.js"
    if not bridge_script.exists():
        return {"error": f"Bridge script not found: {bridge_script}"}

    # 4. Install deps if needed
    if not check_npm_deps(xmtp_dir):
        try:
            install_npm_deps(xmtp_dir, node_path)
        except RuntimeError as e:
            return {"error": str(e)}

    # 5. Check if already running
    running = _check_bridge_running(data_dir)
    if running:
        return running

    # 6. Auto-find a free port and launch bridge
    port = find_free_port()

    bridge_env = os.environ.copy()
    bridge_env["XMTP_PRIVATE_KEY"] = private_key
    bridge_env["XMTP_ENV"] = env
    bridge_env["BRIDGE_PORT"] = str(port)
    bridge_env["CLAWMATCH_DATA_DIR"] = str(data_dir)

    log_path = data_dir / "bridge.log"
    log_file = open(log_path, "w")

    proc = subprocess.Popen(
        [node_path, str(bridge_script)],
        cwd=str(xmtp_dir),
        env=bridge_env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    # Write PID + port files
    pid_path = data_dir / "bridge.pid"
    pid_path.write_text(str(proc.pid))
    port_file = data_dir / "bridge_port"
    port_file.write_text(str(port))

    # 7. Wait for bridge to be ready
    result = _wait_for_ready(port, proc, data_dir, is_docker=False)
    if "pid" not in result:
        result["pid"] = proc.pid
    return result


# ---------------------------------------------------------------------------
# Docker mode (for systems with GLIBC < 2.34)
# ---------------------------------------------------------------------------
def find_docker() -> str:
    """Find Docker binary."""
    import shutil
    return shutil.which("docker")


def start_bridge_docker(
    data_dir: Path,
    env: str = "dev",
) -> dict:
    """Start the XMTP bridge in a Docker container."""
    # 1. Load wallet
    wallet_path = data_dir / "wallet.json"
    if not wallet_path.exists():
        return {"error": f"No wallet.json found at {wallet_path}. Register on ERC-8004 first."}

    wallet = json.loads(wallet_path.read_text(encoding="utf-8"))
    private_key = wallet.get("private_key", "")
    if not private_key:
        return {"error": "wallet.json has no private_key"}

    # 2. Find Docker
    docker_path = find_docker()
    if not docker_path:
        return {"error": "Docker not found. Install Docker: https://docs.docker.com/get-docker/"}

    # 3. Check if already running
    running = _check_bridge_running(data_dir)
    if running:
        return running

    # 4. Build Docker image
    xmtp_dir = Path(__file__).parent / "xmtp"
    dockerfile = xmtp_dir / "Dockerfile"
    if not dockerfile.exists():
        return {"error": f"Dockerfile not found: {dockerfile}"}

    image_name = "clawmatch-bridge"
    print("[Bridge] Building Docker image...")
    build_result = subprocess.run(
        [docker_path, "build", "-t", image_name, str(xmtp_dir)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if build_result.returncode != 0:
        return {"error": f"Docker build failed:\n{build_result.stderr[-500:]}"}

    # 5. Auto-find a free port
    port = find_free_port()
    container_name = f"clawmatch-bridge-{port}"

    # Remove stale container with same name if exists
    subprocess.run(
        [docker_path, "rm", "-f", container_name],
        capture_output=True, timeout=10,
    )

    # 6. Run container
    #    --dns 8.8.8.8: ensure DNS works even if host resolv.conf is odd
    #    NODE_OPTIONS=--use-openssl-ca: use system CA certs for gRPC/TLS
    print(f"[Bridge] Starting Docker container on port {port}...")
    run_result = subprocess.run(
        [
            docker_path, "run", "-d",
            "--name", container_name,
            "--dns", "8.8.8.8",
            "-e", f"XMTP_PRIVATE_KEY={private_key}",
            "-e", f"XMTP_ENV={env}",
            "-e", "BRIDGE_PORT=3500",
            "-e", "CLAWMATCH_DATA_DIR=/data",
            "-e", "NODE_OPTIONS=--use-openssl-ca",
            "-v", f"{data_dir}:/data",
            "-p", f"127.0.0.1:{port}:3500",
            "--restart", "unless-stopped",
            image_name,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if run_result.returncode != 0:
        return {"error": f"Docker run failed:\n{run_result.stderr}"}

    container_id = run_result.stdout.strip()[:12]

    # Write container + port files
    (data_dir / "bridge_container").write_text(container_name)
    (data_dir / "bridge_port").write_text(str(port))

    # 7. Wait for bridge to be ready
    result = _wait_for_ready(port, None, data_dir, is_docker=True)
    result["container"] = container_name
    result["container_id"] = container_id
    return result


def stop_bridge(data_dir: Path) -> dict:
    """Stop the running XMTP bridge (native or Docker)."""
    data_dir = data_dir.expanduser()
    pid_path = data_dir / "bridge.pid"
    port_file = data_dir / "bridge_port"
    container_file = data_dir / "bridge_container"

    stopped = False

    # Try Docker stop first
    if container_file.exists():
        try:
            container_name = container_file.read_text().strip()
            docker_path = find_docker()
            if docker_path and container_name:
                subprocess.run(
                    [docker_path, "stop", container_name],
                    capture_output=True, timeout=15,
                )
                subprocess.run(
                    [docker_path, "rm", container_name],
                    capture_output=True, timeout=10,
                )
                stopped = True
        except (OSError, subprocess.TimeoutExpired):
            pass
        container_file.unlink(missing_ok=True)

    # Try native PID stop
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except (ProcessLookupError, ValueError):
            pass
        pid_path.unlink(missing_ok=True)

    port_file.unlink(missing_ok=True)

    return {"status": "stopped" if stopped else "not_running"}


def start_bridge(data_dir: Path, env: str = "dev", use_docker: bool = False) -> dict:
    """Start bridge, choosing native or Docker mode."""
    data_dir = data_dir.expanduser()

    if use_docker:
        return start_bridge_docker(data_dir, env)

    # Auto-detect: recommend Docker if GLIBC is too old
    glibc = check_glibc_version()
    if glibc and (glibc[0] < 2 or (glibc[0] == 2 and glibc[1] < 34)):
        print(f"[Bridge] System GLIBC is {glibc[0]}.{glibc[1]} (need >= 2.34).")
        if find_docker():
            print("[Bridge] Docker found — using Docker mode automatically.")
            return start_bridge_docker(data_dir, env)
        else:
            return {
                "error": f"GLIBC {glibc[0]}.{glibc[1]} is too old for @xmtp/node-sdk (need 2.34+). "
                         f"Install Docker and re-run, or upgrade your OS.",
                "glibc": f"{glibc[0]}.{glibc[1]}",
                "hint": "pip install docker or apt install docker.io, then re-run with --docker",
            }

    return start_bridge_native(data_dir, env)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Start/stop XMTP bridge")
    parser.add_argument("data_dir", help="Data directory (e.g. ~/.bot-matcher)")
    parser.add_argument("--env", default="dev", choices=["dev", "production", "local"],
                        help="XMTP environment (default: dev)")
    parser.add_argument("--docker", action="store_true",
                        help="Force Docker mode (for systems with GLIBC < 2.34)")
    parser.add_argument("--stop", action="store_true", help="Stop the bridge")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser()

    if args.stop:
        result = stop_bridge(data_dir)
    else:
        result = start_bridge(data_dir, args.env, use_docker=args.docker)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
