"""uf5vmjt.lib.sections.check — ad-hoc proxy check section.

Paste :// lines (no clash YAML) -> sidecar builds the sing-box batch,
runs it, polls Clash delays per probe and resolves egress geoip per
alive probe. Gated by ACCESS_TOKEN like Shell/Logs. Results render in
uf5-geocard-styled cards with flag watermarks, paginated client-side.
"""
from __future__ import annotations
import html
from lib.core.auth import require_auth
from lib.core.config import COLOR_ERR, COLOR_MUTED, COLOR_OK, COLOR_WARN
from lib.core.events import log_event
from lib.core.ui import badge, card, card_end
from lib.services.netinfo import flag_url
from lib.services.sidecar import worker_check_poll, worker_check_start


PAGE_SIZE = 25
POLL_EVERY_SEC = 2
POLL_BUDGET_SEC = 1200


def _latency_badge(alive: bool, ms) -> str:
    if not alive:
        return badge("dead", COLOR_MUTED)
    try:
        ms = int(ms or 0)
    except (TypeError, ValueError):
        return badge("?", COLOR_MUTED)
    if ms < 300:
        return badge(f"{ms} ms", COLOR_OK)
    if ms < 800:
        return badge(f"{ms} ms", COLOR_WARN)
    return badge(f"{ms} ms", COLOR_ERR)


def _row_html(r: dict) -> str:
    geo = r.get("geo") or {}
    cc = str(geo.get("country_code", "") or "")
    flag = flag_url(cc)
    small = f'<img class="uf5-flag" src="{flag}" alt="{html.escape(cc)}"/>' if flag else ""
    name = html.escape(str(r.get("name") or r.get("tag") or "?"))
    ip = html.escape(str(geo.get("ip", "") or ""))
    place = html.escape(str(geo.get("city") or geo.get("country") or ""))
    org = html.escape(str(geo.get("org") or ""))
    asn = geo.get("asn") or "?"
    err = html.escape(str(r.get("error") or ""))
    sub = " · ".join(p for p in (ip, place, f"AS{asn} {org}".strip()) if p)
    if not r.get("alive") and err:
        sub = (sub + " · " if sub else "") + err
    return (
        f'<div class="uf5-checkrow">{small}'
        f'<span class="uf5-checkrow-main"><b>{name}</b>'
        f'<span class="uf5-muted">{sub}</span></span>'
        f'{_latency_badge(r.get("alive"), r.get("latency_ms"))}</div>'
    )


