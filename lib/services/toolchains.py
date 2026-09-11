"""uf5vmjt.lib.services.toolchains — Go toolchain ensure + tailscale trigger/status."""
from __future__ import annotations
import json
import os
import platform
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from lib.core.config import WORKER_PORT
from lib.core.events import log_event



def version_var(name: str) -> str:
    """Version knob from env, else st.secrets, else latest."""
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    try:
        import streamlit as st

        value = str(st.secrets.get(name, "") or "").strip()
    except Exception:  # noqa: BLE001
        value = ""
    return value or TOOLCHAIN_DEFAULTS.get(name, "latest")


def _fetch_text(url: str, timeout: float = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "uf5vmjt/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(errors="replace")


def resolve_go_latest() -> str:
    """Newest stable Go (go.dev/VERSION plain text, first line goX.Y.Z)."""
    first = _fetch_text("https://go.dev/VERSION?m=text").splitlines()
    if first:
        m = re.match(r"^go(\d+\.\d+(?:\.\d+)?)$", first[0].strip())
        if m:
            return m.group(1)
    raise ValueError("bad VERSION body")


def _resolve_tool_version(raw: str, kind: str) -> str:
    """latest|x.y[.z] for Go. Anything else raises ValueError.

    Upstream max is cached per process for an hour: reruns stay at two
    dict lookups, new releases are picked up within the hour.
    """
    want = (raw or "").strip()
    if want.lower() == "latest":
        now = time.monotonic()
        hit = _RESOLVED_CACHE.get(kind)
        if hit and now - hit[1] < RESOLVE_TTL_SEC:
            return hit[0]
        ver = resolve_go_latest()
        _RESOLVED_CACHE[kind] = (ver, now)
        return ver
    if re.match(r"^\d+\.\d+(?:\.\d+)?$", want):
        return want
    raise ValueError(f"bad {kind} version {want!r}: want latest|x.y[.z]")


def _machine_arch() -> str:
    """Return the Go arch for this machine."""
    m = platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m in ("armv7l", "arm", "armv6l"):
        return "armv6l"
    return "amd64"


def _read_marker(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_marker(path: str, version: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(version.strip() + "\n")
    except OSError:
        pass


def _download_to(url: str, dest: str, timeout: float = 300) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "uf5vmjt/1.0"})
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as out:
        shutil.copyfileobj(r, out)


def ensure_go_toolchain(want: str) -> str:
    """Download Go want to /tmp/bin/go unless the marker matches. Returns
    the go binary path, or empty on failure."""
    if _read_marker(GO_VERSION_FILE) == want and os.path.isfile(GO_BIN_PATH):
        return GO_BIN_PATH
    arch = _machine_arch()
    url = f"{GO_DL_BASE_URL}/go{want}.linux-{arch}.tar.gz"
    log_event("info", f"downloading go {want}", source="tool")
    try:
        if os.path.isdir(GO_ROOT_DIR):
            shutil.rmtree(GO_ROOT_DIR)
        _download_to(url, os.path.join(BIN_ROOT_DIR, f"go{want}.linux-{arch}.tgz"))
        with tarfile.open(os.path.join(BIN_ROOT_DIR, f"go{want}.linux-{arch}.tgz"), "r:gz") as tf:
            for member in tf.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise ValueError(f"unsafe path in tar: {member.name}")
            tf.extractall(BIN_ROOT_DIR)
        try:
            os.remove(os.path.join(BIN_ROOT_DIR, f"go{want}.linux-{arch}.tgz"))
        except OSError:
            pass
        if not os.path.isfile(GO_BIN_PATH):
            raise ValueError(f"go binary missing after extract: {GO_BIN_PATH}")
        os.chmod(GO_BIN_PATH, 0o755)
        _write_marker(GO_VERSION_FILE, want)
    except Exception as e:  # noqa: BLE001
        log_event("warn", f"go {want} setup failed: {e}", source="tool")
        return ""
    log_event("ok", f"go {want} ready", source="tool")
    return GO_BIN_PATH


def ensure_toolchains() -> None:
    """Resolve GO_VERSION and fetch the Go toolchain; Tailscale is owned by
    the worker (POST /v1/tailscale), here we only nudge it once per process.

    Fast path (marker match) costs one file read. Slow path downloads on
    cold boot only — serialized by a lock dir so concurrent reruns never
    trample the tree. Never raises.
    """
    global _TOOLCHAINS_DONE
    try:
        go_want = _resolve_tool_version(version_var("GO_VERSION"), "go")
    except Exception as e:  # noqa: BLE001
        log_event("warn", f"toolchain resolve failed: {e}", source="tool")
        return
    if _TOOLCHAINS_DONE == go_want:
        return
    if not _acquire_toolchain_lock():
        log_event("debug", "toolchain setup running elsewhere — retry next run",
                  source="tool")
        return
    try:
        ensure_go_toolchain(go_want)
        _TOOLCHAINS_DONE = go_want
    finally:
        _release_toolchain_lock()
    trigger_tailscale_update()


def _acquire_toolchain_lock() -> bool:
    """Atomic mkdir lock. True when we hold it."""
    try:
        os.mkdir(TOOLCHAIN_LOCK_DIR)
        return True
    except OSError:
        pass
    try:
        age = time.time() - os.stat(TOOLCHAIN_LOCK_DIR).st_mtime
    except OSError:
        return False
    if age < TOOLCHAIN_LOCK_STALE_SEC:
        return False
    try:
        shutil.rmtree(TOOLCHAIN_LOCK_DIR, ignore_errors=True)
        os.mkdir(TOOLCHAIN_LOCK_DIR)
        return True
    except OSError:
        return False


def _release_toolchain_lock() -> None:
    try:
        os.rmdir(TOOLCHAIN_LOCK_DIR)
    except OSError:
        pass


def trigger_tailscale_update() -> None:
    """Nudge the sidecar to refresh /tmp/bin/tailscale (fire-and-forget).

    The worker answers 202 immediately and downloads detached, so the panel
    never blocks on the 25 MB fetch. State lives in session_state (survives
    script re-execution in any process model): done once the version badge
    resolved a real version, quiet for 10 min against a pre-endpoint worker,
    retried on transient errors (sidecar still starting). Never raises.
    """
    import streamlit as st

    if st.session_state.get("uf5_ts_triggered"):
        return
    cached = (st.session_state.get("uf5_versions") or {}).get("Tailscale", "")
    if cached and cached not in ("unknown", "error", "not installed"):
        st.session_state["uf5_ts_triggered"] = True
        return
    try:
        if time.time() - float(st.session_state.get("uf5_ts_old_worker_ts", 0) or 0) < TS_OLD_WORKER_TTL_SEC:
            return
    except (TypeError, ValueError):
        pass
    # The version badge renders on stats only; other sections would never
    # close the gate above. Ask the sidecar directly (localhost, instant):
    # installed means done, no update POST at all.
    stt = worker_ts_status()
    if isinstance(stt.get("installed"), str) and stt["installed"]:
        st.session_state["uf5_ts_triggered"] = True
        return
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{WORKER_PORT}/v1/tailscale",
            data=json.dumps({"func": "update"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            if r.status == 202:
                st.session_state["uf5_ts_triggered"] = True
                log_event("debug", "tailscale update triggered on sidecar",
                          source="tool")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            st.session_state["uf5_ts_old_worker_ts"] = time.time()
        log_event("debug", f"tailscale trigger skipped: HTTP {e.code}", source="tool")
    except Exception as e:  # noqa: BLE001
        log_event("debug", f"tailscale trigger skipped: {e}", source="tool")


def worker_ts_status() -> dict:
    """Sidecar tailscale snapshot (func=status). Empty when unreachable."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{WORKER_PORT}/v1/tailscale",
            data=json.dumps({"func": "status"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read().decode(errors="replace"))
            return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


TOOLCHAIN_DEFAULTS = {"GO_VERSION": "latest", "TS_VERSION": "latest"}

BIN_ROOT_DIR = "/tmp/bin"

GO_ROOT_DIR = os.path.join(BIN_ROOT_DIR, "go")

GO_BIN_PATH = os.path.join(GO_ROOT_DIR, "bin", "go")

GO_VERSION_FILE = os.path.join(GO_ROOT_DIR, ".version")

GO_DL_BASE_URL = "https://go.dev/dl"

RESOLVE_TTL_SEC = 3600

TOOLCHAIN_LOCK_DIR = "/tmp/uf5vmjt-toolchains.lock"

TOOLCHAIN_LOCK_STALE_SEC = 20 * 60

_RESOLVED_CACHE: dict = {}

_TOOLCHAINS_DONE: tuple | None = None

TS_OLD_WORKER_TTL_SEC = 600

