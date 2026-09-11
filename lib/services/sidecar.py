"""uf5vmjt.lib.services.sidecar — Go worker sidecar lifecycle + pg verdict."""
from __future__ import annotations
import json
import os
import subprocess
import urllib.error
import urllib.request
from lib.core.config import GO_LOG_PATH, WORKER_BIN_ENV, WORKER_ENV_KEYS, WORKER_PORT
from lib.core.events import log_event
from lib.services.netinfo import fetch_json



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


def worker_pg_verdict() -> dict:
    """Cached /v1/pg verdict from the local sidecar. Empty when unreachable.

    The failure reason lands in uf5_pg_note (shown under the versions row),
    so 'unknown' is always diagnosable: old worker, unconfigured pg, or a
    sidecar that is not up (yet).
    """
    import streamlit as st

    cached = st.session_state.get("uf5_pg_verdict")
    if isinstance(cached, dict) and cached:
        return cached
    url = f"http://127.0.0.1:{WORKER_PORT}/v1/pg"
    try:
        data = fetch_json(url, timeout=3)
    except urllib.error.HTTPError as e:
        detail = f"sidecar http {e.code}"
        try:
            body = json.loads(e.read().decode(errors="replace") or "{}")
            if isinstance(body, dict) and body.get("error"):
                detail += f": {body['error']}"
        except (ValueError, OSError):
            pass
        if e.code == 404:
            detail += " (old worker — redeploy for /v1/pg)"
        st.session_state["uf5_pg_note"] = detail
        return {}
    except Exception:  # noqa: BLE001
        st.session_state["uf5_pg_note"] = f"sidecar unreachable on :{WORKER_PORT}"
        return {}
    if isinstance(data, dict) and data.get("version"):
        st.session_state["uf5_pg_verdict"] = data
        st.session_state.pop("uf5_pg_note", None)
        return data
    st.session_state["uf5_pg_note"] = "empty verdict"
    return {}


_WORKER_PROC = None

