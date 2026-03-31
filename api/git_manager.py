import subprocess
import threading
from pathlib import Path, PurePosixPath


class GitManager:
    def __init__(self, repo_path: str, user_name: str = "CMDB API", user_email: str = "cmdb@localhost"):
        self.repo_path = Path(repo_path)
        self.repo_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        if not (self.repo_path / ".git").exists():
            self._run(["git", "init", "--initial-branch=main"])
            self._run(["git", "config", "user.name", user_name])
            self._run(["git", "config", "user.email", user_email])
            # create an initial commit so diffs have a base
            self._run(["git", "commit", "--allow-empty", "-m", "Initial commit"])

    def _run(self, cmd: list, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=check,
        )

    def _safe_rel(self, hostname: str, file_path: str) -> PurePosixPath:
        """Build a safe relative path inside the repo, preventing traversal."""
        # Strip leading slash, normalize
        stripped = file_path.lstrip("/")
        rel = PurePosixPath(hostname) / stripped

        # Reject any path component that is ".."
        for part in rel.parts:
            if part == "..":
                raise ValueError(f"Path traversal detected in: {file_path!r}")

        return rel

    def write_and_commit(self, hostname: str, file_path: str, content: bytes, commit_message: str) -> str:
        """Write file content to the repo and commit. Returns new commit SHA."""
        with self._lock:
            rel = self._safe_rel(hostname, file_path)
            dest = self.repo_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

            self._run(["git", "add", str(rel)])
            self._run(["git", "commit", "-m", commit_message])

            result = self._run(["git", "rev-parse", "HEAD"])
            return result.stdout.strip()

    def get_diff(self, from_commit: str, to_commit: str, hostname: str, file_path: str) -> str:
        """Return unified diff text between two commits for a specific file."""
        rel = self._safe_rel(hostname, file_path)
        result = self._run(
            ["git", "diff", from_commit, to_commit, "--", str(rel)],
            check=False,
        )
        return result.stdout

    def get_file_at_commit(self, commit_sha: str, hostname: str, file_path: str) -> bytes:
        """Return raw file content at the given commit."""
        rel = self._safe_rel(hostname, file_path)
        result = subprocess.run(
            ["git", "show", f"{commit_sha}:{rel}"],
            cwd=str(self.repo_path),
            capture_output=True,
            check=True,
        )
        return result.stdout

    def get_log(self, hostname: str, file_path: str, limit: int = 50) -> list[dict]:
        """Return commit log for a specific file, newest first."""
        rel = self._safe_rel(hostname, file_path)
        result = self._run(
            ["git", "log", f"--max-count={limit}", "--format=%H|%aI|%s", "--follow", "--", str(rel)],
            check=False,
        )
        entries = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append({"sha": parts[0], "timestamp": parts[1], "message": parts[2]})
        return entries

    def health_check(self) -> bool:
        """Return True if the git repo is accessible and operational."""
        try:
            result = self._run(["git", "status"], check=False)
            return result.returncode == 0
        except Exception:
            return False
