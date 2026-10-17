import argparse
import fcntl
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from dotenv import dotenv_values, set_key
from nemothello.config import Settings

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
WEB = ROOT / "web"


class StartError(Exception):
    pass


def port_number(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1024 and 65535")
    return port


def check_environment(backend_port: int, web_port: int) -> str:
    node = shutil.which("node")
    if node is None:
        raise StartError("Node.js was not found. Install Node.js 20.9 or later.")
    version = subprocess.check_output([node, "-p", "process.versions.node"], text=True).strip()
    if tuple(int(part) for part in version.split(".")) < (20, 9, 0):
        raise StartError("Node.js is too old. Version 20.9 or later is required.")
    if not (ROOT / "node_modules/next/dist/bin/next").is_file():
        raise StartError("Frontend dependencies are missing. Run at the repository root: npm ci")
    if backend_port == web_port:
        raise StartError("Frontend and backend must use different ports.")
    for name, port in (("Backend", backend_port), ("Frontend", web_port)):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise StartError(f"{name} port {port} is unavailable. Stop the service using it or choose another port.") from exc
    return node


def prepare_configuration(backend_port: int, write: bool) -> Settings:
    backend_file, web_file = BACKEND / ".env", WEB / ".env.local"
    backend_values = dotenv_values(backend_file) if backend_file.exists() else {}
    web_values = dotenv_values(web_file) if web_file.exists() else {}

    def configured(name: str, default: str = "") -> str:
        return (os.environ.get(name, backend_values.get(name)) or default).strip()

    token = (configured("BACKEND_SERVICE_TOKEN")
             or (web_values.get("BACKEND_SERVICE_TOKEN") or "").strip()
             or secrets.token_urlsafe(32))
    paths = {}
    for name, filename in (("EDAX_EXECUTABLE", "edax"), ("EDAX_EVAL_FILE", "eval.dat")):
        path = Path(configured(name, str(ROOT / "deploy/edax" / filename))).expanduser()
        paths[name] = str((BACKEND / path).resolve() if not path.is_absolute() else path.resolve())
    settings = Settings(
        _env_file=backend_file,
        backend_service_token=token,
        edax_executable=Path(paths["EDAX_EXECUTABLE"]),
        edax_eval_file=Path(paths["EDAX_EVAL_FILE"]),
        edax_version=configured("EDAX_VERSION", "4.6"),
    )
    settings.validate_resources()
    if not os.access(settings.edax_executable, os.X_OK):
        raise StartError("Edax is not executable. Check EDAX_EXECUTABLE.")
    if write:
        for path, example in ((backend_file, BACKEND / ".env.example"),
                              (web_file, WEB / ".env.example")):
            if not path.exists():
                shutil.copyfile(example, path)
            path.chmod(0o600)
        backend_updates = {**paths, "BACKEND_SERVICE_TOKEN": token,
                           "EDAX_VERSION": settings.edax_version}
        web_updates = {"BACKEND_SERVICE_TOKEN": token,
                       "BACKEND_URL": f"http://127.0.0.1:{backend_port}"}
        for path, old_values, updates in ((backend_file, backend_values, backend_updates),
                                          (web_file, web_values, web_updates)):
            for name, value in updates.items():
                if old_values.get(name) != value:
                    set_key(str(path), name, value)
    return settings


def wait_ready(url: str, processes: list[subprocess.Popen],
               stop: threading.Event, timeout: int, backend: bool = False) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not stop.is_set():
        if any(child.poll() is not None for child in processes):
            raise StartError("A service exited early. Check backend/runtime/local-start logs.")
        try:
            with opener.open(url, timeout=1) as response:
                if response.status == 200:
                    if backend and json.load(response).get("service") != "nemothello":
                        raise StartError("The backend health check reached a different service.")
                    return
        except urllib.error.HTTPError as exc:
            raise StartError(f"Service returned HTTP {exc.code}. Check startup logs: {url}") from exc
        except OSError:
            pass
        stop.wait(0.2)
    if not stop.is_set():
        raise StartError(f"Service was not ready within {timeout} seconds: {url}")


def stop_services(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Nemothello locally using installed dependencies.")
    parser.add_argument("--backend-port", type=port_number, default=8000)
    parser.add_argument("--web-port", type=port_number, default=3000)
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser after startup")
    parser.add_argument("--check", action="store_true", help="Check the environment without changing configuration or starting services")
    args = parser.parse_args()
    node = check_environment(args.backend_port, args.web_port)
    if args.check:
        prepare_configuration(args.backend_port, write=False)
        print("Environment check passed. Startup will fill missing configuration and synchronize service credentials.", flush=True)
        return 0

    log_directory = BACKEND / "runtime/local-start"
    log_directory.mkdir(parents=True, exist_ok=True)
    processes = []
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, lambda *_: stop.set())
    with (log_directory / "launcher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StartError("The launcher is already running. Close its terminal window first.") from exc
        settings = prepare_configuration(args.backend_port, write=True)
        common_env = os.environ.copy()
        common_env.update({
            "BACKEND_SERVICE_TOKEN": settings.backend_service_token.get_secret_value(),
            "EDAX_EXECUTABLE": str(settings.edax_executable),
            "EDAX_EVAL_FILE": str(settings.edax_eval_file),
            "EDAX_VERSION": settings.edax_version,
            "BACKEND_URL": f"http://127.0.0.1:{args.backend_port}",
        })
        with (log_directory / "backend.log").open("w") as backend_log, \
                (log_directory / "web.log").open("w") as web_log:
            try:
                print("Starting local services…", flush=True)
                processes.append(subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "nemothello.main:app",
                     "--host", "127.0.0.1", "--port", str(args.backend_port)],
                    cwd=BACKEND, env=common_env, stdout=backend_log,
                    stderr=subprocess.STDOUT, start_new_session=True,
                ))
                wait_ready(common_env["BACKEND_URL"] + "/health", processes,
                           stop, 30, backend=True)
                if stop.is_set():
                    return 0
                processes.append(subprocess.Popen(
                    [node, str(ROOT / "node_modules/next/dist/bin/next"), "dev",
                     "--hostname", "127.0.0.1", "--port", str(args.web_port)],
                    cwd=WEB, env=common_env, stdout=web_log,
                    stderr=subprocess.STDOUT, start_new_session=True,
                ))
                url = f"http://127.0.0.1:{args.web_port}"
                wait_ready(url, processes, stop, 60)
                if not stop.is_set():
                    print(f"Running: {url}\nPress Ctrl+C to stop both services.\nLogs: {log_directory}", flush=True)
                    if not settings.token_factory_api_key.get_secret_value():
                        print("Games, hints, and branches are available. Nemotron reviews are not configured.", flush=True)
                    if not args.no_browser:
                        webbrowser.open(url)
                while not stop.wait(0.5):
                    if any(process.poll() is not None for process in processes):
                        raise StartError("A service exited unexpectedly. Check the startup logs.")
                return 0
            finally:
                stop_services(processes)
                print("Local services stopped.", flush=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (StartError, ValueError) as error:
        print(f"Startup failed: {error}", file=sys.stderr)
        sys.exit(1)
