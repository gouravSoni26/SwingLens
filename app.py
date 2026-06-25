"""
app.py
------
NSE Trading Analyst — Streamlit UI
Run with: streamlit run app.py
"""

import streamlit as st
from analyzer import analyze_setup
from storage import init_db, save_to_sqlite, save_to_obsidian, get_history, get_by_id
import os
from dotenv import load_dotenv

load_dotenv()
init_db()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NSE Trading Analyst",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ──────────────────────────────────────────────────────────────────
VIEW_STYLE = {
    "bullish":      ("E1F5EE", "9FE1CB", "0F6E56", "↑ Bullish"),
    "bearish":      ("FAECE7", "F5C4B3", "993C1D", "↓ Bearish"),
    "neutral":      ("FAEEDA", "FAC775", "854F0B", "→ Neutral"),
    "unclear":      ("F1EFE8", "D3D1C7", "888780", "? Unclear"),
    "not_described":("F1EFE8", "D3D1C7", "888780", "— N/A"),
}

GOV_LABELS = {
    "nse_cash":     "NSE cash equity only",
    "swing_period": "Swing hold period",
    "not_intraday": "Not intraday scalp",
    "risk_limit":   "Risk ≤ 1.5% per trade",
    "no_auto":      "No auto-execution",
}

TFS = [("Monthly","monthly"), ("Weekly","weekly"), ("Daily","daily"), ("1H","h1")]


# ── HTML helpers ───────────────────────────────────────────────────────────────
def tf_pill(view: str, label: str) -> str:
    bg, bd, tx, lbl = VIEW_STYLE.get(view, VIEW_STYLE["not_described"])
    return (
        f'<div style="background:#{bg};border:1px solid #{bd};border-radius:6px;'
        f'padding:8px 10px;text-align:center">'
        f'<div style="font-size:10px;color:#{tx};opacity:.8;text-transform:uppercase;'
        f'letter-spacing:.08em;margin-bottom:2px">{label}</div>'
        f'<div style="font-size:12px;color:#{tx};font-weight:500;font-family:monospace">{lbl}</div>'
        f'</div>'
    )

def tf_card(label: str, data: dict) -> str:
    view = data.get("view", "not_described")
    bg, bd, tx, lbl = VIEW_STYLE.get(view, VIEW_STYLE["not_described"])
    trend  = data.get("trend", "—")
    levels = ", ".join(data.get("levels", [])) or "None noted"
    return (
        f'<div style="border:1px solid #e5e5e5;border-radius:8px;padding:12px;margin-bottom:8px">'
        f'  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
        f'    <span style="font-size:11px;font-weight:500;text-transform:uppercase;color:#A0A0A0">{label}</span>'
        f'    <span style="background:#{bg};border:1px solid #{bd};color:#{tx};'
        f'           padding:2px 8px;border-radius:4px;font-size:10px;font-family:monospace">{lbl}</span>'
        f'  </div>'
        f'  <div style="font-size:11px;color:#E0E0E0;margin-bottom:2px"><span style="color:#A0A0A0">Trend: </span>{trend}</div>'
        f'  <div style="font-size:11px;color:#E0E0E0"><span style="color:#A0A0A0">Levels: </span>{levels}</div>'
        f'</div>'
    )

def risk_row(label: str, value: str, fail: bool = False) -> str:
    color = "#D85A30" if fail else "#E8E8E8"
    return (
        f'<div style="display:flex;justify-content:space-between;padding:5px 0;'
        f'border-bottom:1px solid #f5f5f5">'
        f'  <span style="font-size:12px;color:#A0A0A0">{label}</span>'
        f'  <span style="font-size:12px;font-family:monospace;color:{color}">{value}</span>'
        f'</div>'
    )

def gov_row(label: str, status: str) -> str:
    if status == "pass":
        dot, stc = "#1D9E75", "#1D9E75"
    elif status == "fail":
        dot, stc = "#D85A30", "#D85A30"
    else:
        dot, stc = "#BA7517", "#BA7517"
    display = "N/A" if status == "not_calculable" else status.upper()
    return (
        f'<div style="display:flex;align-items:center;gap:8px;padding:5px 0;'
        f'border-bottom:1px solid #f5f5f5">'
        f'  <span style="color:{dot};font-size:14px">●</span>'
        f'  <span style="font-size:12px;flex:1;color:#D0D0D0">{label}</span>'
        f'  <span style="font-size:11px;font-family:monospace;font-weight:500;color:{stc}">{display}</span>'
        f'</div>'
    )


