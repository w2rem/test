"""uf5vmjt — Streamlit system monitor: stats, shell, logs.

Sections (sidebar): stats (memory/CPU/geo/cluster/versions), shell (command
runner with rendered history), logs (unified event stream, incl. Go sidecar).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from stat import S_ISDIR, S_ISLNK
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Palette — white base, muted grays, single steel-blue accent family.
# ---------------------------------------------------------------------------

COLOR_BG = "#FFFFFF"
COLOR_PANEL = "#F4F6F8"
COLOR_BORDER = "#E2E7EB"
COLOR_TEXT = "#2F3E46"
COLOR_MUTED = "#6C7A86"
COLOR_ACCENT = "#4A7FA5"
COLOR_ACCENT_SOFT = "#A8C3D1"
COLOR_ACCENT_PALE = "#E8EDEF"
COLOR_OK = "#5A9E6F"
COLOR_WARN = "#C9A227"
COLOR_ERR = "#C26D6D"

# Memory bar segments (single 0..max stacked column).
COLOR_MEM_USED = "#4A7FA5"  # steel blue — application memory
COLOR_MEM_CACHE = "#A8C3D1"  # pale steel — page cache / reclaimable
COLOR_MEM_FREE = "#E8EDEF"  # pale gray — free

# Bundled runtime icons (inline: zero local-file/network dependency).
ICON_GO = '''<svg height="78" viewBox="0 0 207 78" width="207" xmlns="http://www.w3.org/2000/svg"><g fill="#211f1f" fill-rule="evenodd"><path d="m16.2 24.1c-.4 0-.5-.2-.3-.5l2.1-2.7c.2-.3.7-.5 1.1-.5h35.7c.4 0 .5.3.3.6l-1.7 2.6c-.2.3-.7.6-1 .6z"/><path d="m1.1 33.3c-.4 0-.5-.2-.3-.5l2.1-2.7c.2-.3.7-.5 1.1-.5h45.6c.4 0 .6.3.5.6l-.8 2.4c-.1.4-.5.6-.9.6z"/><path d="m25.3 42.5c-.4 0-.5-.3-.3-.6l1.4-2.5c.2-.3.6-.6 1-.6h20c.4 0 .6.3.6.7l-.2 2.4c0 .4-.4.7-.7.7z"/><g transform="translate(55)"><path d="m74.1 22.3c-6.3 1.6-10.6 2.8-16.8 4.4-1.5.4-1.6.5-2.9-1-1.5-1.7-2.6-2.8-4.7-3.8-6.3-3.1-12.4-2.2-18.1 1.5-6.8 4.4-10.3 10.9-10.2 19 .1 8 5.6 14.6 13.5 15.7 6.8.9 12.5-1.5 17-6.6.9-1.1 1.7-2.3 2.7-3.7-3.6 0-8.1 0-19.3 0-2.1 0-2.6-1.3-1.9-3 1.3-3.1 3.7-8.3 5.1-10.9.3-.6 1-1.6 2.5-1.6h36.4c-.2 2.7-.2 5.4-.6 8.1-1.1 7.2-3.8 13.8-8.2 19.6-7.2 9.5-16.6 15.4-28.5 17-9.8 1.3-18.9-.6-26.9-6.6-7.4-5.6-11.6-13-12.7-22.2-1.3-10.9 1.9-20.7 8.5-29.3 7.1-9.3 16.5-15.2 28-17.3 9.4-1.7 18.4-.6 26.5 4.9 5.3 3.5 9.1 8.3 11.6 14.1.6.9.2 1.4-1 1.7z"/><path d="m107.2 77.6c-9.1-.2-17.4-2.8-24.4-8.8-5.9-5.1-9.6-11.6-10.8-19.3-1.8-11.3 1.3-21.3 8.1-30.2 7.3-9.6 16.1-14.6 28-16.7 10.2-1.8 19.8-.8 28.5 5.1 7.9 5.4 12.8 12.7 14.1 22.3 1.7 13.5-2.2 24.5-11.5 33.9-6.6 6.7-14.7 10.9-24 12.8-2.7.5-5.4.6-8 .9zm23.8-40.4c-.1-1.3-.1-2.3-.3-3.3-1.8-9.9-10.9-15.5-20.4-13.3-9.3 2.1-15.3 8-17.5 17.4-1.8 7.8 2 15.7 9.2 18.9 5.5 2.4 11 2.1 16.3-.6 7.9-4.1 12.2-10.5 12.7-19.1z" fill-rule="nonzero"/></g></g></svg>'''
ICON_PYTHON = '''<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><g fill="#211f1f" fill-rule="evenodd"><path d="M14.31.18l.9.2.73.26.59.3.45.32.34.34.25.34.16.33.1.3.04.26.02.2-.01.13V8.5l-.05.63-.13.55-.21.46-.26.38-.3.31-.33.25-.35.19-.35.14-.33.1-.3.07-.26.04-.21.02H8.83l-.69.05-.59.14-.5.22-.41.27-.33.32-.27.35-.2.36-.15.37-.1.35-.07.32-.04.27-.02.21v3.06H3.23l-.21-.03-.28-.07-.32-.12-.35-.18-.36-.26-.36-.36-.35-.46-.32-.59-.28-.73-.21-.88-.14-1.05L0 11.97l.06-1.22.16-1.04.24-.87.32-.71.36-.57.4-.44.42-.33.42-.24.4-.16.36-.1.32-.05.24-.01h.16l.06.01h8.16v-.83H6.24l-.01-2.75-.02-.37.05-.34.11-.31.17-.28.25-.26.31-.23.38-.2.44-.18.51-.15.58-.12.64-.1.71-.06.77-.04.84-.02 1.27.05 1.07.13zm-6.3 1.98l-.23.33-.08.41.08.41.23.34.33.22.41.09.41-.09.33-.22.23-.34.08-.41-.08-.41-.23-.33-.33-.22-.41-.09-.41.09-.33.22zM21.1 6.11l.28.06.32.12.35.18.36.27.36.35.35.47.32.59.28.73.21.88.14 1.04.05 1.23-.06 1.23-.16 1.04-.24.86-.32.71-.36.57-.4.45-.42.33-.42.24-.4.16-.36.09-.32.05-.24.02-.16-.01h-8.22v.82h5.84l.01 2.76.02.36-.05.34-.11.31-.17.29-.25.25-.31.24-.38.2-.44.17-.51.15-.58.13-.64.09-.71.07-.77.04-.84.01-1.27-.04-1.07-.14-.9-.2-.73-.25-.59-.3-.45-.33-.34-.34-.25-.34-.16-.33-.1-.3-.04-.25-.02-.2.01-.13v-5.34l.05-.64.13-.54.21-.46.26-.38.3-.32.33-.24.35-.2.35-.14.33-.1.3-.06.26-.04.21-.02.13-.01h5.84l.69-.05.59-.14.5-.21.41-.28.33-.32.27-.35.2-.36.15-.36.1-.35.07-.32.04-.28.02-.21V6.07h2.09l.14.01.21.03zm-6.47 14.25l-.23.33-.08.41.08.41.23.33.33.23.41.08.41-.08.33-.23.23-.33.08-.41-.08-.41-.23-.33-.33-.23-.41-.08-.41.08-.33.23z"/></g></svg>'''
ICON_TAILSCALE = '''<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">  <path d="M3.5 17.5C5.43299 17.5 6.99999 15.933 6.99999 14C6.99999 12.067 5.43299 10.5 3.5 10.5C1.567 10.5 0 12.067 0 14C0 15.933 1.567 17.5 3.5 17.5Z" fill="#232222"/>  <path d="M14 17.5C15.933 17.5 17.5 15.933 17.5 14C17.5 12.067 15.933 10.5 14 10.5C12.067 10.5 10.5 12.067 10.5 14C10.5 15.933 12.067 17.5 14 17.5Z" fill="#232222"/>  <path d="M14 28C15.933 28 17.5 26.433 17.5 24.5C17.5 22.567 15.933 21 14 21C12.067 21 10.5 22.567 10.5 24.5C10.5 26.433 12.067 28 14 28Z" fill="#232222"/>  <path d="M24.5 17.5C26.433 17.5 28 15.933 28 14C28 12.067 26.433 10.5 24.5 10.5C22.567 10.5 21 12.067 21 14C21 15.933 22.567 17.5 24.5 17.5Z" fill="#232222"/>  <g opacity="0.4">    <path d="M3.5 28C5.43299 28 6.99999 26.433 6.99999 24.5C6.99999 22.567 5.43299 21 3.5 21C1.567 21 0 22.567 0 24.5C0 26.433 1.567 28 3.5 28Z" fill="#232222"/>    <path d="M24.5 28C26.433 28 28 26.433 28 24.5C28 22.567 26.433 21 24.5 21C22.567 21 21 22.567 21 24.5C21 26.433 22.567 28 24.5 28Z" fill="#232222"/>    <path d="M3.5 6.99999C5.43299 6.99999 6.99999 5.43299 6.99999 3.5C6.99999 1.567 5.43299 0 3.5 0C1.567 0 0 1.567 0 3.5C0 5.43299 1.567 6.99999 3.5 6.99999Z" fill="#232222"/>    <path d="M14 6.99999C15.933 6.99999 17.5 5.43299 17.5 3.5C17.5 1.567 15.933 0 14 0C12.067 0 10.5 1.567 10.5 3.5C10.5 5.43299 12.067 6.99999 14 6.99999Z" fill="#232222"/>    <path d="M24.5 6.99999C26.433 6.99999 28 5.43299 28 3.5C28 1.567 26.433 0 24.5 0C22.567 0 21 1.567 21 3.5C21 5.43299 22.567 6.99999 24.5 6.99999Z" fill="#232222"/>  </g></svg>'''

ICON_SVGS = {"go": ICON_GO, "python": ICON_PYTHON, "tailscale": ICON_TAILSCALE}

GEO_URL = "https://api.ip.sb/geoip"
GEO_TTL_SEC = 300
CLUSTER_TTL_SEC = 600
GO_LOG_PATH = os.environ.get("UF5VMJT_GO_LOG", "/tmp/uf5vmjt-go.log").strip()
SHELL_TIMEOUT_SEC = 15
SHELL_HISTORY_LIMIT = 20


# ---------------------------------------------------------------------------
# Event log — single source for the logs section.
# ---------------------------------------------------------------------------

def _now_tag() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def log_event(level: str, message: str, source: str = "main") -> None:
    """Append one line to the in-memory event stream (used by logs section)."""
    import streamlit as st

    events = st.session_state.setdefault("uf5_events", [])
    events.append({"ts": _now_tag(), "level": level, "source": source, "msg": message})
    del events[:-500]


def ingest_go_events() -> int:
    """Tail JSON-lines from the Go sidecar log into the event stream.

    Expected line shape: {"level": "info", "msg": "..."}. Returns lines added.
    """
    import streamlit as st

    if not os.path.isfile(GO_LOG_PATH):
        return 0
    try:
        offset = int(st.session_state.get("uf5_go_offset", 0) or 0)
    except (TypeError, ValueError):
        offset = 0
    added = 0
    try:
        with open(GO_LOG_PATH, "rb") as f:
            f.seek(offset)
            for raw in f:
                try:
                    obj = json.loads(raw.decode(errors="replace"))
                except ValueError:
                    continue
                log_event(str(obj.get("level", "info")), str(obj.get("msg", "")), source="go")
                added += 1
            st.session_state["uf5_go_offset"] = f.tell()
    except OSError:
        return 0
    return added


# ---------------------------------------------------------------------------
# Go sidecar — ./worker next to the launch dir, background, lines to main.
# ---------------------------------------------------------------------------

WORKER_PORT = int(os.environ.get("WORKER_PORT", "6549") or 6549)
WORKER_BIN_ENV = "UF5VMJT_WORKER_BIN"
# Env keys the sidecar inherits; missing ones are seeded from st.secrets so a
# Cloud deploy (secrets-only, no shell env) still configures the worker.
# Values never hit the logs.
WORKER_ENV_KEYS = ("PG_DATABASE_URL", "STREAMLIT_SESSION_TOKEN", "STREAMLIT_SESSION",
                   "APP_HOST", "APP_URL", "UP_EVERY", "WORKER_PORT")
_WORKER_PROC = None


def seed_worker_env_from_secrets() -> None:
    """Copy WORKER_ENV_KEYS from st.secrets into os.environ when unset.

    Cloud deploys are secrets-only (no shell env); the sidecar inherits
    os.environ, so without this it would never see PG_DATABASE_URL or the
    session token. Key names (never values) go to the event log.
    Never raises.
    """
    import streamlit as st

    try:
        secrets = st.secrets
    except Exception:  # noqa: BLE001
        return
    for key in WORKER_ENV_KEYS:
        if os.environ.get(key):
            continue
        try:
            value = secrets.get(key, "")
        except Exception:  # noqa: BLE001
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        os.environ[key] = str(value).strip() if isinstance(value, str) else str(value)
        log_event("debug", f"secret {key} applied to worker env", source="go")


def find_worker_binary() -> str:
    """Locate the worker binary: env override, ./worker (launch dir), or next
    to main.py. Empty when nothing is shipped."""
    override = (os.environ.get(WORKER_BIN_ENV) or "").strip()
    if override and os.path.isfile(override):
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(os.getcwd(), "worker"),
                 os.path.join(here, "worker")):
        if os.path.isfile(cand):
            return cand
    return ""


def worker_alive() -> bool:
    """True when our child is running or something answers /health on port."""
    proc = _WORKER_PROC
    try:
        if proc is not None and proc.poll() is None:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{WORKER_PORT}/health",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=1) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _pump_worker_logs(proc, path: str) -> None:
    """Forward child stdout lines to the Go JSON-lines log (daemon thread).

    Never touches session_state (wrong context here) — ingest_go_events()
    tails the file back into the event stream on the script thread.
    """
    try:
        assert proc.stdout is not None
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            for line in proc.stdout:
                text = line.strip()
                if not text:
                    continue
                low = text.lower()
                level = ("error" if "error" in low or "fatal" in low
                         else "warn" if "warn" in low else "info")
                try:
                    f.write(json.dumps({"level": level, "msg": text[:500]}) + "\n")
                    f.flush()
                except OSError:
                    break
    except Exception:  # noqa: BLE001
        pass


def ensure_worker() -> None:
    """Spawn ./worker once per Python process; no-op when already up.

    Child inherits APP_URL (set earlier in main) and gets its own PORT so it
    never fights the hosting port. Never raises — failures become log lines.
    """
    import streamlit as st

    global _WORKER_PROC
    try:
        if worker_alive():
            return
        if st.session_state.get("uf5_worker_started"):
            return
        binary = find_worker_binary()
        if not binary:
            if not st.session_state.get("uf5_worker_missing_logged"):
                st.session_state["uf5_worker_missing_logged"] = True
                log_event("debug", "no ./worker next to launch dir — sidecar off",
                          source="go")
            return
        try:
            if not os.access(binary, os.X_OK):
                os.chmod(binary, 0o755)
        except OSError:
            pass
        env = dict(os.environ)
        env["PORT"] = str(WORKER_PORT)
        try:
            import threading

            proc = subprocess.Popen(
                [binary], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=os.path.dirname(binary) or None,
                env=env,
            )
        except Exception as e:  # noqa: BLE001
            log_event("warn", f"worker spawn failed: {e}", source="go")
            return
        _WORKER_PROC = proc
        thread = threading.Thread(target=_pump_worker_logs,
                                  args=(proc, GO_LOG_PATH), daemon=True)
        thread.start()
        st.session_state["uf5_worker_started"] = True
        log_event("ok", f"worker started: {binary} on :{WORKER_PORT} "
                        f"app={os.environ.get('APP_URL', '?')} "
                        f"every={os.environ.get('UP_EVERY', '?')} min",
                  source="go")
    except Exception as e:  # noqa: BLE001
        try:
            log_event("warn", f"worker ensure failed: {e}", source="go")
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# /proc readers — memory, CPU.
# ---------------------------------------------------------------------------

def read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into {key: kB}. Empty dict when unavailable."""
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, val = line.partition(":")
                parts = val.strip().split()
                if not parts:
                    continue
                try:
                    out[key.strip()] = int(parts[0])
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def memory_segments(mem: dict[str, int]) -> tuple[int, int, int, int]:
    """Return (total, used, cache, free) in kB.

    cache = Cached + Buffers + SReclaimable (reclaimable page cache).
    used  = total - free - cache, where free = MemFree.
    """
    total = mem.get("MemTotal", 0)
    free = mem.get("MemFree", 0)
    cache = mem.get("Cached", 0) + mem.get("Buffers", 0) + mem.get("SReclaimable", 0)
    used = max(total - free - cache, 0)
    return total, used, cache, free


