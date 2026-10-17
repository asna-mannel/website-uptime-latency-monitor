
import json
import os
import shutil
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="Website Uptime & Latency Monitor",
    page_icon="🌐",
    layout="wide",
)

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
HISTORY_FILE = Path(
    os.getenv("HISTORY_FILE", str(DATA_DIR / "monitoring_history.csv"))
)
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_URLS = [
    "https://www.google.com",
    "https://www.github.com",
    "https://www.python.org",
    "https://streamlit.io",
    "https://instgram.com",
]

CURL_FORMAT = (
    '{"http_code":%{http_code},'
    '"time_namelookup":%{time_namelookup},'
    '"time_connect":%{time_connect},'
    '"time_appconnect":%{time_appconnect},'
    '"time_pretransfer":%{time_pretransfer},'
    '"time_starttransfer":%{time_starttransfer},'
    '"time_total":%{time_total},'
    '"remote_ip":"%{remote_ip}"}'
)


def load_history():
    if not HISTORY_FILE.exists() or HISTORY_FILE.stat().st_size == 0:
        return pd.DataFrame()

    try:
        df = pd.read_csv(HISTORY_FILE)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], errors="coerce"
            )
        return df
    except (pd.errors.ParserError, OSError, ValueError):
        return pd.DataFrame()


def save_history(df):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(HISTORY_FILE, index=False)


def check_website(url, timeout):
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    clean_url = url.strip()

    if clean_url and not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    record = {
        "timestamp": checked_at,
        "website": clean_url,
        "status": "DOWN",
        "http_code": 0,
        "dns_ms": None,
        "tcp_ms": None,
        "tls_ms": None,
        "ttfb_ms": None,
        "total_ms": None,
        "remote_ip": "",
        "error": "",
        "probe_host": socket.gethostname(),
    }

    if not clean_url:
        record["error"] = "Empty URL"
        return record

    curl_path = shutil.which("curl")

    if not curl_path:
        record["error"] = "curl is not installed"
        return record

    command = [
        curl_path,
        "-L",
        "-sS",
        "-o",
        os.devnull,
        "-w",
        CURL_FORMAT,
        "--max-time",
        str(timeout),
        clean_url,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout + 3,
            check=False,
        )

        metrics = (
            json.loads(result.stdout.strip())
            if result.stdout.strip()
            else {}
        )

        http_code = int(metrics.get("http_code", 0) or 0)
        dns = float(metrics.get("time_namelookup", 0) or 0)
        connect = float(metrics.get("time_connect", 0) or 0)
        appconnect = float(metrics.get("time_appconnect", 0) or 0)
        pretransfer = float(metrics.get("time_pretransfer", 0) or 0)
        starttransfer = float(metrics.get("time_starttransfer", 0) or 0)
        total = float(metrics.get("time_total", 0) or 0)

        record.update({
            "http_code": http_code,
            "dns_ms": round(dns * 1000, 2),
            "tcp_ms": round(max(0, connect - dns) * 1000, 2),
            "tls_ms": (
                round(max(0, appconnect - connect) * 1000, 2)
                if clean_url.startswith("https://") and appconnect > 0
                else None
            ),
            "ttfb_ms": round(
                max(0, starttransfer - pretransfer) * 1000, 2
            ),
            "total_ms": round(total * 1000, 2),
            "remote_ip": metrics.get("remote_ip", ""),
        })

        if 200 <= http_code < 400:
            record["status"] = "UP"
        else:
            record["error"] = (
                result.stderr.strip() or f"HTTP status {http_code}"
            )

    except subprocess.TimeoutExpired:
        record["error"] = f"Request timed out after {timeout} seconds"
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        record["error"] = f"Could not parse curl result: {exc}"
    except OSError as exc:
        record["error"] = str(exc)

    return record


def run_checks(urls, timeout, current_history):
    new_records = []
    progress = st.progress(0, text="Starting website checks...")

    for index, url in enumerate(urls):
        new_records.append(check_website(url, timeout))
        progress.progress(
            (index + 1) / len(urls),
            text=f"Checked {index + 1} of {len(urls)} websites",
        )

    progress.empty()

    new_df = pd.DataFrame(new_records)

    if current_history.empty:
        combined = new_df
    else:
        combined = pd.concat(
            [current_history, new_df], ignore_index=True
        )

    combined["timestamp"] = pd.to_datetime(
        combined["timestamp"], errors="coerce"
    )
    save_history(combined)

    return combined, new_records


# Dashboard heading
st.title("🌐 Synthetic Website Uptime & Global Edge Latency Monitor")
st.caption(
    "Measures website availability and request timings from this running "
    "instance. Genuine global measurements require probes in separate regions."
)

