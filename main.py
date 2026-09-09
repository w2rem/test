"""uf5vmjt — Streamlit system monitor: stats, shell, logs.

Sections (sidebar): stats (memory/CPU/geo/cluster/versions), shell (command
runner with rendered history), logs (unified event stream, incl. Go sidecar).
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
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

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
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
    for fs in fs_list:
        total, used, free = fs["total"], fs["used"], fs["free"]
        pct = used / total * 100
        st.markdown(f"**`{fs['mount']}`**  "
                    f"<span class='uf5-muted'>{fmt_gb(used)} of {fmt_gb(total)} · {pct:.1f}%</span>",
                    unsafe_allow_html=True)
        bar = (
            f'<div class="uf5-memseg" title="used {fmt_gb(used)}" '
            f'style="width:{pct:.2f}%;background:{COLOR_ACCENT}"></div>'
            f'<div class="uf5-memseg" title="free {fmt_gb(free)}" '
            f'style="width:{100 - pct:.2f}%;background:{COLOR_ACCENT_PALE}"></div>'
        )
        st.markdown(f'<div class="uf5-memtrack">{bar}</div>', unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Total", fmt_gb(total))
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
            f'<div style="width:130px;text-align:right;font-family:monospace;'
            f'font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">/{name}</div>'
            f'<div class="uf5-memtrack" style="height:22px;flex:1;">'
            f'<div class="uf5-memseg" style="width:{size / top * 100:.2f}%;'
            f'background:{COLOR_ACCENT};opacity:{opacity}"></div></div>'
            f'<div style="width:90px;font-size:12px;font-weight:600;">{fmt_gb(size)}</div></div>'
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
    """Read rebuild/icons/<name>.svg, force one size, recolor dark fills."""
    path = os.path.join(ICON_DIR, f"{name}.svg")
    try:
        with open(path) as f:
            svg = f.read()
    except OSError:
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
        section[data-testid="stSidebar"] {{ background: {COLOR_PANEL}; }}
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
        /* Sidebar nav: icon list, no radio dots, no emoji. */
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label > div:first-child {{
            display: none;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label {{
            display: flex !important; align-items: center; gap: 10px;
            padding: 9px 12px !important; border-radius: 10px;
            font-size: 14px; font-weight: 600; color: {COLOR_TEXT};
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {{
            background: {COLOR_ACCENT_PALE};
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {{
            background: {COLOR_ACCENT}; color: #fff;
            box-shadow: 0 4px 12px -4px rgba(74,127,165,.6);
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label::before {{
            content: ""; width: 17px; height: 17px; flex: none;
            background-size: contain; background-repeat: no-repeat;
            background-position: center;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:nth-of-type(1)::before {{
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234A7FA5' stroke-width='2.4' stroke-linecap='round'%3E%3Cpath d='M5 20v-6M11 20V5M17 20v-9'/%3E%3C/svg%3E");
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:nth-of-type(2)::before {{
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234A7FA5' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='4' width='18' height='16' rx='3'/%3E%3Cpath d='M7 10l3 3-3 3M12 16h5'/%3E%3C/svg%3E");
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:nth-of-type(3)::before {{
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234A7FA5' stroke-width='2.4' stroke-linecap='round'%3E%3Cpath d='M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01'/%3E%3C/svg%3E");
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked)::before {{
            filter: brightness(0) invert(1);
        }}
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
    c1.metric("Total", fmt_mb(total))
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
    m2.metric("Busy cores", sum(1 for v in per_core.values() if v >= 5),
              f"of {len(per_core)}", delta_color="off")
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

    with tab_mem:
        @live
        def _live_memory() -> None:
            render_memory_bar()

        _live_memory()

    with tab_cpu:
        @live
        def _live_cpu() -> None:
            render_cpu_panel()

        _live_cpu()

    with tab_disk:
        @slow
        def _live_disk() -> None:
            render_disk_panel()

        _live_disk()


def render_geo_cluster() -> None:
    """Network block without card chrome: flag + IP + shard badge, watermark behind."""
    import streamlit as st

    geo = get_geo()
    cluster = get_cluster()
    if not geo:
        st.caption("geo unavailable")
        return
    cc = str(geo.get("country_code", ""))
    flag = flag_url(cc)
    shard = str(cluster.get("cluster", "") or "")
    small = f'<img class="uf5-flag" src="{flag}" alt="{cc}"/>' if flag else ""
    big = f'<img class="uf5-geocard-bg" src="{flag}" alt=""/>' if flag else ""
    st.markdown(
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
    for col, label, icon, resolver in (
        (cols[0], "Python", "python", resolve_python_version),
        (cols[1], "Go", "go", resolve_go_version),
        (cols[2], "Tailscale", "tailscale", resolve_tailscale_version),
    ):
        with col:
            svg = load_icon(icon)
            with st.spinner(f"resolving {label.lower()}…"):
                version = resolver()
            color = COLOR_OK if version not in ("not installed", "error", "unknown") else COLOR_MUTED
            st.markdown(
                f'<div class="uf5-ver">{svg}<span class="uf5-ver-name">{label}</span>'
                f'{badge(version, color)}</div>',
                unsafe_allow_html=True)
            log_event("debug", f"version {label}={version}")


def render_stats() -> None:
    render_canvas()
    render_geo_cluster()
    render_versions()


# ---------------------------------------------------------------------------
# Shell section.
# ---------------------------------------------------------------------------

def render_shell() -> None:
    """Single command line + rendered history (exit code, stdout, stderr)."""
    import streamlit as st

    st.session_state.setdefault("uf5_shell_hist", [])
    st.session_state.setdefault("uf5_cwd", os.getcwd())

    st.caption(f"cwd: `{st.session_state['uf5_cwd']}` · timeout {SHELL_TIMEOUT_SEC}s")
    with st.form("uf5_shell_form", clear_on_submit=True):
        cmd = st.text_input("Command", placeholder="ls -la /tmp",
                            label_visibility="collapsed")
        run = st.form_submit_button("Run ⏎", width="stretch")
    if run and cmd and cmd.strip():
        cmd = cmd.strip()
        if cmd.startswith("cd"):
            target = cmd[2:].strip() or os.path.expanduser("~")
            dest = os.path.join(st.session_state["uf5_cwd"], os.path.expanduser(target))
            if os.path.isdir(dest):
                st.session_state["uf5_cwd"] = os.path.abspath(dest)
                log_event("info", f"shell cd -> {st.session_state['uf5_cwd']}")
            else:
                st.session_state["uf5_shell_hist"].append(
                    {"cmd": cmd, "cwd": st.session_state["uf5_cwd"], "rc": 1,
                     "out": "", "err": f"no such directory: {target}", "ms": 0})
            st.rerun()
        else:
            entry = run_shell_command(cmd, st.session_state["uf5_cwd"])
            st.session_state["uf5_shell_hist"].append(entry)
            del st.session_state["uf5_shell_hist"][:-SHELL_HISTORY_LIMIT]
            level = "ok" if entry["rc"] == 0 else "error"
            log_event(level, f"shell exit={entry['rc']} ms={entry['ms']}: {cmd[:120]}")
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
# Entry point.
# ---------------------------------------------------------------------------

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="uf5vmjt", layout="wide")
    inject_style()

    section = st.sidebar.radio("Section", ["stats", "shell", "logs"],
                               key="uf5_section")
    st.sidebar.divider()
    log_event("debug", f"section opened: {section}")

    if section == "stats":
        render_stats()
    elif section == "shell":
        render_shell()
    else:
        render_logs()


if __name__ == "__main__":
    main()
