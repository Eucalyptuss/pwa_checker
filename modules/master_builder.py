from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List

import pandas as pd

from .normalizer import display_value, fmt_date, is_blank, normalize_whitespace

MASTER_SHEET_ORDER = [
    "Instructions",
    "Company",
    "Worker",
    "Task",
    "SOP",
    "Site",
    "Worker_By_Company",
]


def _safe_sheet_name(name: str) -> str:
    bad = ["\\", "/", "*", "?", ":", "[", "]"]
    for ch in bad:
        name = name.replace(ch, "_")
    return name[:31]


def _safe_join(values: Any, limit: int = 80) -> str:
    """Return stable comma-separated text for audit columns."""
    if values is None:
        return ""
    if isinstance(values, pd.Series):
        raw = values.tolist()
    elif isinstance(values, (list, tuple, set)):
        raw = list(values)
    else:
        raw = [values]
    cleaned = sorted(set(normalize_whitespace(v) for v in raw if not is_blank(v)))
    if len(cleaned) > limit:
        return ", ".join(cleaned[:limit]) + f", ... (+{len(cleaned) - limit} more)"
    return ", ".join(cleaned)


def _source_rows(series: pd.Series, limit: int = 120) -> str:
    vals: List[str] = []
    for value in series.dropna().tolist():
        text = normalize_whitespace(value)
        if text:
            vals.append(text)
    unique = sorted(set(vals), key=lambda x: (len(x), x))
    if len(unique) > limit:
        return ", ".join(unique[:limit]) + f", ... (+{len(unique) - limit} more)"
    return ", ".join(unique)


def _date_min(series: pd.Series) -> str:
    dates = pd.to_datetime(series, errors="coerce").dropna()
    return fmt_date(dates.min()) if not dates.empty else ""


def _date_max(series: pd.Series) -> str:
    dates = pd.to_datetime(series, errors="coerce").dropna()
    return fmt_date(dates.max()) if not dates.empty else ""


def _empty_master_tables() -> Dict[str, pd.DataFrame]:
    return {
        "Instructions": pd.DataFrame([
            {
                "Item": "Purpose",
                "Description": "This workbook is a generated reference master file for PWA checker typo/similarity validation.",
            },
            {
                "Item": "How to use",
                "Description": "Review the values, correct canonical names in the first column of each master sheet, then upload this file as the Optional Reference Master Excel file.",
            },
            {
                "Item": "Important",
                "Description": "The app reads the first recognized master column from Company, Worker, Task, SOP, and Site sheets. Review columns are for audit/support only.",
            },
        ]),
        "Company": pd.DataFrame(columns=["Company", "Company Normalized", "Review Status", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]),
        "Worker": pd.DataFrame(columns=["Worker", "Worker Normalized", "Review Status", "Companies", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]),
        "Task": pd.DataFrame(columns=["Task", "Task Normalized", "Review Status", "SOPs Observed", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]),
        "SOP": pd.DataFrame(columns=["SOP", "SOP Normalized", "Review Status", "Tasks Observed", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]),
        "Site": pd.DataFrame(columns=["Site", "Review Status", "Companies", "Workers", "Occurrence Count", "Total Hours", "First Date", "Last Date", "Notes"]),
        "Worker_By_Company": pd.DataFrame(columns=["Company", "Company Normalized", "Worker", "Worker Normalized", "Review Status", "Source Sites", "Source Rows", "Occurrence Count", "Total Hours", "First Date", "Last Date", "Notes"]),
    }