# Sidebar settings
with st.sidebar:
    st.header("Monitor settings")

    urls_text = st.text_area(
        "Websites to monitor (one URL per line)",
        value="\n".join(DEFAULT_URLS),
        height=150,
    )

    timeout = st.slider("Request timeout (seconds)", 2, 30, 15)

    auto_monitor = st.toggle("Automatic checks", value=True)

    refresh_seconds = st.selectbox(
        "Automatic check interval",
        options=[30, 60, 120, 300],
        index=1,
        format_func=lambda seconds: f"{seconds} seconds",
        disabled=not auto_monitor,
    )

    manual_check = st.button(
        "Check websites now",
        type="primary",
        use_container_width=True,
    )

    clear_requested = st.button(
        "Clear history",
        use_container_width=True,
    )

    st.divider()
    st.caption(f"Running instance: {socket.gethostname()}")
    st.caption(f"History file: {HISTORY_FILE}")

# Refresh dashboard automatically
if auto_monitor:
    st_autorefresh(
        interval=refresh_seconds * 1000,
        key="website_monitor_autorefresh",
    )

# Read website URLs
urls = []

for line in urls_text.splitlines():
    url = line.strip()

    if url and url not in urls:
        urls.append(url)

# Initialize session state
if "monitor_history" not in st.session_state:
    st.session_state.monitor_history = load_history()
    st.session_state.last_auto_check = 0.0

# Clear saved history
if clear_requested:
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()

    st.session_state.monitor_history = pd.DataFrame()
    st.session_state.last_auto_check = time.time()
    st.success("History cleared.")
    st.rerun()

# Run scheduled checks
now = time.time()

auto_check_due = (
    auto_monitor
    and bool(urls)
    and now - st.session_state.last_auto_check >= refresh_seconds
)

if manual_check and urls:
    with st.spinner("Checking websites..."):
        updated_history, results = run_checks(
            urls,
            timeout,
            st.session_state.monitor_history,
        )

    st.session_state.monitor_history = updated_history
    st.session_state.last_auto_check = time.time()

    up_count = sum(item["status"] == "UP" for item in results)

    st.success(
        f"Completed {len(results)} checks. "
        f"{up_count} website(s) are UP."
    )

elif auto_check_due:
    with st.spinner("Running scheduled website checks..."):
        updated_history, results = run_checks(
            urls,
            timeout,
            st.session_state.monitor_history,
        )

    st.session_state.monitor_history = updated_history
    st.session_state.last_auto_check = time.time()

    up_count = sum(item["status"] == "UP" for item in results)

    st.toast(
        f"Automatic check complete: {up_count}/{len(results)} websites UP."
    )

# Load monitoring history
history = st.session_state.monitor_history.copy()

if history.empty:
    st.info(
        "No monitoring history yet. Keep Automatic checks enabled or "
        "click 'Check websites now' to collect measurements."
    )
    st.stop()

history["timestamp"] = pd.to_datetime(
    history["timestamp"], errors="coerce"
)
history = history.dropna(subset=["timestamp"])

if history.empty:
    st.warning("No valid timestamped records are available.")
    st.stop()

for column in [
    "http_code", "dns_ms", "tcp_ms",
    "tls_ms", "ttfb_ms", "total_ms"
]:
    if column in history.columns:
        history[column] = pd.to_numeric(
            history[column], errors="coerce"
        )

if "status" not in history.columns:
    history["status"] = "DOWN"

if "probe_host" not in history.columns:
    history["probe_host"] = "unknown"

# Latest status for each website
latest = (
    history.sort_values("timestamp")
    .groupby("website", as_index=False)
    .tail(1)
    .sort_values("website")
)

total_checks = len(history)
up_checks = int((history["status"] == "UP").sum())
overall_uptime = (
    up_checks / total_checks * 100 if total_checks else 0
)
latest_up = int((latest["status"] == "UP").sum())

# Summary metrics
c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Websites monitored",
    int(history["website"].nunique()),
)
c2.metric(
    "Latest websites UP",
    f"{latest_up}/{len(latest)}",
)
c3.metric(
    "Overall recorded uptime",
    f"{overall_uptime:.2f}%",
)
c4.metric(
    "Total checks recorded",
    total_checks,
)

# Latest website status
st.subheader("Latest Website Status")

status_columns = [
    col for col in [
        "website", "timestamp", "status", "http_code",
        "total_ms", "remote_ip", "error", "probe_host"
    ]
    if col in latest.columns
]

st.dataframe(
    latest[status_columns],
    use_container_width=True,
    hide_index=True,
)

# Uptime percentage
st.subheader("Uptime Percentage by Website")