def read_cpu_times() -> dict[str, tuple[int, int]]:
    """Return {cpuN: (total_jiffies, idle_jiffies)} from /proc/stat."""
    out: dict[str, tuple[int, int]] = {}
    try:
        with open("/proc/stat") as f:
            for line in f:
                if not line.startswith("cpu"):
                    continue
                parts = line.split()
                name = parts[0]
                if name == "cpu":
                    continue  # aggregate handled separately
                try:
                    nums = [int(x) for x in parts[1:]]
                except ValueError:
                    continue
                total = sum(nums)
                idle = (nums[3] if len(nums) > 3 else 0) + (nums[4] if len(nums) > 4 else 0)
                out[name] = (total, idle)
    except OSError:
        pass
    return out


def read_cpu_total() -> tuple[int, int]:
    """Return (total_jiffies, idle_jiffies) for the aggregate cpu line."""
    try:
        with open("/proc/stat") as f:
            for line in f:
                parts = line.split()
                if parts and parts[0] == "cpu":
                    nums = [int(x) for x in parts[1:]]
                    total = sum(nums)
                    idle = (nums[3] if len(nums) > 3 else 0) + (nums[4] if len(nums) > 4 else 0)
                    return total, idle
    except (OSError, ValueError):
        pass
    return 0, 0


def cpu_info() -> tuple[str, int, int]:
    """Return (model_name, physical_cores, logical_cores) from /proc/cpuinfo."""
    model = ""
    physical: set[str] = set()
    logical = 0
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    if not model:
                        model = line.partition(":")[2].strip()
                elif line.startswith("processor"):
                    logical += 1
                elif line.startswith("core id"):
                    physical.add(line.partition(":")[2].strip())
    except OSError:
        pass
    return model or "unknown", len(physical) or logical or 1, logical or 1