def build_master_tables(normalized: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Build master tables from normalized PWA data.

    The first column of Company/Worker/Task/SOP/Site is intentionally the canonical
    master value because ``load_master_file`` uses it directly during later uploads.
    """
    if normalized is None or normalized.empty:
        return _empty_master_tables()

    df = normalized.copy()
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    if "Hours" in df.columns:
        df["Hours"] = pd.to_numeric(df["Hours"], errors="coerce")
    source_row_text = (
        df.get("Source Sheet", pd.Series([""] * len(df), index=df.index)).map(normalize_whitespace)
        + "!"
        + df.get("Source Row", pd.Series([""] * len(df), index=df.index)).map(normalize_whitespace)
    )
    df["__SourceRef__"] = source_row_text.str.strip("!")

    tables = _empty_master_tables()

    valid_company = df[df.get("Company Normalized", pd.Series(dtype=str)).fillna("").astype(str).ne("")].copy()
    if not valid_company.empty:
        company = (
            valid_company.groupby("Company Normalized", dropna=False)
            .agg(
                Company=("Company Original", display_value),
                Source_Sites=("Site", _safe_join),
                Source_Rows=("__SourceRef__", _source_rows),
                Occurrence_Count=("Company Original", "size"),
                First_Date=("Date", _date_min),
                Last_Date=("Date", _date_max),
            )
            .reset_index()
            .rename(columns={
                "Company Normalized": "Company Normalized",
                "Source_Sites": "Source Sites",
                "Source_Rows": "Source Rows",
                "Occurrence_Count": "Occurrence Count",
                "First_Date": "First Date",
                "Last_Date": "Last Date",
            })
        )
        company.insert(2, "Review Status", "Review")
        company["Notes"] = ""
        tables["Company"] = company[["Company", "Company Normalized", "Review Status", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]].sort_values("Company").reset_index(drop=True)

    valid_worker = df[df.get("Worker Normalized", pd.Series(dtype=str)).fillna("").astype(str).ne("")].copy()
    if not valid_worker.empty:
        worker = (
            valid_worker.groupby("Worker Normalized", dropna=False)
            .agg(
                Worker=("Worker Original", display_value),
                Companies=("Company Original", _safe_join),
                Source_Sites=("Site", _safe_join),
                Source_Rows=("__SourceRef__", _source_rows),
                Occurrence_Count=("Worker Original", "size"),
                First_Date=("Date", _date_min),
                Last_Date=("Date", _date_max),
            )
            .reset_index()
            .rename(columns={
                "Worker Normalized": "Worker Normalized",
                "Source_Sites": "Source Sites",
                "Source_Rows": "Source Rows",
                "Occurrence_Count": "Occurrence Count",
                "First_Date": "First Date",
                "Last_Date": "Last Date",
            })
        )
        worker.insert(2, "Review Status", "Review")
        worker["Notes"] = ""
        tables["Worker"] = worker[["Worker", "Worker Normalized", "Review Status", "Companies", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]].sort_values(["Worker", "Companies"]).reset_index(drop=True)

    valid_task = df[df.get("Task Normalized", pd.Series(dtype=str)).fillna("").astype(str).ne("")].copy()
    if not valid_task.empty:
        task = (
            valid_task.groupby("Task Normalized", dropna=False)
            .agg(
                Task=("Task Original", display_value),
                SOPs_Observed=("SOP Original", _safe_join),
                Source_Sites=("Site", _safe_join),
                Source_Rows=("__SourceRef__", _source_rows),
                Occurrence_Count=("Task Original", "size"),
                First_Date=("Date", _date_min),
                Last_Date=("Date", _date_max),
            )
            .reset_index()
            .rename(columns={
                "Task Normalized": "Task Normalized",
                "SOPs_Observed": "SOPs Observed",
                "Source_Sites": "Source Sites",
                "Source_Rows": "Source Rows",
                "Occurrence_Count": "Occurrence Count",
                "First_Date": "First Date",
                "Last_Date": "Last Date",
            })
        )
        task.insert(2, "Review Status", "Review")
        task["Notes"] = ""
        tables["Task"] = task[["Task", "Task Normalized", "Review Status", "SOPs Observed", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]].sort_values("Task").reset_index(drop=True)

    valid_sop = df[df.get("SOP Normalized", pd.Series(dtype=str)).fillna("").astype(str).ne("")].copy()
    if not valid_sop.empty:
        sop = (
            valid_sop.groupby("SOP Normalized", dropna=False)
            .agg(
                SOP=("SOP Original", display_value),
                Tasks_Observed=("Task Original", _safe_join),
                Source_Sites=("Site", _safe_join),
                Source_Rows=("__SourceRef__", _source_rows),
                Occurrence_Count=("SOP Original", "size"),
                First_Date=("Date", _date_min),
                Last_Date=("Date", _date_max),
            )
            .reset_index()
            .rename(columns={
                "SOP Normalized": "SOP Normalized",
                "Tasks_Observed": "Tasks Observed",
                "Source_Sites": "Source Sites",
                "Source_Rows": "Source Rows",
                "Occurrence_Count": "Occurrence Count",
                "First_Date": "First Date",
                "Last_Date": "Last Date",
            })
        )
        sop.insert(2, "Review Status", "Review")
        sop["Notes"] = ""
        tables["SOP"] = sop[["SOP", "SOP Normalized", "Review Status", "Tasks Observed", "Source Sites", "Source Rows", "Occurrence Count", "First Date", "Last Date", "Notes"]].sort_values("SOP").reset_index(drop=True)

    valid_site = df[df.get("Site", pd.Series(dtype=str)).fillna("").astype(str).ne("")].copy()
    if not valid_site.empty:
        site = (
            valid_site.groupby("Site", dropna=False)
            .agg(
                Companies=("Company Original", _safe_join),
                Workers=("Worker Original", _safe_join),
                Occurrence_Count=("Site", "size"),
                Total_Hours=("Hours", "sum"),
                First_Date=("Date", _date_min),
                Last_Date=("Date", _date_max),
            )
            .reset_index()
            .rename(columns={
                "Occurrence_Count": "Occurrence Count",
                "Total_Hours": "Total Hours",
                "First_Date": "First Date",
                "Last_Date": "Last Date",
            })
        )
        site.insert(1, "Review Status", "Review")
        site["Total Hours"] = pd.to_numeric(site["Total Hours"], errors="coerce").fillna(0).round(2)
        site["Notes"] = ""
        tables["Site"] = site[["Site", "Review Status", "Companies", "Workers", "Occurrence Count", "Total Hours", "First Date", "Last Date", "Notes"]].sort_values("Site").reset_index(drop=True)

    valid_pair = df[
        df.get("Company Normalized", pd.Series(dtype=str)).fillna("").astype(str).ne("")
        & df.get("Worker Normalized", pd.Series(dtype=str)).fillna("").astype(str).ne("")
    ].copy()
    if not valid_pair.empty:
        pair = (
            valid_pair.groupby(["Company Normalized", "Worker Normalized"], dropna=False)
            .agg(
                Company=("Company Original", display_value),
                Worker=("Worker Original", display_value),
                Source_Sites=("Site", _safe_join),
                Source_Rows=("__SourceRef__", _source_rows),
                Occurrence_Count=("Worker Original", "size"),
                Total_Hours=("Hours", "sum"),
                First_Date=("Date", _date_min),
                Last_Date=("Date", _date_max),
            )
            .reset_index()
            .rename(columns={
                "Source_Sites": "Source Sites",
                "Source_Rows": "Source Rows",
                "Occurrence_Count": "Occurrence Count",
                "Total_Hours": "Total Hours",
                "First_Date": "First Date",
                "Last_Date": "Last Date",
            })
        )
        pair.insert(4, "Review Status", "Review")
        pair["Total Hours"] = pd.to_numeric(pair["Total Hours"], errors="coerce").fillna(0).round(2)
        pair["Notes"] = ""
        tables["Worker_By_Company"] = pair[["Company", "Company Normalized", "Worker", "Worker Normalized", "Review Status", "Source Sites", "Source Rows", "Occurrence Count", "Total Hours", "First Date", "Last Date", "Notes"]].sort_values(["Company", "Worker"]).reset_index(drop=True)

    return tables


def _format_master_sheet(writer: pd.ExcelWriter, sheet_name: str, df: pd.DataFrame) -> None:
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
    body_fmt = workbook.add_format({"border": 1, "valign": "top"})
    review_fmt = workbook.add_format({"border": 1, "valign": "top", "bg_color": "#FEF3C7", "font_color": "#713F12"})
    number_fmt = workbook.add_format({"border": 1, "num_format": "0.00", "valign": "top"})
    int_fmt = workbook.add_format({"border": 1, "num_format": "0", "valign": "top"})
    wrap_fmt = workbook.add_format({"border": 1, "valign": "top", "text_wrap": True})

    if df is None:
        df = pd.DataFrame()
    for col_idx, col in enumerate(df.columns):
        worksheet.write(0, col_idx, col, header_fmt)
        values = [] if df.empty else ["" if pd.isna(v) else str(v) for v in df[col].head(300).tolist()]
        max_len = max([len(str(col))] + [len(v) for v in values]) if values else len(str(col))
        width = min(max(max_len + 2, 10), 55)
        if col in {"Source Rows", "Source Sites", "Companies", "Workers", "SOPs Observed", "Tasks Observed", "Description"}:
            worksheet.set_column(col_idx, col_idx, min(max(width, 24), 60), wrap_fmt)
        elif col in {"Occurrence Count"}:
            worksheet.set_column(col_idx, col_idx, 16, int_fmt)
        elif col in {"Total Hours"}:
            worksheet.set_column(col_idx, col_idx, 14, number_fmt)
        elif col == "Review Status":
            worksheet.set_column(col_idx, col_idx, 16, review_fmt)
        else:
            worksheet.set_column(col_idx, col_idx, width, body_fmt)
    worksheet.freeze_panes(1, 0)
    if len(df.columns) > 0:
        worksheet.autofilter(0, 0, max(len(df), 1), len(df.columns) - 1)
    if "Review Status" in df.columns and len(df) > 0:
        status_col = list(df.columns).index("Review Status")
        worksheet.data_validation(1, status_col, max(len(df), 1), status_col, {
            "validate": "list",
            "source": ["Review", "Approved", "Do Not Use"],
        })


def build_master_file(normalized: pd.DataFrame) -> bytes:
    """Build downloadable Reference Master workbook bytes from normalized PWA data."""
    tables = build_master_tables(normalized)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="yyyy-mm-dd", date_format="yyyy-mm-dd") as writer:
        for name in MASTER_SHEET_ORDER:
            df = tables.get(name, pd.DataFrame()).copy()
            sheet_name = _safe_sheet_name(name)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            _format_master_sheet(writer, sheet_name, df)
    output.seek(0)
    return output.getvalue()
