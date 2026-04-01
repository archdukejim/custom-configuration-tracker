#!/usr/bin/env python3
"""CMDB Agent — monitors configured paths and ships changed files to the API."""

import hashlib
import logging
import os
import platform
import re
import socket
import sys
import time
from pathlib import Path
from typing import Optional

import requests
import yaml

try:
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def load_config(path: str = "/app/config.yml") -> dict:
    with open(path) as f:
        raw = f.read()
    # Interpolate ${ENV_VAR} references
    raw = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), raw)
    return yaml.safe_load(raw)


def sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError) as e:
        logging.warning("Cannot hash %s: %s", path, e)
        return None


class ApiClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def register(self, hostname: str, agent_id: str, metadata: dict) -> bool:
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/hosts/register",
                json={"hostname": hostname, "agent_id": agent_id, "metadata": metadata},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            logging.info("Registered as hostname=%s host_id=%s", hostname, resp.json().get("host_id"))
            return True
        except Exception as e:
            logging.error("Registration failed: %s", e)
            return False

    def submit(self, agent_id: str, file_path: str, file_hash: str, content: bytes) -> Optional[dict]:
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/configs/submit",
                data={"agent_id": agent_id, "file_path": file_path, "file_hash": file_hash},
                files={"content": ("content", content, "application/octet-stream")},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            logging.error("Submit HTTP error for %s: %s — %s", file_path, e, e.response.text if e.response else "")
            return None
        except Exception as e:
            logging.error("Submit failed for %s: %s", file_path, e)
            return None


class Agent:
    def __init__(self, config: dict):
        self.config = config
        self.agent_id = os.environ.get("AGENT_ID", "").strip()
        if not self.agent_id:
            logging.critical("AGENT_ID environment variable is required")
            sys.exit(1)

        self.hostname = os.environ.get("AGENT_HOSTNAME", "").strip() or socket.gethostname()
        self.max_bytes = int(config["agent"].get("max_file_size_mb", 10)) * 1024 * 1024
        self.poll_interval = int(config["agent"].get("poll_interval_seconds", 60))
        self.use_watchdog = bool(config["agent"].get("use_watchdog", True)) and WATCHDOG_AVAILABLE

        # Resolve monitored paths from config, falling back to MONITORED_PATHS env var
        env_paths = os.environ.get("MONITORED_PATHS", "")
        if env_paths:
            self.monitored_paths = [Path(p.strip()) for p in env_paths.split(",") if p.strip()]
        else:
            self.monitored_paths = [Path(p) for p in config.get("monitored_paths", ["/monitored"])]

        api_cfg = config["api"]
        self.api = ApiClient(api_cfg["base_url"], int(api_cfg.get("timeout_seconds", 10)))
        self.hash_cache: dict[str, str] = {}  # file_path -> last submitted hash

    def _metadata(self) -> dict:
        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "python": platform.python_version(),
            "monitored_paths": [str(p) for p in self.monitored_paths],
        }

    def _register_with_retry(self):
        backoff = 5
        while True:
            if self.api.register(self.hostname, self.agent_id, self._metadata()):
                return
            logging.warning("Retrying registration in %ds…", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _should_skip(self, path: Path) -> bool:
        """Skip symlinks, non-files, and files exceeding max size."""
        if path.is_symlink():
            return True
        if not path.is_file():
            return True
        try:
            if path.stat().st_size > self.max_bytes:
                logging.debug("Skipping oversized file: %s", path)
                return True
        except OSError:
            return True
        return False

    def submit_file(self, path: Path):
        if self._should_skip(path):
            return

        file_hash = sha256_file(path)
        if file_hash is None:
            return

        file_path_str = str(path)
        if self.hash_cache.get(file_path_str) == file_hash:
            return  # No change since last submission

        try:
            content = path.read_bytes()
        except (PermissionError, OSError) as e:
            logging.warning("Cannot read %s: %s", path, e)
            return

        result = self.api.submit(self.agent_id, file_path_str, file_hash, content)
        if result is None:
            return

        status = result.get("status")
        if status == "unchanged":
            logging.debug("Server confirmed unchanged: %s", path)
        else:
            logging.info("Submitted %s → hash %s", path, result.get("content_hash", "")[:12])

        self.hash_cache[file_path_str] = file_hash

    def scan_all(self):
        for root in self.monitored_paths:
            if not root.exists():
                logging.warning("Monitored path does not exist: %s", root)
                continue
            for path in root.rglob("*"):
                self.submit_file(path)

    def run(self):
        logging.info("CMDB Agent starting — hostname=%s agent_id=%s", self.hostname, self.agent_id)
        logging.info("Monitored paths: %s", self.monitored_paths)

        self._register_with_retry()

        if self.use_watchdog:
            self._start_watchdog()

        logging.info("Starting poll loop (interval=%ds)", self.poll_interval)
        while True:
            self.scan_all()
            time.sleep(self.poll_interval)

    def _start_watchdog(self):
        agent = self

        class Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if not event.is_directory:
                    agent.submit_file(Path(event.src_path))

            def on_created(self, event):
                if not event.is_directory:
                    agent.submit_file(Path(event.src_path))

        observer = Observer()
        for root in self.monitored_paths:
            if root.exists():
                observer.schedule(Handler(), str(root), recursive=True)
                logging.info("Watchdog watching: %s", root)
        observer.start()
        logging.info("Watchdog observer started")


def main():
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    setup_logging(log_level)

    config_path = os.environ.get("CONFIG_PATH", "/app/config.yml")
    config = load_config(config_path)

    agent = Agent(config)
    agent.run()


if __name__ == "__main__":
    main()