def fmt_mb(kb: int) -> str:
    return f"{kb / 1024:.0f} MB"


def fmt_gb(num_bytes: int) -> str:
    gb = num_bytes / (1024 ** 3)
    if gb >= 100:
        return f"{gb:.0f} GB"
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{num_bytes / (1024 ** 2):.0f} MB"


# ---------------------------------------------------------------------------
# Disk — filesystems + top consumers.
# ---------------------------------------------------------------------------

DISK_TOP_TTL_SEC = 120
DISK_SCAN_BUDGET_SEC = 6.0
# Process-level fallback cache (used when streamlit is unavailable, e.g. tests).
_PROCESS_CACHE: dict = {}

_PSEUDO_FS = {"proc", "sysfs", "devpts", "cgroup", "cgroup2", "tmpfs", "devtmpfs",
              "overlay", "shm", "mqueue", "debugfs", "tracefs", "fusectl", "configfs"}


def list_filesystems() -> list[dict]:
    """Mounted real filesystems, deduped by device, with usage numbers."""
    mounts: list[tuple[str, str]] = []
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                dev, point, fstype = parts[0], parts[1], parts[2]
                if fstype in _PSEUDO_FS or point.startswith(("/proc", "/sys", "/dev")):
                    continue
                mounts.append((dev, point))
    except OSError:
        mounts = [("", "/")]
    seen: set[int] = set()
    out: list[dict] = []
    for _dev, point in mounts:
        try:
            dev_id = os.stat(point).st_dev
        except OSError:
            continue
        if dev_id in seen:
            continue
        seen.add(dev_id)
        try:
            usage = shutil.disk_usage(point)
        except OSError:
            continue
        if usage.total <= 0:
            continue
        out.append({"mount": point, "total": usage.total,
                    "used": usage.used, "free": usage.free})
    return out


def top_dirs(root: str = "/", limit: int = 8) -> tuple[list[tuple[str, int]], bool]:
    """Depth-first size scan of root's children. Returns (items, truncated).

    Bounded by DISK_SCAN_BUDGET_SEC; stays on one device; skips unreadable.
    Results cached in session for DISK_TOP_TTL_SEC (process cache fallback).
    """
    try:
        import streamlit as st

        store: dict = st.session_state
    except ImportError:
        store = _PROCESS_CACHE

    now = time.monotonic()
    cached = store.get("uf5_dutop")
    ts = float(store.get("uf5_dutop_ts", 0) or 0)
    if cached and now - ts < DISK_TOP_TTL_SEC:
        return cached, False
    try:
        root_dev = os.stat(root).st_dev
    except OSError:
        return [], False
    sizes: dict[str, int] = {}
    truncated = False
    t0 = time.monotonic()
    try:
        children = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return [], False
    for child in children:
        if time.monotonic() - t0 > DISK_SCAN_BUDGET_SEC:
            truncated = True
            break
        try:
            if child.is_symlink():
                continue
            total = 0
            stack = [child.path]
            while stack:
                if time.monotonic() - t0 > DISK_SCAN_BUDGET_SEC:
                    truncated = True
                    stack.clear()
                    break
                cur = stack.pop()
                try:
                    stt = os.lstat(cur)
                except OSError:
                    continue
                if stt.st_dev != root_dev:
                    continue
                total += stt.st_blocks * 512
                if S_ISDIR(stt.st_mode) and not S_ISLNK(stt.st_mode):
                    try:
                        with os.scandir(cur) as it:
                            stack.extend(e.path for e in it)
                    except OSError:
                        continue
            # Count the top-level dir itself.
            try:
                total += os.lstat(child.path).st_blocks * 512
            except OSError:
                pass
            if total > 0:
                sizes[child.name] = total
        except OSError:
            continue
    items = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    store["uf5_dutop"] = items
    store["uf5_dutop_ts"] = now
    return items, truncated


def render_disk_panel() -> None:
    """Filesystems as 0..max stacked tracks + top consumer bars."""
    import streamlit as st

    fs_list = list_filesystems()
    if not fs_list:
        st.caption("disk info unavailable")
        return
    for idx, fs in enumerate(fs_list):
        total, used, free = fs["total"], fs["used"], fs["free"]
        pct = used / total * 100
        if idx > 0:
            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown(f"<span class='uf5-muted'>filesystem</span>  **`{fs['mount']}`**",
                    unsafe_allow_html=True)
        bar = (
            f'<div class="uf5-memseg" title="used {fmt_gb(used)}" '
            f'style="width:{pct:.2f}%;background:{COLOR_ACCENT}"></div>'
            f'<div class="uf5-memseg" title="free {fmt_gb(free)}" '
            f'style="width:{100 - pct:.2f}%;background:{COLOR_ACCENT_PALE}"></div>'
        )
        st.markdown(f'<div class="uf5-memtrack">{bar}</div>', unsafe_allow_html=True)
        # Every card gets a delta line so all three share one height (symmetry).
        m1, m2, m3 = st.columns(3)
        m1.metric("Total", fmt_gb(total), "capacity", delta_color="off")
        m2.metric("Used", fmt_gb(used), f"{pct:.1f}%")
        m3.metric("Free", fmt_gb(free), f"{100 - pct:.1f}%")

    st.divider()
    st.markdown("**Top consumers**  <span class='uf5-muted'>depth-1 scan of `/`, "
                "cached 2 min</span>", unsafe_allow_html=True)
    items, truncated = top_dirs()
    if not items:
        st.caption("directory scan unavailable")
        return
    top = items[0][1] if items else 1
    rows = []
    for i, (name, size) in enumerate(items):
        opacity = round(1 - i * 0.07, 2)
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;margin:7px 0;">'
            f'<div class="uf5-muted" style="width:26px;font-family:monospace;'
            f'font-size:12px;text-align:right;">{i + 1:02d}</div>'
            f'<div style="width:130px;text-align:right;font-family:monospace;'
            f'font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">/{name}</div>'
            f'<div class="uf5-memtrack" style="height:22px;flex:1;">'
            f'<div class="uf5-memseg" style="width:{size / top * 100:.2f}%;'
            f'background:{COLOR_ACCENT};opacity:{opacity}"></div></div>'
            f'<div style="width:90px;font-size:12px;font-weight:600;font-variant-numeric:tabular-nums;">{fmt_gb(size)}</div></div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
    if truncated:
        st.caption("scan hit the time budget — biggest entries shown first")


# ---------------------------------------------------------------------------
# Network — geo + Streamlit cluster.
# ---------------------------------------------------------------------------