def _summary_card(run: dict) -> str:
    results = run.get("results") or []
    alive = [r for r in results if r.get("alive")]
    lat = sorted(int(r.get("latency_ms") or 0) for r in alive if r.get("latency_ms"))
    med = lat[len(lat) // 2] if lat else 0
    ccs = sorted({str((r.get("geo") or {}).get("country_code") or "?") for r in alive})
    top_cc = ccs[0] if len(ccs) == 1 and ccs[0] != "?" else ""
    flag = flag_url(top_cc)
    big = f'<img class="uf5-geocard-bg" src="{flag}" alt=""/>' if flag else ""
    state = run.get("state", "?")
    state_badge = badge(state, COLOR_OK if state == "done" else COLOR_WARN)
    dead = len(results) - len(alive)
    pending = max(0, int(run.get("total") or 0) - len(results))
    line2 = f"{len(alive)} alive · {dead} dead"
    if pending:
        line2 += f" · {pending} running"
    if med:
        line2 += f" · median {med} ms"
    if len(ccs) > 1 or (ccs and ccs[0] != "?"):
        shown = ", ".join(c for c in ccs[:6] if c != "?") or "?"
        line2 += f" · {shown}"
    return (
        f'<div class="uf5-geocard">{big}<div class="uf5-geo-fg">'
        f'<div class="uf5-geo-ip"><span class="uf5-big">Check {html.escape(str(run.get("run_id", "")))}</span>'
        f"{state_badge}</div>"
        f"<div>{html.escape(line2)}</div>"
        f"</div></div>"
    )


def render_check() -> None:
    import streamlit as st

    if not require_auth():
        return
    card("Proxy check")
    st.caption("Только :// строки (vless/vmess/trojan/ss/socks/http/hy2/tuic/wireguard), по одной на строку. Без clash YAML — невалидные строки отсеются с причиной.")
    st.text_area("Ссылки", key="uf5_check_input", height=220, label_visibility="collapsed",
                 placeholder="vless://…\ntrojan://…")
    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        timeout_s = st.selectbox("Таймаут", [5, 10, 20], index=1, key="uf5_check_timeout")
    with c2:
        go = st.button("Проверить", key="uf5_check_go", use_container_width=True)
    if go:
        lines = [l for l in str(st.session_state.get("uf5_check_input") or "").splitlines() if l.strip()]
        if not lines:
            st.warning("Вставь хотя бы одну строку.")
        else:
            with st.spinner(f"sidecar разбирает {len(lines)} строк…"):
                start = worker_check_start(lines, timeout_ms=int(timeout_s) * 1000)
            if start.get("error"):
                st.error(start["error"])
                log_event("warn", f"check start failed: {start['error']}", source="check")
            else:
                st.session_state["uf5_check_run"] = {
                    "run_id": start["run_id"], "state": "running",
                    "total": len(start.get("accepted") or []),
                    "results": [], "rejected": start.get("rejected") or [],
                    "accepted": start.get("accepted") or [],
                }
                st.session_state["uf5_check_page"] = 0
                st.session_state["uf5_check_filter"] = "all"
                log_event("ok", f"check started: {start['run_id']} "
                                f"({len(start.get('accepted') or [])} probes, "
                                f"{len(start.get('rejected') or [])} rejected)", source="check")
                st.rerun()
    run = st.session_state.get("uf5_check_run")
    if not run:
        card_end()
        return

    if run.get("state") == "running":
        try:
            live = st.fragment(run_every=POLL_EVERY_SEC)
        except TypeError:
            live = st.fragment

        @live
        def _poll() -> None:
            snap = worker_check_poll(run["run_id"])
            if snap and snap.get("run_id"):
                run.update({k: snap.get(k, run.get(k)) for k in
                            ("state", "total", "results", "rejected")})
                run["done"] = snap.get("done", run.get("done", 0))
                if run.get("state") in ("done", "error"):
                    log_event("ok" if run["state"] == "done" else "warn",
                              f"check {run['run_id']}: {run['state']} "
                              f"({len(run.get('results') or [])} results)", source="check")
            done = len(run.get("results") or [])
            total = int(run.get("total") or 0)
            st.progress(min(1.0, done / total) if total else 0.0,
                        text=f"{run.get('state', '?')} — {done}/{total}")
            if run.get("state") == "error" and run.get("detail"):
                st.error(str(run["detail"]))

        _poll()

    st.markdown(_summary_card(run), unsafe_allow_html=True)

    rejected = run.get("rejected") or []
    if rejected:
        with st.expander(f"Отсеяно: {len(rejected)}"):
            for r in rejected[:100]:
                st.caption(f"строка {r.get('index', '?')}: {r.get('reason', '?')}")

    results = list(run.get("results") or [])
    f1, f2, _ = st.columns([1, 1, 2])
    with f1:
        flt = st.selectbox("Показать", ["all", "alive", "dead"], key="uf5_check_filter",
                           format_func={"all": "Все", "alive": "Живые", "dead": "Мёртвые"}.get)
    with f2:
        srt = st.selectbox("Порядок", ["latency", "input"], key="uf5_check_sort",
                           format_func={"latency": "Сначала быстрые", "input": "Как вставлено"}.get)
    if flt == "alive":
        results = [r for r in results if r.get("alive")]
    elif flt == "dead":
        results = [r for r in results if not r.get("alive")]
    if srt == "latency":
        results.sort(key=lambda r: (not r.get("alive"), int(r.get("latency_ms") or 10 ** 9)))
    else:
        results.sort(key=lambda r: int(r.get("index") or 0))

    total_pages = max(1, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(int(st.session_state.get("uf5_check_page") or 0), total_pages - 1)
    chunk = results[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    if not chunk:
        st.caption("Пока пусто — опрос идёт, страница обновится сама.")
    for r in chunk:
        st.markdown(_row_html(r), unsafe_allow_html=True)
    p1, p2, p3 = st.columns([1, 1, 4])
    with p1:
        if st.button("← Назад", key="uf5_check_prev", disabled=page == 0, use_container_width=True):
            st.session_state["uf5_check_page"] = page - 1
            st.rerun()
    with p2:
        if st.button("Вперёд →", key="uf5_check_next",
                     disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state["uf5_check_page"] = page + 1
            st.rerun()
    with p3:
        st.caption(f"стр. {page + 1}/{total_pages} · всего {len(results)}")
    card_end()
