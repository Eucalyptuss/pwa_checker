from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from .config import STATUS_COLORS, STATUS_FONT_COLORS


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .pwa-kpi-card {
            border: 1px solid rgba(120, 120, 120, 0.25);
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 10px;
            background: rgba(125, 125, 125, 0.08);
            min-height: 105px;
        }
        .pwa-kpi-label {
            font-size: 0.86rem;
            opacity: 0.78;
            margin-bottom: 6px;
        }
        .pwa-kpi-value {
            font-size: 1.75rem;
            font-weight: 800;
            line-height: 1.2;
        }
        .small-note {
            color: rgba(120,120,120,0.95);
            font-size: 0.88rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: Any) -> None:
    st.markdown(
        f"""
        <div class="pwa-kpi-card">
            <div class="pwa-kpi-label">{label}</div>
            <div class="pwa-kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpis(summary: Dict[str, Any]) -> None:
    if not summary:
        st.info("No analysis results yet.")
        return
    labels = list(summary.keys())
    for i in range(0, len(labels), 4):
        cols = st.columns(4)
        for col, label in zip(cols, labels[i:i + 4]):
            with col:
                kpi_card(label, summary[label])


def status_first(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Status" not in df.columns:
        return df
    return df.loc[:, ["Status"] + [c for c in df.columns if c != "Status"]]


def style_status_dataframe(df: pd.DataFrame):
    df = status_first(df)
    if df is None or df.empty or "Status" not in df.columns:
        return df

    def _row_style(row):
        status = str(row.get("Status", ""))
        bg = STATUS_COLORS.get(status, "")
        fg = STATUS_FONT_COLORS.get(status, "")
        if not bg:
            return ["" for _ in row]
        return [f"background-color: {bg}; color: {fg};" if col == "Status" else "" for col in row.index]

    return df.style.apply(_row_style, axis=1)


def show_table(df: pd.DataFrame, title: str = "", height: int = 520) -> None:
    if title:
        st.subheader(title)
    if df is None or df.empty:
        st.info("No data to display.")
        return
    st.dataframe(style_status_dataframe(df), use_container_width=True, height=height)


def filter_dataframe(df: pd.DataFrame, key_prefix: str = "filter") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = status_first(df.copy())
    cols = st.columns(4)
    categorical = [c for c in ["Status", "Type", "Site", "Company", "Worker"] if c in out.columns]
    for idx, col_name in enumerate(categorical[:4]):
        options = sorted([str(v) for v in out[col_name].dropna().unique().tolist()])
        selected = cols[idx % 4].multiselect(col_name, options, key=f"{key_prefix}_{col_name}")
        if selected:
            out = out[out[col_name].astype(str).isin(selected)]
    if "Similarity Score" in out.columns:
        min_score = st.slider("Minimum Similarity Score", 0, 100, 0, key=f"{key_prefix}_score")
        out = out[pd.to_numeric(out["Similarity Score"], errors="coerce").fillna(0) >= min_score]
    return out