def fetch_json(url: str, timeout: float = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "uf5vmjt/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode(errors="replace"))


def get_geo() -> dict:
    """Fetch api.ip.sb/geoip, cached in session for GEO_TTL_SEC."""
    import streamlit as st

    now = time.monotonic()
    cached = st.session_state.get("uf5_geo") or {}
    ts = float(st.session_state.get("uf5_geo_ts", 0) or 0)
    if cached and now - ts < GEO_TTL_SEC:
        return cached
    try:
        data = fetch_json(GEO_URL)
        st.session_state["uf5_geo"] = data
        st.session_state["uf5_geo_ts"] = now
        log_event("ok", "geo resolved via api.ip.sb/geoip", source="net")
        return data
    except Exception as e:  # noqa: BLE001
        log_event("warn", f"geo fetch failed: {e}", source="net")
        return cached


def app_host() -> str:
    """Public host of this app from the browser URL (empty when local/headless)."""
    try:
        import streamlit as st

        url = st.context.url
    except Exception:  # noqa: BLE001
        return ""
    if not url:
        return ""
    return urlparse(url).hostname or ""


def get_cluster() -> dict:
    """Resolve /api/v2/app/disambiguate for this host, cached CLUSTER_TTL_SEC."""
    import streamlit as st

    now = time.monotonic()
    cached = st.session_state.get("uf5_cluster") or {}
    ts = float(st.session_state.get("uf5_cluster_ts", 0) or 0)
    if cached and now - ts < CLUSTER_TTL_SEC:
        return cached
    host = app_host()
    if not host:
        return {}
    try:
        data = fetch_json(f"https://{host}/api/v2/app/disambiguate")
        st.session_state["uf5_cluster"] = data
        st.session_state["uf5_cluster_ts"] = now
        log_event("ok", f"cluster resolved: {data.get('cluster', '?')}", source="net")
        return data
    except Exception as e:  # noqa: BLE001
        log_event("warn", f"disambiguate failed: {e}", source="net")
        return cached


def probe_disambiguate(host: str, token: str) -> tuple[int, dict]:
    """GET /api/v2/app/disambiguate. Returns (http_code, body).

    -1 on transport error. Token goes into the Cookie header, never logs.
    Never raises.
    """
    headers = {"User-Agent": "uf5vmjt/1.0", "Accept": "application/json"}
    if token:
        headers["Cookie"] = f"streamlit_session={token}"
    req = urllib.request.Request(f"https://{host}/api/v2/app/disambiguate",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            try:
                return r.status, json.loads(r.read().decode(errors="replace"))
            except ValueError:
                return r.status, {}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(errors="replace")
            return e.code, json.loads(body) if body else {}
        except (ValueError, OSError):
            return e.code, {}
    except Exception:  # noqa: BLE001
        return -1, {}


def ensure_keepalive_config() -> None:
    """Probe app visibility once per session, then fix the keepalive config.

    Anonymous 404 -> warn the operator to set STREAMLIT_SESSION_TOKEN.
    Resolved app -> default UP_EVERY to 10m when unset (child inherits it).
    Never raises.
    """
    import streamlit as st

    if st.session_state.get("uf5_visibility_checked"):
        return
    st.session_state["uf5_visibility_checked"] = True
    host = app_host()
    if not host:
        return
    token = (os.environ.get("STREAMLIT_SESSION_TOKEN")
             or os.environ.get("STREAMLIT_SESSION") or "")
    code, data = probe_disambiguate(host, token)
    if code == 200:
        # Feed the geo card cache — render_geo_cluster() reuses it, no refetch.
        st.session_state["uf5_cluster"] = data
        st.session_state["uf5_cluster_ts"] = time.monotonic()
        if not os.environ.get("UP_EVERY"):
            os.environ["UP_EVERY"] = "10"
            log_event("debug", "UP_EVERY defaulted to 10 min", source="net")
        every = (os.environ.get("UP_EVERY") or "10").strip()
        display = f"{every} min" if every.isdigit() else every
        log_event("ok", f"app visible on {data.get('cluster', '?')} — "
                        f"keepalive every {display}",
                  source="net")
    elif code == 404 and not token:
        log_event("warn", "app invisible anonymously (disambiguate 404) — "
                          "if private, set STREAMLIT_SESSION_TOKEN to the owner "
                          "streamlit_session cookie value", source="net")
    elif code == 404:
        log_event("warn", "disambiguate 404 even with session — "
                          "token expired or app gone", source="net")
    elif code == -1:
        log_event("warn", "disambiguate unreachable — keepalive defaults apply",
                  source="net")


# Detailed vector flags (hjnilsson/country-flags on GitHub) via jsDelivr CDN.
FLAG_CDN = "https://cdn.jsdelivr.net/gh/hjnilsson/country-flags/svg"


def flag_url(country_code: str) -> str:
    """CDN URL of a detailed SVG flag, or empty when unknown."""
    code = (country_code or "").strip().lower()
    if len(code) != 2 or not code.isalpha():
        return ""
    return f"{FLAG_CDN}/{code}.svg"


def shard_color(cluster: str) -> str:
    """Deterministic muted accent per shard (e.g. shard-4)."""
    palette = ["#4A7FA5", "#5A9E6F", "#8A7FB5", "#B5894A", "#5FA8A0", "#A56A7F"]
    idx = sum(ord(c) for c in cluster) % len(palette)
    return palette[idx]


# ---------------------------------------------------------------------------
# Icons — normalized size, single accent recolor.
# ---------------------------------------------------------------------------

def load_icon(name: str, size_px: int = 44, color: str = COLOR_ACCENT) -> str:
    """Bundled SVG icon, normalized to one size with accent recolor."""
    svg = ICON_SVGS.get(name, "")
    if not svg:
        return ""
    svg = re.sub(r'fill="#21\w{4}"', f'fill="{color}"', svg)
    svg = re.sub(r'fill="#23\w{4}"', f'fill="{color}"', svg)
    svg = re.sub(r'width="\d+"', f'width="{size_px}"', svg, count=1)
    svg = re.sub(r'height="\d+"', f'height="{size_px}"', svg, count=1)
    if 'width="' not in svg:
        svg = svg.replace("<svg", f'<svg width="{size_px}" height="{size_px}"', 1)
    return svg


# ---------------------------------------------------------------------------
# Versions — spinner while resolving, version text after.
# ---------------------------------------------------------------------------

def resolve_python_version() -> str:
    return platform.python_version()


def resolve_go_version() -> str:
    go = shutil.which("go")
    if not go:
        return "not installed"
    try:
        out = subprocess.run([go, "version"], capture_output=True, text=True, timeout=10)
        m = re.search(r"go(\d+\.\d+(?:\.\d+)?)", (out.stdout or "") + (out.stderr or ""))
        return m.group(1) if m else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "error"


def resolve_tailscale_version() -> str:
    ts = shutil.which("tailscale") or shutil.which("tailscaled")
    if not ts:
        for cand in ("/tmp/tailit", os.path.expanduser("~/.local/bin")):
            try:
                for entry in os.listdir(cand):
                    if entry == "tailscale":
                        ts = os.path.join(cand, entry)
                        break
            except OSError:
                continue
            if ts:
                break
    if not ts:
        return "not installed"
    try:
        out = subprocess.run([ts, "version"], capture_output=True, text=True, timeout=10)
        m = re.search(r"(\d+\.\d+\.\d+)", (out.stdout or "") + (out.stderr or ""))
        return m.group(1) if m else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "error"


# ---------------------------------------------------------------------------
# Shell — one-line runner with rendered history.
# ---------------------------------------------------------------------------

def run_shell_command(cmd: str, cwd: str) -> dict:
    """Run cmd with a timeout. Returns {cmd, cwd, rc, out, err, ms}. Never raises."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd or None, capture_output=True, text=True,
            timeout=SHELL_TIMEOUT_SEC, executable="/bin/bash",
        )
        return {"cmd": cmd, "cwd": cwd, "rc": proc.returncode,
                "out": proc.stdout or "", "err": proc.stderr or "",
                "ms": int((time.monotonic() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "cwd": cwd, "rc": 124, "out": "",
                "err": f"timeout after {SHELL_TIMEOUT_SEC}s", "ms": SHELL_TIMEOUT_SEC * 1000}
    except Exception as e:  # noqa: BLE001
        return {"cmd": cmd, "cwd": cwd, "rc": 127, "out": "", "err": str(e)[:500],
                "ms": int((time.monotonic() - t0) * 1000)}


# ---------------------------------------------------------------------------
# Page chrome.
# ---------------------------------------------------------------------------

def inject_style() -> None:
    import streamlit as st

    st.markdown(
        f"""<style>
        .stApp {{ background: {COLOR_BG}; color: {COLOR_TEXT};
                 font-variant-numeric: tabular-nums; }}
        .uf5-card {{ background: {COLOR_PANEL}; border: 1px solid {COLOR_BORDER};
                     border-radius: 14px; padding: 16px 18px; margin-bottom: 14px;
                     box-shadow: 0 1px 2px rgba(47,62,70,.05), 0 8px 24px -12px rgba(47,62,70,.18); }}
        .uf5-title {{ font-size: 13px; font-weight: 600; letter-spacing: .04em;
                      text-transform: uppercase; color: {COLOR_MUTED}; margin-bottom: 8px; }}
        .uf5-big {{ font-size: 22px; font-weight: 700; color: {COLOR_TEXT}; }}
        .uf5-muted {{ color: {COLOR_MUTED}; font-size: 13px; }}
        .uf5-badge {{ display: inline-block; padding: 3px 12px; border-radius: 999px;
                      font-size: 13px; font-weight: 600; color: #fff; }}
        .uf5-ver {{ display: flex; align-items: center; gap: 12px; }}
        .uf5-ver b {{ font-size: 15px; }}
        .uf5-ver .uf5-ver-name {{ flex: 1; font-size: 15px; font-weight: 600; }}
        /* Sidebar: soft studio panel, both testids covered. */
        section[data-testid="stSidebar"], div[data-testid="stSidebarContent"] {{
            background: linear-gradient(180deg, #FFFFFF 0%, {COLOR_PANEL} 78%);
        }}
        /* Sidebar nav cards below. */
        /* Sidebar nav: option cards only — the widget group label is not
           an option and stays hidden even under display overrides. */
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:not(:has(input)) {{
            display: none !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input) > div:first-child {{
            display: none;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input) {{
            display: flex !important; align-items: center; gap: 12px;
            padding: 8px 12px 8px 8px !important; border-radius: 14px;
            border: 1px solid transparent;
            font-size: 15px; font-weight: 700; color: {COLOR_TEXT};
            transition: background .22s ease, border-color .22s ease,
                        box-shadow .22s ease, transform .22s ease;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input):hover {{
            background: #FFFFFF; border-color: {COLOR_BORDER};
            transform: translateX(3px);
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {{
            background: linear-gradient(135deg, {COLOR_ACCENT} 0%, #5E93B5 100%);
            color: #fff; border-color: transparent;
            box-shadow: 0 8px 20px -8px rgba(74,127,165,.7);
        }}
        /* Active text stays white: Streamlit nests the caption in its own
           containers that ignore inherited color. */
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) p,
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) div {{
            color: #fff !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked)::after {{
            content: "›"; margin-left: auto; font-size: 20px; font-weight: 700;
            opacity: .85; line-height: 1;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input)::before {{
            content: ""; width: 36px; height: 36px; flex: none;
            border-radius: 11px; background-color: {COLOR_ACCENT_PALE};
            background-size: 19px; background-repeat: no-repeat;
            background-position: center;
            transition: background-color .22s ease;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input):nth-of-type(1)::before {{
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234A7FA5' stroke-width='2.4' stroke-linecap='round'%3E%3Cpath d='M5 20v-6M11 20V5M17 20v-9'/%3E%3C/svg%3E");
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input):nth-of-type(2)::before {{
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234A7FA5' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='4' width='18' height='16' rx='3'/%3E%3Cpath d='M7 10l3 3-3 3M12 16h5'/%3E%3C/svg%3E");
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input):nth-of-type(3)::before {{
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234A7FA5' stroke-width='2.4' stroke-linecap='round'%3E%3Cpath d='M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01'/%3E%3C/svg%3E");
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked)::before {{
            background-color: rgba(255,255,255,.22);
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked)::before {{
            filter: brightness(0) invert(1);
        }}
        /* Sidebar lock: quiet ghost button. */
        section[data-testid="stSidebar"] div[data-testid="stButton"] button {{
            background: transparent; border: 1px solid {COLOR_BORDER};
            color: {COLOR_MUTED}; font-weight: 700; border-radius: 10px;
            transition: background .2s ease, color .2s ease;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {{
            background: {COLOR_ACCENT_PALE}; color: {COLOR_TEXT};
            border-color: {COLOR_ACCENT_SOFT};
        }}
        /* Water-fill CPU bars: fresh nodes animate 0 -> value every tick. */
        .uf5-row {{ display: flex; align-items: flex-end; gap: 10px; }}
        .uf5-col {{ flex: 1; display: flex; flex-direction: column; align-items: center; }}
        .uf5-track {{ width: 100%; max-width: 56px; height: 200px;
                      background: {COLOR_ACCENT_PALE}; border-radius: 8px;
                      position: relative; overflow: hidden; }}
        .uf5-fill {{ position: absolute; bottom: 0; left: 0; right: 0;
                     background: linear-gradient(to top, {COLOR_ACCENT}, {COLOR_ACCENT_SOFT});
                     border-radius: 8px; transform-box: fill-box; transform-origin: bottom;
                     animation: uf5fill .9s cubic-bezier(.22,.8,.3,1) backwards;
                     transition: height .9s cubic-bezier(.22,.8,.3,1); }}
        .uf5-cap {{ margin-top: 6px; font-size: 11px; color: {COLOR_MUTED}; }}
        .uf5-val {{ font-size: 11px; font-weight: 700; color: {COLOR_TEXT}; margin-bottom: 2px; }}
        @keyframes uf5fill {{ from {{ transform: scaleY(0); }} to {{ transform: scaleY(1); }} }}
        /* Drop ghost: gray zone marking how much a bar fell, decrease-only. */
        .uf5-ghost {{ position: absolute; left: 0; right: 0;
                     background: #B9C4CC; opacity: .8; border-radius: 8px 8px 0 0;
                     transition: bottom .9s cubic-bezier(.22,.8,.3,1),
                                 height .9s cubic-bezier(.22,.8,.3,1),
                                 opacity 1.6s ease; }}
        /* Canvas tabs: larger labels, breathing room. */
        button[data-testid="stTab"] {{ font-size: 15px; font-weight: 600; }}
        /* Instrument-panel metrics: hero numbers, quiet labels. */
        div[data-testid="stMetricValue"] {{ font-size: 32px; font-weight: 700;
            font-variant-numeric: tabular-nums; }}
        div[data-testid="stMetricLabel"] {{ font-size: 12px; letter-spacing: .05em;
            text-transform: uppercase; color: {COLOR_MUTED}; }}
        div[data-testid="stMetric"] {{ background: {COLOR_PANEL};
            border: 1px solid {COLOR_BORDER}; border-radius: 12px; padding: 10px 14px;
            box-shadow: 0 1px 2px rgba(47,62,70,.05); }}
        @media (prefers-reduced-motion: reduce) {{
            .uf5-fill, .uf5-memseg, .uf5-ghost {{ animation: none !important;
                transition: none !important; }}
        }}
        /* Section transition: veil covers the render, then lifts. */
        .uf5-veil {{ position: fixed; inset: 0; z-index: 9999;
                     background: {COLOR_BG}; pointer-events: none;
                     display: flex; flex-direction: column; align-items: center;
                     justify-content: center; gap: 16px;
                     animation: uf5veil 1s ease forwards; }}
        .uf5-veil-line {{ width: 180px; height: 3px; border-radius: 999px;
                          background: {COLOR_ACCENT_PALE}; overflow: hidden;
                          position: relative; }}
        .uf5-veil-line::after {{ content: ""; position: absolute; inset: 0;
                                 width: 40%; border-radius: 999px;
                                 background: {COLOR_ACCENT};
                                 animation: uf5sweep .8s ease-in-out infinite; }}
        .uf5-veil-name {{ font-size: 14px; font-weight: 800;
                          letter-spacing: .34em; text-transform: uppercase;
                          color: {COLOR_MUTED}; padding-left: .34em;
                          animation: uf5veilname .8s ease backwards; }}
        @keyframes uf5veilname {{
            from {{ opacity: 0; transform: translateY(6px); }}
            to {{ opacity: 1; transform: none; }}
        }}
        .uf5-veil-line {{ width: 180px; height: 3px; border-radius: 999px;
                          background: {COLOR_ACCENT_PALE}; overflow: hidden;
                          position: relative; }}
        .uf5-veil-line::after {{ content: ""; position: absolute; inset: 0;
                                 width: 40%; border-radius: 999px;
                                 background: {COLOR_ACCENT};
                                 animation: uf5sweep .8s ease-in-out infinite; }}
        @keyframes uf5veil {{
            0% {{ opacity: 1; visibility: visible; }}
            62% {{ opacity: 1; visibility: visible; }}
            100% {{ opacity: 0; visibility: hidden; }}
        }}
        @keyframes uf5sweep {{
            0% {{ left: -40%; }} 100% {{ left: 100%; }}
        }}
        /* Skeleton shimmer: staged placeholders while data resolves. */
        .uf5-sk {{ border-radius: 8px; background: linear-gradient(
                     100deg, {COLOR_ACCENT_PALE} 40%, #FFFFFF 50%, {COLOR_ACCENT_PALE} 60%);
                   background-size: 200% 100%;
                   animation: uf5shimmer 1.2s ease-in-out infinite; }}
        @keyframes uf5shimmer {{
            0% {{ background-position: 180% 0; }} 100% {{ background-position: -80% 0; }}
        }}
        /* Content entrance: soft rise on every full render; main() may
           override the animation-name with a directional slide. */
        div[data-testid="stMainBlock"] {{ animation: uf5enter .5s ease backwards; }}
        @keyframes uf5enter {{ from {{ opacity: 0; transform: translateY(10px); }}
                              to {{ opacity: 1; transform: none; }} }}
        @keyframes uf5enterR {{ from {{ opacity: 0; transform: translateX(30px); }}
                               to {{ opacity: 1; transform: none; }} }}
        @keyframes uf5enterL {{ from {{ opacity: 0; transform: translateX(-30px); }}
                               to {{ opacity: 1; transform: none; }} }}
        @media (prefers-reduced-motion: reduce) {{
            .uf5-veil, .uf5-veil-name,
            div[data-testid="stMainBlock"] {{ animation: none !important; }}
        }}
        /* Memory stacked bar: one 0..max track, animated segment widths. */
        .uf5-memtrack {{ display: flex; height: 44px; background: {COLOR_ACCENT_PALE};
                         border-radius: 999px; overflow: hidden; }}
        .uf5-memseg {{ height: 100%; transition: width .9s cubic-bezier(.22,.8,.3,1);
                       animation: uf5fillx .9s cubic-bezier(.22,.8,.3,1) backwards;
                       transform-origin: left; }}
        @keyframes uf5fillx {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
        .uf5-legend {{ display: flex; gap: 16px; margin-top: 8px; font-size: 13px;
                       color: {COLOR_MUTED}; }}
        .uf5-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                    margin-right: 6px; }}
        /* Geo card: own chrome-free card, flag stretched across it. */
        .uf5-geocard {{ position: relative; overflow: hidden;
                        background: {COLOR_PANEL}; border: 1px solid {COLOR_BORDER};
                        border-radius: 14px; padding: 16px 18px; margin-bottom: 14px;
                        box-shadow: 0 1px 2px rgba(47,62,70,.05), 0 8px 24px -12px rgba(47,62,70,.18); }}
        .uf5-geocard-bg {{ position: absolute; top: 0; right: 0; display: block;
                           height: 100%; width: auto; max-width: 62%;
                           object-fit: contain; object-position: right center;
                           opacity: .28; pointer-events: none; user-select: none;
                           -webkit-mask-image: linear-gradient(to right, transparent 0%, black 45%);
                           mask-image: linear-gradient(to right, transparent 0%, black 45%); }}
        .uf5-geo-fg {{ position: relative; }}
        .uf5-geo-ip {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
        .uf5-flag {{ width: 30px; height: 22px; object-fit: cover; border-radius: 5px;
                     box-shadow: 0 1px 4px rgba(0,0,0,.25); }}
        </style>""",
        unsafe_allow_html=True,
    )


def card(title: str) -> None:
    import streamlit as st

    st.markdown(f'<div class="uf5-card"><div class="uf5-title">{title}</div>', unsafe_allow_html=True)


def card_end() -> None:
    import streamlit as st

    st.markdown("</div></div>", unsafe_allow_html=True)


def badge(text: str, color: str) -> str:
    return f'<span class="uf5-badge" style="background:{color}">{text}</span>'


# ---------------------------------------------------------------------------
# Stats section.
# ---------------------------------------------------------------------------

def render_memory_bar() -> None:
    """Single 0..max stacked track: used + cache + free (HTML, animated)."""
    import streamlit as st

    mem = read_meminfo()
    total, used, cache, free = memory_segments(mem)
    if not total:
        st.caption("memory info unavailable (no /proc/meminfo)")
        return
    segs = [("Used", used, COLOR_MEM_USED), ("Cache", cache, COLOR_MEM_CACHE),
            ("Free", free, COLOR_MEM_FREE)]
    bar = "".join(
        f'<div class="uf5-memseg" title="{label} {fmt_mb(v)}" '
        f'style="width:{v / total * 100:.2f}%;background:{color}"></div>'
        for label, v, color in segs
    )
    st.markdown(f'<div class="uf5-memtrack">{bar}</div>', unsafe_allow_html=True)
    legend = "".join(
        f'<span><span class="uf5-dot" style="background:{color}"></span>'
        f'{label} <b>{fmt_mb(v)}</b> {v / total * 100:.1f}%</span>'
        for label, v, color in segs
    )
    st.markdown(f'<div class="uf5-legend">{legend}</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", fmt_mb(total), "capacity", delta_color="off")
    c2.metric("Used", fmt_mb(used), f"{used / total * 100:.1f}%")
    c3.metric("Cache", fmt_mb(cache), f"{cache / total * 100:.1f}%")
    c4.metric("Free", fmt_mb(free), f"{free / total * 100:.1f}%")


def render_cpu_panel() -> None:
    """CPU model, core counts, per-core bars (st.bar_chart) + used/free."""
    import streamlit as st

    model, physical, logical = cpu_info()
    st.markdown(f'<div class="uf5-big">{model}</div>', unsafe_allow_html=True)
    st.markdown(f'<span class="uf5-muted">{physical} physical · {logical} logical cores</span>',
                unsafe_allow_html=True)
    snap1 = read_cpu_times()
    total1, idle1 = read_cpu_total()
    time.sleep(0.5)
    snap2 = read_cpu_times()
    total2, idle2 = read_cpu_total()

    per_core: dict[str, float] = {}
    for name, (t1, i1) in snap1.items():
        t2, i2 = snap2.get(name, (t1, i1))
        dt, di = t2 - t1, i2 - i1
        per_core[name] = round((1 - di / dt) * 100, 1) if dt > 0 else 0.0
    dt, di = total2 - total1, idle2 - idle1
    avg = round((1 - di / dt) * 100, 1) if dt > 0 else 0.0

    m1, m2, m3 = st.columns(3)
    m1.metric("Average load", f"{avg}%")
    busy = sum(1 for v in per_core.values() if v >= 5)
    prev_busy = st.session_state.get("uf5_busy_prev")
    if prev_busy is None or not isinstance(prev_busy, int):
        busy_delta = None  # first tick: no history yet
    else:
        diff = busy - prev_busy
        busy_delta = f"{diff:+d}" if diff else "0"
    st.session_state["uf5_busy_prev"] = busy
    m2.metric("Busy cores", busy, busy_delta, delta_color="normal")
    m3.metric("Free (avg)", f"{100 - avg:.1f}%")

    if per_core:
        # Water-fill bars + drop ghost: when a bar decreases, the lost portion
        # stays visible in gray until the next tick melts it away.
        prev = st.session_state.get("uf5_cpu_prev", {})
        bars = []
        for i, (name, value) in enumerate(per_core.items()):
            label = re.sub(r"[^a-z0-9]", "", name.lower()) or f"c{i}"
            pct = max(min(value, 100), 0)
            drop = max(min(prev.get(name, value), 100) - pct, 0)
            has_ghost = drop >= 0.5
            # Flush joint: flat blue top hugged by the ghost, no seam.
            fill_radius = "0 0 8px 8px" if has_ghost else "8px"
            ghost = (
                f'<div class="uf5-ghost" '
                f'style="bottom:{pct:.1f}%;height:{drop:.1f}%"></div>'
                if has_ghost else ""
            )
            bars.append(
                f'<div class="uf5-col"><div class="uf5-val">{value:.0f}</div>'
                f'<div class="uf5-track"><div class="uf5-fill" '
                f'style="height:{pct:.1f}%;animation-delay:{i * 70}ms;'
                f'border-radius:{fill_radius}"></div>'
                f'{ghost}</div>'
                f'<div class="uf5-cap">{label}</div></div>'
            )
        st.session_state["uf5_cpu_prev"] = dict(per_core)
        st.markdown(f'<div class="uf5-row">{"".join(bars)}</div>',
                    unsafe_allow_html=True)


def render_canvas() -> None:
    """Memory / CPU canvases as native tabs (no switcher widget, no emoji).

    Each tab owns a realtime fragment; the visible one animates, the hidden
    one costs a single /proc read per tick. Wheel switching is impossible in
    pure Streamlit — tabs are the lightest native mechanism.
    """
    import streamlit as st

    try:
        live = st.fragment(run_every=2)
        slow = st.fragment(run_every=5)
    except TypeError:
        live = slow = st.fragment

    tab_mem, tab_cpu, tab_disk = st.tabs(["Memory", "CPU", "Disk"])

    def _on_stats() -> bool:
        # Stale auto-timers from a previous section must render nothing —
        # otherwise their deltas land in a foreign section tree.
        return st.session_state.get("uf5_section", "stats") == "stats"

    with tab_mem:
        @live
        def _live_memory() -> None:
            if _on_stats():
                render_memory_bar()

        _live_memory()

    with tab_cpu:
        @live
        def _live_cpu() -> None:
            if _on_stats():
                render_cpu_panel()

        _live_cpu()

    with tab_disk:
        @slow
        def _live_disk() -> None:
            if _on_stats():
                render_disk_panel()

        _live_disk()


def render_geo_cluster() -> None:
    """Network block without card chrome: flag + IP + shard badge, watermark behind."""
    import streamlit as st

    # Staged: skeleton first (covers teardown gap), real content on resolve.
    slot = st.empty()
    slot.markdown(
        '<div class="uf5-geocard"><div class="uf5-sk" style="height:26px;width:45%"></div>'
        '<div style="height:10px"></div>'
        '<div class="uf5-sk" style="height:15px;width:70%"></div>'
        '<div style="height:8px"></div>'
        '<div class="uf5-sk" style="height:13px;width:55%"></div></div>',
        unsafe_allow_html=True,
    )
    geo = get_geo()
    cluster = get_cluster()
    if not geo:
        slot.caption("geo unavailable")
        return
    cc = str(geo.get("country_code", ""))
    flag = flag_url(cc)
    shard = str(cluster.get("cluster", "") or "")
    small = f'<img class="uf5-flag" src="{flag}" alt="{cc}"/>' if flag else ""
    big = f'<img class="uf5-geocard-bg" src="{flag}" alt=""/>' if flag else ""
    slot.markdown(
        f'<div class="uf5-geocard">{big}'
        f'<div class="uf5-geo-fg">'
        f'<div class="uf5-geo-ip">{small}'
        f'<span class="uf5-big">{geo.get("ip", "unknown")}</span>'
        + (badge(shard, shard_color(shard)) if shard != "unknown" else "")
        + f'</div>'
        f'<div>{geo.get("city", "?")}, {geo.get("country", "?")} ({cc or "?"})</div>'
        f'<div class="uf5-muted">AS{geo.get("asn", "?")} · '
        f'{geo.get("asn_organization", "unknown")}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_versions() -> None:
    """Python / Go / Tailscale rows: icon + name + version, no card chrome."""
    import streamlit as st

    cols = st.columns(3)
    slots = [c.empty() for c in cols]
    cached_versions = st.session_state.setdefault("uf5_versions", {})
    for s in slots:
        s.markdown('<div class="uf5-sk" style="height:44px"></div>',
                   unsafe_allow_html=True)
    for slot, (label, icon, resolver) in zip(slots, (
        ("Python", "python", resolve_python_version),
        ("Go", "go", resolve_go_version),
        ("Tailscale", "tailscale", resolve_tailscale_version),
    )):
        version = cached_versions.get(label)
        if not version:
            with st.spinner(f"resolving {label.lower()}…"):
                version = resolver()
            cached_versions[label] = version
        svg = load_icon(icon)
        color = COLOR_OK if version not in ("not installed", "error", "unknown") else COLOR_MUTED
        slot.markdown(
            f'<div class="uf5-ver">{svg}<span class="uf5-ver-name">{label}</span>'
            f'{badge(version, color)}</div>',
            unsafe_allow_html=True)
        log_event("debug", f"version {label}={version}")


def render_stats() -> None:
    render_canvas()
    render_geo_cluster()
    render_versions()


# ---------------------------------------------------------------------------
# Shell section — persistent cwd, host-aware suggestions, styled history.
# ---------------------------------------------------------------------------

SHELL_BUILTINS = ("cd", "clear", "history", "help", "exit")
SHELL_SUGGEST_LIMIT = 12


def list_path_binaries() -> list[str]:
    """All executable names on PATH, sorted. No duplicates."""
    found: set[str] = set()
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not folder or not os.path.isdir(folder):
            continue
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False) and os.access(entry.path, os.X_OK):
                            found.add(entry.name)
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(found)


def suggest_commands(text: str, cwd: str) -> list[str]:
    """Complete first token against PATH binaries, later tokens against cwd.

    Returns up to SHELL_SUGGEST_LIMIT matches. Pure function (testable).
    """
    text = text.strip()
    if not text:
        return []
    parts = text.split()
    if len(parts) <= 1 and not text.endswith((" ", "\t")):
        prefix = parts[0] if parts else ""
        cands = [b for b in SHELL_BUILTINS if b.startswith(prefix)]
        cands += [b for b in list_path_binaries() if b.startswith(prefix) and b not in cands]
        return cands[:SHELL_SUGGEST_LIMIT]
    frag = parts[-1]
    if "/" in frag:
        dirpart, tail = frag.rsplit("/", 1)
        if os.path.isabs(dirpart):
            folder = dirpart
        else:
            folder = os.path.normpath(os.path.join(cwd, os.path.expanduser(dirpart or ".")))
        prefix = dirpart + "/"
    else:
        folder, tail, prefix = cwd, frag, ""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.startswith(tail):
            continue
        full = os.path.join(folder, name)
        suffix = "/" if os.path.isdir(full) else ""
        out.append(prefix + name + suffix)
        if len(out) >= SHELL_SUGGEST_LIMIT:
            break
    return out


def resolve_cd(target: str, cwd: str) -> str | None:
    """Resolve a cd target (absolute, ~, relative) to a real dir or None."""
    target = os.path.expanduser(target.strip()) or os.path.expanduser("~")
    dest = target if os.path.isabs(target) else os.path.normpath(os.path.join(cwd, target))
    dest = os.path.abspath(dest)
    return dest if os.path.isdir(dest) else None


def find_shell_component_dir() -> str:
    """Locate components/shell_input/index.html next to main.py, in cwd, or above.

    The deployed entry point may live at a different path than this repo
    (e.g. test/main.py), so several layouts are probed. Empty when missing.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(here, "components", "shell_input"),
        os.path.join(os.getcwd(), "uf5vmjt", "components", "shell_input"),
        os.path.join(os.getcwd(), "components", "shell_input"),
        os.path.join(here, "..", "uf5vmjt", "components", "shell_input"),
    ]
    for cand in cands:
        if os.path.isfile(os.path.join(cand, "index.html")):
            return os.path.normpath(cand)
    return ""


SHELL_COMPONENT_DIR = find_shell_component_dir()
_shell_component = None


def shell_input_component(candidates: list[str], files: list[str], dirs: dict, cwd: str, key: str):
    """Render the ghost-autocomplete terminal input. Returns submitted cmd or None."""
    global _shell_component
    import streamlit.components.v1 as components

    if not SHELL_COMPONENT_DIR:
        raise FileNotFoundError("shell_input/index.html not found next to main.py")
    if _shell_component is None:
        _shell_component = components.declare_component("uf5_shell_input", path=SHELL_COMPONENT_DIR)
    return _shell_component(binaries=candidates, files=files, dirs=dirs, cwd=cwd, key=key, default=None)


def build_completion_tree(cwd: str, per_dir: int = 60, max_subs: int = 25) -> dict:
    """Shallow dir listings for client-side '/' completion: / + cwd + subdirs."""
    def snap(folder: str) -> list[str]:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return []
        out = []
        for name in names:
            if name.startswith("."):
                continue
            out.append(name + "/" if os.path.isdir(os.path.join(folder, name)) else name)
            if len(out) >= per_dir:
                break
        return out

    tree: dict[str, list[str]] = {}
    tree[os.path.normpath("/")] = snap("/")
    cwd_norm = os.path.normpath(cwd)
    tree[cwd_norm] = snap(cwd_norm)
    for name in tree[cwd_norm][:max_subs]:
        if name.endswith("/"):
            sub = os.path.normpath(os.path.join(cwd_norm, name))
            tree[sub] = snap(sub)
    return tree


def list_cwd_files(cwd: str) -> list[str]:
    """Entry names of cwd for client-side path completion (dirs get '/')."""
    try:
        names = sorted(os.listdir(cwd))
    except OSError:
        return []
    out = []
    for name in names:
        if name.startswith("."):
            continue
        out.append(name + "/" if os.path.isdir(os.path.join(cwd, name)) else name)
    return out

def render_shell() -> None:
    """Terminal runner: ghost-autocomplete input, persistent cwd, styled history.

    Completion is client-side inside the custom component (ghost text after a
    pause, Tab to accept/list, live rescan per keystroke). Python only sees
    the submitted command on Enter.
    """
    import streamlit as st

    if not require_auth():
        return
    st.session_state.setdefault("uf5_shell_hist", [])
    st.session_state.setdefault("uf5_cwd", os.getcwd())
    st.session_state.setdefault("uf5_binaries", None)
    st.session_state.setdefault("uf5_input_nonce", 0)
    cwd = st.session_state["uf5_cwd"]
    if st.session_state["uf5_binaries"] is None:
        st.session_state["uf5_binaries"] = list_path_binaries()
    try:
        user_host = f"{os.getlogin()}@{socket.gethostname()}"
    except OSError:
        user_host = socket.gethostname()

    st.markdown(
        f'<div style="font-family:monospace;font-size:13px;margin-bottom:8px;">'
        f'<span style="color:{COLOR_OK};font-weight:700">{user_host}</span>'
        f'<span style="color:{COLOR_MUTED}">:</span>'
        f'<span style="color:{COLOR_ACCENT};font-weight:700">{cwd}</span>'
        f'<span style="color:{COLOR_MUTED}">$ · timeout {SHELL_TIMEOUT_SEC}s</span></div>',
        unsafe_allow_html=True,
    )
    component_ok = True
    try:
        submitted = shell_input_component(
            st.session_state["uf5_binaries"], list_cwd_files(cwd),
            build_completion_tree(cwd), cwd,
            key=f"uf5_shell_in_{st.session_state['uf5_input_nonce']}",
        )
    except Exception as e:  # noqa: BLE001
        component_ok = False
        log_event("error", f"shell component failed ({type(e).__name__}: {e}) — "
                           "ship components/shell_input/index.html next to main.py")
        # Basic fallback WITH chips: chips render before the form so a click
        # may legally preset the input value.
        st.session_state.setdefault("uf5_draft", "")
        draft = st.session_state["uf5_draft"].strip()
        if draft:
            matches = suggest_commands(draft, cwd)
            if matches:
                st.caption("suggestions from this host (click to fill, Enter to run):")
                cols = st.columns(min(len(matches), 6))
                parts = draft.split()
                for i, cand in enumerate(matches[:6]):
                    label = cand if len(cand) <= 18 else cand[:17] + "…"
                    if cols[i % len(cols)].button(f"`{label}`", key=f"uf5_s_{i}_{label}"):
                        base = parts[:-1] if len(parts) > 1 else []
                        full = " ".join(base + [cand]) + ("" if cand.endswith("/") else " ")
                        st.session_state["uf5_cmd"] = full
                        st.session_state["uf5_draft"] = full
                        st.rerun()
                if len(matches) > 6:
                    st.caption(f"+{len(matches) - 6} more — keep typing")
        st.caption("component unavailable — basic input:")
        with st.form("uf5_shell_form", clear_on_submit=True):
            submitted = st.text_input("Command", label_visibility="collapsed", key="uf5_cmd")
            if not st.form_submit_button("Run ⏎", width="stretch"):
                submitted = None

    if submitted and submitted.strip():
        cmd = submitted.strip()
        st.session_state["uf5_draft"] = cmd
        verb = cmd.split()[0]
        if verb == "cd":
            dest = resolve_cd(cmd[2:].strip(), cwd)
            if dest:
                st.session_state["uf5_cwd"] = dest
                log_event("info", f"shell cd -> {dest}")
            else:
                st.session_state["uf5_shell_hist"].append(
                    {"cmd": cmd, "cwd": cwd, "rc": 1,
                     "out": "", "err": f"no such directory: {cmd[2:].strip()}", "ms": 0})
        elif verb == "clear":
            st.session_state["uf5_shell_hist"] = []
        elif verb == "history":
            for i, h in enumerate(st.session_state["uf5_shell_hist"]):
                st.caption(f"{i + 1}: {h['cmd']}")
        elif verb == "help":
            st.caption("builtins: cd <dir> (absolute, ~, relative, persistent) · "
                       "clear · history · help · any host binary")
        else:
            entry = run_shell_command(cmd, cwd)
            st.session_state["uf5_shell_hist"].append(entry)
            del st.session_state["uf5_shell_hist"][:-SHELL_HISTORY_LIMIT]
            level = "ok" if entry["rc"] == 0 else "error"
            log_event(level, f"shell exit={entry['rc']} ms={entry['ms']}: {cmd[:120]}")
        st.session_state["uf5_input_nonce"] += 1
        st.rerun()

    for entry in reversed(st.session_state["uf5_shell_hist"]):
        color = COLOR_OK if entry["rc"] == 0 else COLOR_ERR
        meta = f"{entry['ms']} ms · {entry['cwd']}"
        with st.container(border=True):
            st.markdown(f"`$ {entry['cmd']}`  {badge('exit ' + str(entry['rc']), color)} "
                        f"<span class='uf5-muted'>{meta}</span>",
                        unsafe_allow_html=True)
            if entry["out"].strip():
                st.code(entry["out"].rstrip(), language="text")
            if entry["err"].strip():
                st.code(entry["err"].rstrip(), language="text")


# ---------------------------------------------------------------------------
# Logs section — strict line-by-line stream, no offsets.
# ---------------------------------------------------------------------------

LEVEL_COLOR = {"debug": COLOR_MUTED, "info": COLOR_ACCENT, "ok": COLOR_OK,
               "warn": COLOR_WARN, "error": COLOR_ERR}


def render_logs() -> None:
    import streamlit as st

    if not require_auth():
        return
    ingest_go_events()
    events = st.session_state.get("uf5_events", [])
    c1, c2 = st.columns([3, 1])
    level_filter = c1.segmented_control("Level", ["all", "debug", "info", "ok", "warn", "error"],
                                        default="all", key="uf5_log_level")
    if c2.button("Clear", width="stretch"):
        st.session_state["uf5_events"] = []
        st.rerun()
    lines = []
    for e in events:
        if level_filter != "all" and e["level"] != level_filter:
            continue
        color = LEVEL_COLOR.get(e["level"], COLOR_MUTED)
        lines.append(
            f'<div style="font-family:monospace;font-size:13px;line-height:1.5;white-space:pre-wrap;">'
            f'<span style="color:{COLOR_MUTED}">{e["ts"]}</span> '
            f'<span style="color:{color};font-weight:700">{e["level"].upper():5s}</span> '
            f'<span style="color:{COLOR_MUTED}">[{e["source"]}]</span> '
            f'<span>{e["msg"]}</span></div>'
        )
    st.markdown("\n".join(lines) if lines else
                '<span class="uf5-muted">no events yet</span>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Token wall — Shell/Logs locked behind ACCESS_TOKEN + signed cookie.
# ---------------------------------------------------------------------------

SESSION_COOKIE = "uf5sess"
SESSION_TTL_MIN_DEFAULT = 30


def access_token_expected() -> str:
    """ACCESS_TOKEN from env, else st.secrets. Empty when unconfigured."""
    token = (os.environ.get("ACCESS_TOKEN") or "").strip()
    if token:
        return token
    try:
        import streamlit as st

        value = st.secrets.get("ACCESS_TOKEN", "")
    except Exception:  # noqa: BLE001
        return ""
    return str(value or "").strip()


def session_ttl_sec() -> int:
    """Session lifetime in seconds (SESSION_TTL_MIN, default 30, floor 1m)."""
    raw = (os.environ.get("SESSION_TTL_MIN") or "").strip()
    try:
        minutes = max(int(raw), 1) if raw else SESSION_TTL_MIN_DEFAULT
    except ValueError:
        minutes = SESSION_TTL_MIN_DEFAULT
    return minutes * 60


def sign_session(exp: int, key: str) -> str:
    """Mint '<exp>.<hmac>' with key — stateless, verified without storage."""
    sig = hmac.new(key.encode(), f"{SESSION_COOKIE}:{exp}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_session_exp(cookie_value: str, key: str) -> int:
    """Return the cookie expiry unix time, or 0 when bad/expired/tampered."""
    try:
        exp_s, sig = (cookie_value or "").split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return 0
    want = hmac.new(key.encode(), f"{SESSION_COOKIE}:{exp}".encode(),
                    hashlib.sha256).hexdigest()
    try:
        ok = hmac.compare_digest(want.encode(), sig.encode())
    except (TypeError, ValueError):
        return 0
    return exp if ok and exp > int(time.time()) else 0


def read_session_cookie() -> str:
    """Our session cookie via st.context.cookies (read-only mapping)."""
    try:
        import streamlit as st

        return str(st.context.cookies.get(SESSION_COOKIE, "") or "")
    except Exception:  # noqa: BLE001
        return ""


def find_session_component_dir() -> str:
    """Locate components/session_cookie/index.html (mirrors shell_input)."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(here, "components", "session_cookie"),
        os.path.join(os.getcwd(), "uf5vmjt", "components", "session_cookie"),
        os.path.join(os.getcwd(), "components", "session_cookie"),
        os.path.join(here, "..", "uf5vmjt", "components", "session_cookie"),
    ]
    for cand in cands:
        if os.path.isfile(os.path.join(cand, "index.html")):
            return os.path.normpath(cand)
    return ""


SESSION_COMPONENT_DIR = find_session_component_dir()
_session_component = None


def session_cookie_api(action: str, value: str = "", max_age: int = 0) -> bool:
    """Run one cookie action (set/clear). False when the bridge is missing —
    the tab session still works, only reload persistence is lost."""
    global _session_component
    import streamlit as st
    import streamlit.components.v1 as components

    if not SESSION_COMPONENT_DIR:
        st.caption("persistent login unavailable "
                   "(ship components/session_cookie/index.html next to main.py)")
        return False
    if _session_component is None:
        _session_component = components.declare_component("uf5_session_cookie",
                                                          path=SESSION_COMPONENT_DIR)
    _session_component(action=action, value=value, max_age=max_age,
                       name=SESSION_COOKIE, key="uf5_sess_cookie", default=None)
    return True


def is_authed(key: str) -> bool:
    """Fast path (tab session) then cookie path (reload/new tab)."""
    import streamlit as st

    now = int(time.time())
    try:
        until = int(st.session_state.get("uf5_authed_until", 0) or 0)
    except (TypeError, ValueError):
        until = 0
    if until > now:
        return True
    exp = valid_session_exp(read_session_cookie(), key)
    if exp > now:
        st.session_state["uf5_authed_until"] = exp
        return True
    return False


def require_auth() -> bool:
    """Gate for Shell/Logs. Renders the wall when unauthenticated."""
    import streamlit as st

    key = access_token_expected()
    if not key:
        st.warning("ACCESS_TOKEN not configured — Shell/Logs are open. "
                   "Set ACCESS_TOKEN to lock them.")
        return True
    if is_authed(key):
        return True
    st.markdown("**Restricted area** — Shell and Logs need the access token. "
                "Stats stays public.")
    token = st.text_input("Access token", type="password", key="uf5_token_input")
    if st.button("Unlock", key="uf5_unlock"):
        if (token or "").strip() and _compare_tokens((token or "").strip(), key):
            exp = int(time.time()) + session_ttl_sec()
            st.session_state["uf5_authed_until"] = exp
            session_cookie_api("set", sign_session(exp, key), session_ttl_sec())
            st.rerun()
        time.sleep(1)
        st.error("wrong token")
    return False


def _compare_tokens(a: str, b: str) -> bool:
    """Constant-time compare on bytes (bytes form tolerates non-ASCII)."""
    try:
        return hmac.compare_digest(a.encode(), b.encode())
    except (TypeError, ValueError):
        return False


def render_lock_button() -> None:
    """Sidebar Lock: clears cookie + tab session. Only when wall + authed."""
    import streamlit as st

    key = access_token_expected()
    if not key or not is_authed(key):
        return
    if st.sidebar.button("Lock", key="uf5_lock", width="stretch"):
        st.session_state.pop("uf5_authed_until", None)
        try:
            st.session_state.pop("uf5_token_input", None)
        except Exception:  # noqa: BLE001
            pass  # widget keys are read-only outside callbacks
        session_cookie_api("clear")
        st.rerun()


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

SECTION_ORDER = ["stats", "shell", "logs"]
SECTION_LABELS = {"stats": "Stats", "shell": "Shell", "logs": "Logs"}


def section_animation(section: str) -> str:
    """Slide direction vs the previous section (Stats→Shell→Logs = forward).

    Tracks the last full render in session state; fragment ticks never reach
    here, so realtime canvases keep animating undisturbed.
    """
    import streamlit as st

    prev = st.session_state.get("uf5_section_prev")
    st.session_state["uf5_section_prev"] = section
    if not prev or prev == section or prev not in SECTION_ORDER:
        return "uf5enter"
    forward = SECTION_ORDER.index(section) > SECTION_ORDER.index(prev)
    return "uf5enterR" if forward else "uf5enterL"

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="uf5vmjt", layout="wide")
    inject_style()
    seed_worker_env_from_secrets()
    # Publish our own public URL for the keepalive worker: an explicit APP_URL
    # env wins, otherwise derive https://<host> from the browser URL so a
    # sidecar in the same container (or the operator copying the log line)
    # knows what to ping. Never overwrites, never raises.
    _host = app_host()
    if _host and not os.environ.get("APP_URL"):
        os.environ["APP_URL"] = f"https://{_host}"
        log_event("debug", f"APP_URL set to https://{_host}", source="net")
    ensure_keepalive_config()
    ensure_worker()

    section = st.sidebar.radio("Navigate", SECTION_ORDER,
                               format_func=SECTION_LABELS.get,
                               label_visibility="collapsed",
                               key="uf5_section")
    anim = section_animation(section)
    # Fresh veil node on every full rerun -> replays on section switches only
    # (fragment ticks never re-execute main, so realtime canvases keep animating).
    st.markdown(f'<div class="uf5-veil"><div class="uf5-veil-line"></div>'
                f'<div class="uf5-veil-name">{SECTION_LABELS[section]}</div></div>',
                unsafe_allow_html=True)
    if anim != "uf5enter":
        st.markdown(f'<style>div[data-testid="stMainBlock"]{{animation-name:{anim};}}</style>',
                    unsafe_allow_html=True)

    st.sidebar.divider()
    render_lock_button()
    log_event("debug", f"section opened: {section}")

    if section == "stats":
        render_stats()
    elif section == "shell":
        render_shell()
    else:
        render_logs()


if __name__ == "__main__":
    main()