uptime = (
    history.assign(
        is_up=(history["status"] == "UP").astype(int)
    )
    .groupby("website", as_index=False)
    .agg(
        total_checks=("is_up", "size"),
        successful_checks=("is_up", "sum"),
        uptime_percent=(
            "is_up",
            lambda values: values.mean() * 100,
        ),
    )
    .sort_values("uptime_percent", ascending=True)
)

uptime["uptime_percent"] = uptime["uptime_percent"].round(2)

st.dataframe(
    uptime,
    use_container_width=True,
    hide_index=True,
)

uptime_fig = px.bar(
    uptime,
    x="website",
    y="uptime_percent",
    range_y=[0, 100],
    text="uptime_percent",
    title="Recorded uptime by website",
    labels={
        "website": "Website",
        "uptime_percent": "Uptime (%)",
    },
)

uptime_fig.update_traces(
    texttemplate="%{text:.2f}%",
    textposition="outside",
)
uptime_fig.update_layout(xaxis_tickangle=-25)

st.plotly_chart(uptime_fig, use_container_width=True)

# Downtime timeline
st.subheader("Downtime Timeline")

selected_website = st.selectbox(
    "Select website for downtime timeline",
    sorted(history["website"].dropna().unique()),
)

timeline = history[
    history["website"] == selected_website
].sort_values("timestamp")

hover_columns = [
    col for col in ["status", "http_code", "error"]
    if col in timeline.columns
]

timeline_fig = go.Figure()

timeline_fig.add_trace(
    go.Scatter(
        x=timeline["timestamp"],
        y=(timeline["status"] == "UP").astype(int) * 100,
        mode="lines+markers",
        line_shape="hv",
        name="Availability",
        customdata=(
            timeline[hover_columns].astype(str).to_numpy()
            if hover_columns else None
        ),
        hovertemplate=(
            "Time: %{x}<br>"
            "Availability: %{y}%<br>"
            "Details: %{customdata}<extra></extra>"
        ),
    )
)

timeline_fig.update_layout(
    title=f"Availability history — {selected_website}",
    xaxis_title="Time",
    yaxis_title="Availability (100 = UP, 0 = DOWN)",
    yaxis={
        "tickmode": "array",
        "tickvals": [0, 100],
        "range": [-10, 110],
    },
)

st.plotly_chart(timeline_fig, use_container_width=True)

# Latency comparison
st.subheader("Regional Latency Comparison")

st.caption(
    "This compares recorded probe instances. If all records come from one "
    "instance, it is not a global regional comparison."
)

latency_columns = [
    col for col in ["dns_ms", "tcp_ms", "tls_ms", "ttfb_ms"]
    if col in history.columns
]

if latency_columns:
    latency_long = history.melt(
        id_vars=["website", "probe_host"],
        value_vars=latency_columns,
        var_name="latency_type",
        value_name="latency_ms",
    ).dropna(subset=["latency_ms"])

    if not latency_long.empty:
        latency_summary = (
            latency_long.groupby(
                ["website", "probe_host", "latency_type"],
                as_index=False,
            )["latency_ms"].mean()
        )

        latency_summary["latency_ms"] = (
            latency_summary["latency_ms"].round(2)
        )

        latency_fig = px.bar(
            latency_summary,
            x="website",
            y="latency_ms",
            color="latency_type",
            barmode="group",
            facet_col="probe_host",
            title="Average DNS, TCP, TLS and TTFB latency",
            labels={
                "website": "Website",
                "latency_ms": "Average latency (ms)",
                "latency_type": "Timing component",
                "probe_host": "Probe instance",
            },
        )

        latency_fig.update_layout(xaxis_tickangle=-25)
        st.plotly_chart(latency_fig, use_container_width=True)

    else:
        st.info("Latency measurements will appear after timing data is collected.")
else:
    st.info("Latency columns are not available in the stored history.")

# Total response time chart
if "total_ms" in history.columns:
    total_fig = px.line(
        history.sort_values("timestamp"),
        x="timestamp",
        y="total_ms",
        color="website",
        markers=True,
        title="Total request time over time",
        labels={
            "timestamp": "Time",
            "total_ms": "Total request time (ms)",
            "website": "Website",
        },
    )

    st.plotly_chart(total_fig, use_container_width=True)

# All recorded checks
st.subheader("All Recorded Checks")

display_history = history.sort_values(
    "timestamp",
    ascending=False,
)

st.dataframe(
    display_history,
    use_container_width=True,
    hide_index=True,
)

st.download_button(
    "Download monitoring history (CSV)",
    data=display_history.to_csv(index=False).encode("utf-8"),
    file_name="monitoring_history.csv",
    mime="text/csv",
)

st.caption(
    f"Automatic checks: {'enabled' if auto_monitor else 'disabled'}. "
    "Checks run from this container; separate regional probes are required "
    "for genuine global edge-latency measurements."
)
