from __future__ import annotations

from io import BytesIO
from typing import Any, Dict

import pandas as pd


SHEET_ORDER = [
    "Summary",
    "PWA_Roster_Check",
    "Roster_Sequence",
    "Roster_Exclusions",
    "Daily_Hours_Check",
    "Violations",
    "Typo_Warnings",
    "Data_Quality_Issues",
    "Normalized_Data",
    "Raw_Data",
    "Column_Mapping",
]


def _safe_sheet_name(name: str) -> str:
    bad = ["\\", "/", "*", "?", ":", "[", "]"]
    for ch in bad:
        name = name.replace(ch, "_")
    return name[:31]


def _status_first(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Status" not in df.columns:
        return df
    return df.loc[:, ["Status"] + [c for c in df.columns if c != "Status"]]


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_cell_text(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_cell_text(v)}" for k, v in value.items())
    return str(value)


def _coerce_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = _status_first(df.copy())
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.tz_localize(None)
        elif out[col].dtype == object:
            out[col] = out[col].map(_cell_text)
    return out


def _format_sheet(writer: pd.ExcelWriter, sheet_name: str, df: pd.DataFrame) -> None:
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]
    header_fmt = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#1F4E79",
        "border": 1,
        "align": "center",
        "valign": "vcenter",
    })
    text_fmt = workbook.add_format({"border": 1, "valign": "top"})
    date_fmt = workbook.add_format({"num_format": "yyyy-mm-dd", "border": 1})
    number_fmt = workbook.add_format({"num_format": "0.00", "border": 1})
    status_formats = {
        "OK": workbook.add_format({"bg_color": "#DCFCE7", "font_color": "#14532D", "bold": True, "border": 1}),
        "Warning": workbook.add_format({"bg_color": "#FEF3C7", "font_color": "#713F12", "bold": True, "border": 1}),
        "Roster Full": workbook.add_format({"bg_color": "#FFEDD5", "font_color": "#7C2D12", "bold": True, "border": 1}),
        "Violation": workbook.add_format({"bg_color": "#FECACA", "font_color": "#7F1D1D", "bold": True, "border": 1}),
        "Error": workbook.add_format({"bg_color": "#FCA5A5", "font_color": "#450A0A", "bold": True, "border": 1}),
        "Manual Review Required": workbook.add_format({"bg_color": "#EDE9FE", "font_color": "#3B0764", "bold": True, "border": 1}),
        "Allowed": workbook.add_format({"bg_color": "#DCFCE7", "font_color": "#14532D", "bold": True, "border": 1}),
    }

    if df is None:
        df = pd.DataFrame()
    df = _status_first(df)
    for col_idx, col in enumerate(df.columns):
        worksheet.write(0, col_idx, col, header_fmt)
        values = [_cell_text(v) for v in df[col].head(300).tolist()] if not df.empty else []
        max_len = max([len(str(col))] + [len(v) for v in values])
        width = min(max(max_len + 2, 10), 55)
        worksheet.set_column(col_idx, col_idx, width, text_fmt)
        if "Date" in str(col):
            worksheet.set_column(col_idx, col_idx, 14, date_fmt)
        if col in {"Hours", "Total Hours", "Unique Worker Count", "Similarity Score", "Roster Sequence", "Same-Date First Access Count", "Cumulative Count After Date"}:
            worksheet.set_column(col_idx, col_idx, 14, number_fmt)
    worksheet.freeze_panes(1, 0)
    if len(df.columns) > 0:
        worksheet.autofilter(0, 0, max(len(df), 1), len(df.columns) - 1)
    if "Status" in df.columns and not df.empty:
        status_col = list(df.columns).index("Status")
        for row_num, status in enumerate(df["Status"].map(_cell_text).tolist(), start=1):
            fmt = status_formats.get(status, text_fmt)
            worksheet.write(row_num, status_col, status, fmt)


def build_excel_report(results: Dict[str, Any]) -> bytes:
    """Create an audit-friendly Excel report from validation results."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="yyyy-mm-dd", date_format="yyyy-mm-dd") as writer:
        summary_dict = results.get("summary", {}) or {}
        summary_df = pd.DataFrame([{"Metric": k, "Value": v} for k, v in summary_dict.items()])
        data_map = {
            "Summary": summary_df,
            "PWA_Roster_Check": results.get("roster_check", pd.DataFrame()),
            "Roster_Sequence": results.get("roster_sequence", pd.DataFrame()),
            "Roster_Exclusions": results.get("roster_exclusions", pd.DataFrame()),
            "Daily_Hours_Check": results.get("daily_hours", pd.DataFrame()),
            "Violations": results.get("violations", pd.DataFrame()),
            "Typo_Warnings": results.get("typo_warnings", pd.DataFrame()),
            "Data_Quality_Issues": results.get("data_quality", pd.DataFrame()),
            "Normalized_Data": results.get("normalized", pd.DataFrame()),
            "Raw_Data": results.get("raw", pd.DataFrame()),
            "Column_Mapping": results.get("mapping", pd.DataFrame()),
        }
        for name in SHEET_ORDER:
            df = _coerce_export_frame(data_map.get(name, pd.DataFrame()))
            sheet_name = _safe_sheet_name(name)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            _format_sheet(writer, sheet_name, df)
    output.seek(0)
    return output.getvalue()