# ── Report renderer ────────────────────────────────────────────────────────────
def render_report(analysis: dict, obsidian_key: str, obsidian_host: str) -> None:
    tk  = analysis.get("ticker", "")
    tf  = analysis.get("timeframes", {})
    rsk = analysis.get("risk", {})
    gov = analysis.get("governance", {})

    # Header
    st.markdown(
        f"## {tk} &nbsp;"
        f'<span style="font-size:12px;background:#f0f0f0;padding:2px 8px;'
        f'border-radius:4px;color:#888;font-family:monospace">NSE CASH</span>',
        unsafe_allow_html=True,
    )

    # Alignment strip
    st.markdown("**Timeframe alignment**")
    cols = st.columns(4)
    for i, (lbl, k) in enumerate(TFS):
        d    = tf.get(k, {})
        view = d.get("view", "not_described")
        with cols[i]:
            st.markdown(tf_pill(view, lbl), unsafe_allow_html=True)

    # Overall bar
    overall_align = analysis.get("alignment_summary", "—")
    st.markdown(
        f'<div style="background:#f8f8f8;border-radius:6px;padding:8px 14px;'
        f'display:flex;justify-content:space-between;align-items:center;margin-top:8px">'
        f'  <span style="font-size:11px;color:#999;text-transform:uppercase;letter-spacing:.08em">Overall alignment</span>'
        f'  <span style="font-size:12px;font-weight:500;font-family:monospace">{overall_align}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.divider()

    # Timeframe detail cards (2x2 grid)
    st.markdown("**Timeframe detail**")
    c1, c2 = st.columns(2)
    for i, (lbl, k) in enumerate(TFS):
        col = c1 if i % 2 == 0 else c2
        with col:
            st.markdown(tf_card(lbl, tf.get(k, {})), unsafe_allow_html=True)

    st.divider()

    # Risk + Governance side by side
    rc, gc = st.columns(2)

    with rc:
        st.markdown("**Risk parameters**")
        rv = rsk.get
        is_fail = rsk.get("risk_pass") is False
        html = ""
        html += risk_row("Entry",     f"₹ {rv('entry')}"   if rv("entry")  is not None else "—")
        html += risk_row("Stop-loss", f"₹ {rv('sl')}"      if rv("sl")     is not None else "—")
        html += risk_row("Target",    f"₹ {rv('target')}"  if rv("target") is not None else "—")
        html += risk_row(
            "Risk / trade",
            f"{rv('risk_pct')}%{' ⚠' if is_fail else ''}" if rv("risk_pct") is not None else "—",
            fail=is_fail,
        )
        html += risk_row("R : R", f"1 : {rv('rr')}" if rv("rr") is not None else "—")
        st.markdown(html, unsafe_allow_html=True)

    with gc:
        st.markdown("**Governance check**")
        html = ""
        for k, lbl in GOV_LABELS.items():
            html += gov_row(lbl, gov.get(k, "unknown"))
        st.markdown(html, unsafe_allow_html=True)

    st.divider()

    # Narrative
    st.markdown("**Narrative summary**")
    st.info(analysis.get("narrative", "—"))

    # Missing info
    missing = analysis.get("missing_info", [])
    if missing:
        with st.expander("📋 Missing information"):
            for m in missing:
                st.write(f"· {m}")

    # Save actions
    st.markdown("---")
    s1, s2 = st.columns(2)

    with s1:
        if st.button("💾 Save to SQLite", use_container_width=True):
            row_id = save_to_sqlite(analysis)
            st.success(f"Saved — row ID {row_id}")

    with s2:
        if st.button("📝 Save to Obsidian", use_container_width=True):
            if not obsidian_key:
                st.error("Add your Obsidian API key in the sidebar first.")
            else:
                ok, msg = save_to_obsidian(analysis, obsidian_key, obsidian_host)
                if ok:
                    st.success(f"Saved → {msg}")
                else:
                    st.error(f"Obsidian save failed: {msg}\n\nIs Obsidian open with Local REST API enabled?")


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Config")
    obsidian_key  = st.text_input(
        "Obsidian API Key",
        value=os.getenv("OBSIDIAN_API_KEY", ""),
        type="password",
        help="From Obsidian → Local REST API plugin settings",
    )
    obsidian_host = st.text_input(
        "Obsidian Host",
        value=os.getenv("OBSIDIAN_HOST", "localhost"),
        help="Usually localhost",
    )

    st.divider()
    st.markdown("### 📋 Recent Analyses")
    history = get_history(10)
    if history:
        for row in history:
            label = f"{row['ticker']} — {row['analysis_date']}"
            if st.button(label, key=f"hist_{row['id']}", use_container_width=True):
                st.session_state.loaded_analysis = get_by_id(row["id"])
    else:
        st.caption("No analyses yet — run your first one!")


# ── Main ───────────────────────────────────────────────────────────────────────
st.title("📊 NSE Trading Analyst")
st.caption("Paper trading · NSE cash equity · Research support only")

tab_analyze, tab_history = st.tabs(["Analyze", "History"])


# ── Tab 1: Analyze ─────────────────────────────────────────────────────────────
with tab_analyze:

    with st.form("setup_form", clear_on_submit=False):
        ticker = st.text_input(
            "Ticker",
            placeholder="e.g. RELIANCE",
            help="NSE stock symbol",
            key="field_ticker",
        )

        st.markdown("**Describe what you see on each timeframe**")
        col_l, col_r = st.columns(2)
        with col_l:
            monthly = st.text_area("Monthly", placeholder="Lower lows, volume declining...", height=90, key="field_monthly")
            daily   = st.text_area("Daily",   placeholder="Inside day coil, low volume...", height=90, key="field_daily")
        with col_r:
            weekly  = st.text_area("Weekly",  placeholder="Pulling back to 10-week EMA...", height=90, key="field_weekly")
            h1      = st.text_area("1H",      placeholder="Bull flag forming above support...", height=90, key="field_h1")

        st.markdown("**Risk parameters** *(optional)*")
        rc1, rc2, rc3 = st.columns(3)
        with rc1: entry  = st.text_input("Entry ₹",     placeholder="e.g. 2875", key="field_entry")
        with rc2: sl     = st.text_input("Stop-loss ₹", placeholder="e.g. 2810", key="field_sl")
        with rc3: target = st.text_input("Target ₹",    placeholder="e.g. 3020", key="field_target")

        submitted = st.form_submit_button(
            "Analyze Setup →",
            use_container_width=True,
            type="primary",
        )

    # Run analysis
    if submitted:
        if not ticker.strip():
            st.error("Please enter a ticker symbol.")
        else:
            with st.spinner(f"Analyzing {ticker.upper()}..."):
                try:
                    result, provider = analyze_setup(
                        ticker, monthly, weekly, daily, h1, entry, sl, target
                    )
                    st.session_state.last_analysis   = result
                    st.session_state.last_provider   = provider
                    st.session_state.loaded_analysis = None
                except Exception as e:
                    st.error(f"Analysis failed: {e}")
                    result = None

    # Show result
    active   = st.session_state.get("last_analysis") or st.session_state.get("loaded_analysis")
    provider = st.session_state.get("last_provider", "")
    if active:
        st.divider()
        if provider == "groq":
            st.warning("⚡ Analysed via Groq (Llama 3.3 70B) — Claude unavailable or key not set.")
        elif provider == "claude":
            st.success("✓ Analysed via Claude Sonnet 4")
        render_report(active, obsidian_key, obsidian_host)

    if st.button("🔄 Clear Analysis"):
        for k in ["last_analysis", "last_provider", "loaded_analysis",
                  "field_ticker", "field_monthly", "field_weekly",
                  "field_daily", "field_h1", "field_entry", "field_sl", "field_target"]:
            st.session_state.pop(k, None)
        st.rerun()


# ── Tab 2: History ─────────────────────────────────────────────────────────────
with tab_history:
    history = get_history(50)

    if not history:
        st.info("No analyses saved yet. Run your first setup analysis above.")
    else:
        st.markdown(f"**{len(history)} saved analyses**")

        # View selector
        VIEW_ICONS = {
            "bullish": "🟢", "bearish": "🔴",
            "neutral": "🟡", "unclear": "⚪", "not_described": "⚪",
        }

        for row in history:
            col_a, col_b, col_c, col_d, col_e, col_f = st.columns([2, 1, 1, 1, 1, 1])
            with col_a:
                st.markdown(f"**{row['ticker']}** — {row['analysis_date']}")
            with col_b:
                st.markdown(VIEW_ICONS.get(row["monthly_view"] or "", "⚪") + " Mo")
            with col_c:
                st.markdown(VIEW_ICONS.get(row["weekly_view"] or "", "⚪") + " Wk")
            with col_d:
                st.markdown(VIEW_ICONS.get(row["daily_view"] or "", "⚪") + " Dy")
            with col_e:
                st.markdown(VIEW_ICONS.get(row["h1_view"] or "", "⚪") + " 1H")
            with col_f:
                gov = row.get("governance_overall", "")
                badge = "✅" if gov == "clear" else "❌" if gov == "blocked" else "⚠️"
                if st.button(f"{badge} View", key=f"view_{row['id']}"):
                    st.session_state.loaded_analysis = get_by_id(row["id"])
                    st.session_state.last_analysis   = None

        # Show loaded analysis from history
        if st.session_state.get("loaded_analysis"):
            st.divider()
            render_report(st.session_state.loaded_analysis, obsidian_key, obsidian_host)
            if st.button("🔄 Clear Analysis", key="clear_history"):
                st.session_state.pop("loaded_analysis", None)
                st.rerun()
