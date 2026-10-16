
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(
    page_title="Website Uptime Monitor",
    page_icon="🌐",
    layout="wide",
)

st.title("🌐 Website Uptime & Latency Monitor")
st.write(
    "Monitor real websites, measure response times, "
    "and track availability."
)

DEFAULT_URLS = """https://www.google.com
https://www.github.com
https://www.python.org
https://www.streamlit.io"""

if "checks" not in st.session_state:
    st.session_state.checks = []

with st.sidebar:
    st.header("Monitoring Settings")

    urls_text = st.text_area(
        "Website URLs (one per line)",
        value=DEFAULT_URLS,
        height=150,
    )

    timeout = st.slider(
        "Request timeout (seconds)",
        min_value=2,
        max_value=20,
        value=8,
    )

    check_button = st.button(
        "Check websites now",
        type="primary",
        use_container_width=True,
    )

    if st.button("Clear history", use_container_width=True):
        st.session_state.checks = []
        st.rerun()

if check_button:
    urls = list(dict.fromkeys(
        line.strip()
        for line in urls_text.splitlines()
        if line.strip()
    ))

    if not urls:
        st.warning("Please enter at least one website URL.")
    else:
        progress = st.progress(0)
        status_message = st.empty()

        for index, url in enumerate(urls, start=1):
            if not url.startswith(("https://", "http://")):
                url = "https://" + url

            checked_at = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )

            start_time = time.perf_counter()

            try:
                response = requests.get(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    headers={"User-Agent": "WebsiteMonitor/1.0"},
                )

                response_time = round(
                    (time.perf_counter() - start_time) * 1000, 2
                )

                success = 200 <= response.status_code < 400

                record = {
                    "checked_at": checked_at,
                    "website": url,
                    "status_code": response.status_code,
                    "response_time_ms": response_time,
                    "success": success,
                    "result": "Online" if success else "HTTP Error",
                    "error": "",
                }

            except requests.RequestException as exc:
                response_time = round(
                    (time.perf_counter() - start_time) * 1000, 2
                )

                record = {
                    "checked_at": checked_at,
                    "website": url,
                    "status_code": None,
                    "response_time_ms": response_time,
                    "success": False,
                    "result": "Unreachable",
                    "error": str(exc)[:250],
                }

            st.session_state.checks.append(record)

            status_message.write(
                f"Checked {index}/{len(urls)}: {url}"
            )
            progress.progress(index / len(urls))

        status_message.success("Website checks completed!")

if not st.session_state.checks:
    st.info(
        "Click 'Check websites now' to run your first website checks."
    )
    st.caption(
        "Checks run from your computer. Results depend on your "
        "internet connection and the websites being tested."
    )

else:
    df = pd.DataFrame(st.session_state.checks)

    # Parse ISO timestamps safely, including timezone information.
    df["checked_at"] = pd.to_datetime(
        df["checked_at"], format="mixed", errors="coerce", utc=True
    )

    # Remove any records with invalid timestamps.
    df = df.dropna(subset=["checked_at"])

    if df.empty:
        st.warning("No valid monitoring records. Please check again.")
    else:
        total_checks = len(df)
        successful_checks = int(df["success"].sum())
        success_rate = successful_checks / total_checks * 100

        average_latency = df.loc[
            df["success"], "response_time_ms"
        ].mean()

        latest = (
            df.sort_values("checked_at")
            .groupby("website", as_index=False)
            .tail(1)
        )

        online_now = int(latest["success"].sum())

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Websites checked",
            latest["website"].nunique(),
        )

        col2.metric(
            "Currently online",
            f"{online_now}/{len(latest)}",
        )

        col3.metric(
            "Session success rate",
            f"{success_rate:.1f}%",
        )

        col4.metric(
            "Average response time",
            f"{average_latency:.0f} ms"
            if pd.notna(average_latency)
            else "N/A",
        )

        st.subheader("Latest Website Status")

        latest_display = latest[
            [
                "website",
                "result",
                "status_code",
                "response_time_ms",
                "checked_at",
                "error",
            ]
        ].sort_values("website")

        st.dataframe(
            latest_display,
            use_container_width=True,
            hide_index=True,
        )

        successful_df = df[df["success"]].copy()

        if not successful_df.empty:
            st.subheader("Response Time by Website")

            latency_chart = px.bar(
                successful_df,
                x="website",
                y="response_time_ms",
                color="website",
                hover_data=["checked_at", "status_code"],
                labels={
                    "website": "Website",
                    "response_time_ms": "Response Time (ms)",
                },
                title="Response Time for Successful Checks",
            )

            st.plotly_chart(
                latency_chart,
                use_container_width=True,
            )

        st.subheader("Response Time History")

        history_chart = px.line(
            df.sort_values("checked_at"),
            x="checked_at",
            y="response_time_ms",
            color="website",
            markers=True,
            hover_data=["status_code", "result"],
            labels={
                "checked_at": "Check Time",
                "response_time_ms": "Response Time (ms)",
                "website": "Website",
            },
        )

        st.plotly_chart(
            history_chart,
            use_container_width=True,
        )

        st.subheader("All Recorded Checks")

        st.dataframe(
            df.sort_values("checked_at", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        csv_data = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download Monitoring History as CSV",
            data=csv_data,
            file_name="website_monitor_history.csv",
            mime="text/csv",
        )

st.caption(
    "Phase 1: Checks run on a single computer. History is kept "
    "in memory during the session and is not permanently stored. "
    "Global monitoring requires additional monitoring locations."
)
