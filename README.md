# Custom Configuration Tracker

A containerized Configuration Management Database (CMDB) that uses **Git** as its history backend. A lightweight agent monitors host filesystems (mounted read-only) and ships changed files to a **Flask** REST API, which commits them to a git repository and records metadata in **PostgreSQL**.

## Architecture

```
┌─────────────────────────────────────────────┐
│                  Host Machine               │
│                                             │
│  /etc, /usr/local/etc, ...                  │
│        │  (read-only bind mount)            │
│        ▼                                    │
│  ┌───────────┐   HTTP    ┌─────────────┐    │
│  │   agent   │ ────────► │     api     │    │
│  │ (Python)  │           │   (Flask)   │    │
│  └───────────┘           └──────┬──────┘    │
│                                 │           │
│                     ┌───────────┴────────┐  │
│                     │      postgres      │  │
│                     │  (metadata index)  │  │
│                     └────────────────────┘  │
│                                             │
│                     git repo (named volume) │
│                     └── <hostname>/         │
│                         └── etc/nginx/...   │
└─────────────────────────────────────────────┘
```

**Three containers, one network:**

| Container | Role |
|-----------|------|
| `postgres` | Stores hosts, tracked file paths, and snapshot metadata |
| `api` | Flask + gunicorn REST API; owns the git repository for full file history |
| `agent` | Scans monitored paths (read-only mount), hashes files, POSTs changes to the API |

Change detection is dual-mode: **watchdog** (inotify/FSEvents) for near-instant detection, plus a **periodic full scan** as a reliable fallback. The server performs its own hash dedup so duplicate submissions are always safe.

## Requirements

- Docker and Docker Compose v2
- Git (only needed on the host to clone this repo)

## Getting Started

**1. Clone and configure**

```bash
git clone <repo-url>
cd custom-configuration-tracker
cp .env.example .env
```

Edit `.env`:

```bash
# Strong password for the cmdb postgres user
POSTGRES_PASSWORD=changeme

# Flask secret key — generate with:
# python -c "import secrets; print(secrets.token_hex(32))"
API_SECRET_KEY=changeme

# Stable UUID for this agent — generate once with:
# python -c "import uuid; print(uuid.uuid4())"
AGENT_ID=00000000-0000-0000-0000-000000000000

# Human-readable name for this host in the CMDB
AGENT_HOSTNAME=my-server
```

**2. Configure monitored paths**

Edit the `agent` service volumes in `docker-compose.yml`:

```yaml
volumes:
  - /etc:/monitored/etc:ro
  - /usr/local/etc:/monitored/usr/local/etc:ro
  # Add more paths here — always :ro
```

**3. Start the stack**

```bash
docker compose up --build -d
```

Startup order is enforced via health checks: postgres → api → agent.

**4. Verify**

```bash
# API health
curl http://localhost:5000/api/v1/health

# List registered hosts
curl http://localhost:5000/api/v1/hosts
```

## API Reference

All endpoints return `application/json` unless noted. Errors include `{"error": "..."}`.

### Hosts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/hosts` | List all known hosts |
| `GET` | `/api/v1/hosts/<hostname>` | Host detail with file count and last snapshot time |
| `POST` | `/api/v1/hosts/register` | Agent self-registration (called automatically on startup) |

**Register body:**
```json
{ "hostname": "web-01", "agent_id": "<uuid>", "metadata": {} }
```

### Configs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/configs/<hostname>` | List tracked files for a host |
| `GET` | `/api/v1/configs/<hostname>/history` | Snapshot history for a file |
| `GET` | `/api/v1/configs/<hostname>/content` | Raw file content at a specific commit |
| `GET` | `/api/v1/configs/<hostname>/diff` | Unified diff between two commits |
| `POST` | `/api/v1/configs/submit` | Submit a changed file (multipart/form-data) |

**History:** `GET /api/v1/configs/web-01/history?file_path=/etc/nginx/nginx.conf&limit=20`

**Diff:** `GET /api/v1/configs/web-01/diff?file_path=/etc/nginx/nginx.conf&from_commit=abc123&to_commit=def456`

Omit `to_commit` to diff against `HEAD`.

**Content:** `GET /api/v1/configs/web-01/content?file_path=/etc/nginx/nginx.conf&commit_sha=abc123`

Returns `application/octet-stream`.

### Health

`GET /api/v1/health` — Returns `{"status": "ok", "db": "ok", "git": "ok"}`. Used by Docker healthcheck.

## Agent Behavior

- On startup, registers with the API (retries with exponential backoff until successful).
- Starts a **watchdog** observer on all monitored paths for fast event-driven detection.
- Runs a **full scan** every `poll_interval_seconds` (default: 60) as a safety net.
- Skips files larger than `max_file_size_mb` (default: 10 MB) and symlinks.
- In-memory hash cache prevents redundant API calls within a session; the server's own dedup handles restarts.

### Agent Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENT_ID` | Yes | Stable UUID identifying this agent |
| `CMDB_API_URL` | Yes | Base URL of the API (e.g. `http://api:5000`) |
| `AGENT_HOSTNAME` | No | Display name; defaults to container hostname |
| `MONITORED_PATHS` | No | Comma-separated paths to scan; overrides `config.yml` |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING` (default: `INFO`) |
| `CONFIG_PATH` | No | Path to `config.yml` (default: `/app/config.yml`) |

## Git Repository Layout

The API maintains a git repo at `/var/cmdb/repo` (persisted in a named volume). Files are stored as:

```
/var/cmdb/repo/
└── <hostname>/
    └── <path-relative-to-root>/
        └── nginx.conf    ← always the latest committed content
```

Every change is a git commit. The full history is browsable inside the `api` container:

```bash
docker compose exec api git -C /var/cmdb/repo log --oneline
docker compose exec api git -C /var/cmdb/repo log --oneline -- web-01/etc/nginx/nginx.conf
```

## Project Structure

```
custom-configuration-tracker/
├── docker-compose.yml
├── init.sql                   # PostgreSQL schema
├── .env.example
├── api/
│   ├── app.py                 # Flask app factory
│   ├── models.py              # SQLAlchemy models
│   ├── git_manager.py         # Thread-safe git operations
│   ├── requirements.txt
│   ├── Dockerfile
│   └── routes/
│       ├── hosts.py
│       └── configs.py
└── agent/
    ├── agent.py               # Watchdog + poll loop + API client
    ├── config.yml
    ├── requirements.txt
    └── Dockerfile
```

## Scaling and Production Notes

- **Multiple agents:** Deploy the agent container on each host you want to monitor. Each needs a unique `AGENT_ID` and `AGENT_HOSTNAME`. Point all agents at the same API URL.
- **Git write concurrency:** The API runs gunicorn with `--workers 1 --threads 4` and a `threading.Lock` around all git writes. If you need multi-worker scaling, swap the threading lock for a `filelock.FileLock`.
- **Secrets:** The `.env` file approach is suitable for single-host deployments. For production, replace with Docker secrets or an external vault.
- **Exposed port:** The API is exposed on `localhost:5000` by default. Remove the `ports:` mapping from `docker-compose.yml` if agents are co-located and external access is not needed.
