from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from .config import COLUMN_CANDIDATES, EXCLUDE_SHEET_KEYWORDS, MASTER_TYPES
from .normalizer import (
    compact_alnum,
    display_value,
    fmt_date,
    is_blank,
    is_date_like_header,
    normalize_company,
    normalize_general,
    normalize_header,
    normalize_sop,
    normalize_whitespace,
    normalize_work,
    normalize_worker,
    parse_date,
    parse_hours,
    roster_exclusion_reason,
)


@dataclass
class SheetLoadResult:
    sheet_name: str
    raw: pd.DataFrame
    mapping: Dict[str, Any]
    normalized: pd.DataFrame
    issues: pd.DataFrame


def should_exclude_sheet(sheet_name: str) -> bool:
    normalized = normalize_header(sheet_name).upper().replace(" ", "")
    return any(keyword in normalized for keyword in EXCLUDE_SHEET_KEYWORDS)


def list_excel_sheets(file_obj: Any) -> List[str]:
    file_obj.seek(0)
    xls = pd.ExcelFile(file_obj, engine="openpyxl")
    return list(xls.sheet_names)


def _candidate_match(column: Any, candidates: Iterable[str]) -> int:
    header = normalize_header(column)
    compact_header = header.replace(" ", "")
    best = 0
    for cand in candidates:
        c = normalize_header(cand)
        compact_c = c.replace(" ", "")
        if header == c:
            best = max(best, 100)
        elif compact_header == compact_c:
            best = max(best, 95)
        elif c in header or header in c:
            best = max(best, 80)
    return best


def auto_detect_mapping(df: pd.DataFrame) -> Dict[str, Any]:
    """Detect long/wide sheet structure and important columns."""
    mapping: Dict[str, Any] = {
        "company": None,
        "worker": None,
        "work": None,
        "sop": None,
        "date": None,
        "hours": None,
        "date_columns": [],
        "format": "unknown",
    }
    columns = list(df.columns)
    used: set[str] = set()
    for field, candidates in COLUMN_CANDIDATES.items():
        scores: List[Tuple[int, Any]] = []
        for col in columns:
            score = _candidate_match(col, candidates)
            if score:
                scores.append((score, col))
        if scores:
            scores.sort(key=lambda x: (-x[0], str(x[1])))
            mapping[field] = scores[0][1]
            used.add(str(scores[0][1]))

    # Detect wide date columns. Exclude detected semantic columns.
    semantic_cols = {mapping.get(k) for k in ["company", "worker", "work", "sop", "date", "hours"] if mapping.get(k) is not None}
    date_cols = [c for c in columns if c not in semantic_cols and is_date_like_header(c)]
    mapping["date_columns"] = date_cols

    if mapping.get("date") is not None and mapping.get("hours") is not None:
        mapping["format"] = "long"
    elif date_cols:
        mapping["format"] = "wide"
    return mapping




def _resolve_column(df: pd.DataFrame, col: Any) -> Any:
    """Map UI string selections back to the original DataFrame column object."""
    if col is None or col == "":
        return None
    if col in df.columns:
        return col
    for actual in df.columns:
        if str(actual) == str(col):
            return actual
    return col


def _resolve_columns(df: pd.DataFrame, cols: Iterable[Any]) -> List[Any]:
    resolved: List[Any] = []
    for col in cols or []:
        actual = _resolve_column(df, col)
        if actual in df.columns and actual not in resolved:
            resolved.append(actual)
    return resolved

def _make_unique_columns(headers: List[Any]) -> List[Any]:
    """Return unique DataFrame columns while preserving real date header objects.

    Excel workbooks used for PWA tracking often contain an empty first row/column and
    hundreds of date columns.  Pandas' default header=0 handling turns those into
    ``Unnamed`` columns, so the loader must infer the actual header row first.
    """
    out: List[Any] = []
    seen: Dict[str, int] = {}
    for idx, value in enumerate(headers, start=1):
        if is_blank(value):
            candidate: Any = f"Unnamed Column {idx}"
        else:
            candidate = normalize_whitespace(value) if isinstance(value, str) else value
        key = str(candidate)
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count:
            if isinstance(candidate, str):
                candidate = f"{candidate}.{count}"
            else:
                candidate = f"{candidate}.{count}"
        out.append(candidate)
    return out


def _row_header_score(values: List[Any]) -> float:
    """Score a row for likelihood of being the real table header."""
    nonblank = [v for v in values if not is_blank(v)]
    if not nonblank:
        return 0
    semantic_score = 0
    for value in nonblank:
        for candidates in COLUMN_CANDIDATES.values():
            if _candidate_match(value, candidates) >= 80:
                semantic_score += 1
                break
    date_score = sum(1 for v in nonblank if is_date_like_header(v))
    # Wide PWA sheets usually have 4 semantic columns + many daily date columns.
    return semantic_score * 25 + min(date_score, 40) * 2 + min(len(nonblank), 20) * 0.1


def _infer_header_row(raw: pd.DataFrame) -> Any:
    """Infer the original DataFrame index label of the real header row."""
    if raw.empty:
        return 0
    max_scan = min(len(raw), 50)
    scored: List[Tuple[float, int, Any]] = []
    for pos in range(max_scan):
        values = raw.iloc[pos].tolist()
        label = raw.index[pos]
        scored.append((_row_header_score(values), pos, label))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][2] if scored and scored[0][0] > 0 else raw.index[0]


def _drop_empty_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop columns that are both unnamed and completely empty."""
    keep_cols: List[Any] = []
    for col in df.columns:
        col_is_unnamed = str(col).startswith("Unnamed Column") or str(col).startswith("Unnamed:")
        if col_is_unnamed and not df[col].notna().any():
            continue
        keep_cols.append(col)
    return df.loc[:, keep_cols]


def _read_sheet(file_obj: Any, sheet_name: str) -> pd.DataFrame:
    """Read one worksheet with robust header-row inference.

    Supports actual field files where row 1 is blank, row 2 contains headers, and
    date columns start after Task/SOP/Company/Name.
    """
    file_obj.seek(0)
    try:
        raw = pd.read_excel(file_obj, sheet_name=sheet_name, engine="openpyxl", dtype=object, header=None)
    except Exception as exc:
        return pd.DataFrame({"__load_error__": [str(exc)]})
    if raw.empty or raw.dropna(how="all").empty:
        return pd.DataFrame()

    # Remove rows/cols that are physically empty at the file edges while keeping
    # original row indices for source Excel row traceability.
    raw = raw.dropna(how="all")
    raw = raw.loc[:, raw.notna().any(axis=0)]
    if raw.empty:
        return pd.DataFrame()

    header_idx = _infer_header_row(raw)
    headers = _make_unique_columns(raw.loc[header_idx].tolist())
    data = raw.loc[raw.index > header_idx].copy()
    data.columns = headers
    data = data.dropna(how="all")
    data = _drop_empty_columns(data)
    data.attrs["header_row_number"] = int(header_idx) + 1
    return data


def _excel_row_from_index(idx: Any) -> Any:
    try:
        return int(idx) + 1
    except Exception:
        return ""


def _concat_nonempty(parts: List[pd.DataFrame]) -> pd.DataFrame:
    valid = [p for p in parts if p is not None and not p.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()


def _issue(sheet: str, row: Any, issue_type: str, severity: str, message: str, column: str = "", value: Any = "") -> Dict[str, Any]:
    return {
        "Status": "Error" if severity == "Error" else "Warning",
        "Issue Type": issue_type,
        "Severity": severity,
        "Sheet": sheet,
        "Excel Row": row,
        "Column": column,
        "Value": "" if is_blank(value) else str(value),
        "Message": message,
    }


def _task_allows_missing_sop(task_value: Any) -> bool:
    """Return True when the task type can be performed without SOP.

    Business rule: Inspection and Trouble Shooting/Troubleshooting can be recorded
    without SOP. These rows should be warning/review items, not hard errors.
    """
    task = normalize_work(task_value)
    compact = compact_alnum(task)
    return "INSPECTION" in task or "TROUBLESHOOTING" in compact or "TROUBLESHOOTING" in task.replace(" ", "")


def convert_sheet_to_long(
    df: pd.DataFrame,
    sheet_name: str,
    mapping: Dict[str, Any],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Convert one site sheet to the internal normalized long format."""
    rows: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    if df.empty:
        issues.append(_issue(sheet_name, "", "Empty Sheet", "Warning", "Sheet is empty and was skipped."))
        return pd.DataFrame(), pd.DataFrame(issues)
    if "__load_error__" in df.columns:
        issues.append(_issue(sheet_name, "", "Sheet Load Error", "Error", str(df["__load_error__"].iloc[0])))
        return pd.DataFrame(), pd.DataFrame(issues)

    effective = auto_detect_mapping(df)
    effective.update({k: v for k, v in mapping.items() if v not in (None, "", [], {})})
    for field in ["company", "worker", "work", "sop", "date", "hours"]:
        effective[field] = _resolve_column(df, effective.get(field))
    effective["date_columns"] = _resolve_columns(df, effective.get("date_columns", []))

    for field in ["company", "worker", "work", "sop"]:
        if effective.get(field) is None:
            issues.append(_issue(sheet_name, "", "Missing Column", "Error", f"Could not detect required column: {field}"))

    fmt = effective.get("format")
    if fmt == "long" and effective.get("date") is not None and effective.get("hours") is not None:
        for idx, row in df.iterrows():
            excel_row = _excel_row_from_index(idx)
            record = _build_record_from_values(
                sheet_name=sheet_name,
                excel_row=excel_row,
                company=row.get(effective.get("company")) if effective.get("company") is not None else None,
                worker=row.get(effective.get("worker")) if effective.get("worker") is not None else None,
                work=row.get(effective.get("work")) if effective.get("work") is not None else None,
                sop=row.get(effective.get("sop")) if effective.get("sop") is not None else None,
                date=row.get(effective.get("date")),
                hours=row.get(effective.get("hours")),
                source_format="Long",
            )
            rows.append(record)
    else:
        date_cols = effective.get("date_columns") or []
        if not date_cols:
            issues.append(_issue(sheet_name, "", "Missing Date Columns", "Error", "Could not detect Date/Hours columns or wide-format date columns."))
        for idx, row in df.iterrows():
            excel_row = _excel_row_from_index(idx)
            for date_col in date_cols:
                raw_hours = row.get(date_col)
                # In wide format, blank/zero cells mean no work record. Invalid text must remain visible.
                parsed_hours, hour_issue = parse_hours(raw_hours)
                if parsed_hours is None and hour_issue is None:
                    continue
                if parsed_hours == 0 and hour_issue is None:
                    continue
                record = _build_record_from_values(
                    sheet_name=sheet_name,
                    excel_row=excel_row,
                    company=row.get(effective.get("company")) if effective.get("company") is not None else None,
                    worker=row.get(effective.get("worker")) if effective.get("worker") is not None else None,
                    work=row.get(effective.get("work")) if effective.get("work") is not None else None,
                    sop=row.get(effective.get("sop")) if effective.get("sop") is not None else None,
                    date=date_col,
                    hours=raw_hours,
                    source_format="Wide",
                )
                rows.append(record)

    out = pd.DataFrame(rows)
    if out.empty:
        return out, pd.DataFrame(issues)

    issues.extend(validate_row_level_quality(out))
    return out, pd.DataFrame(issues)


def _build_record_from_values(
    sheet_name: str,
    excel_row: int,
    company: Any,
    worker: Any,
    work: Any,
    sop: Any,
    date: Any,
    hours: Any,
    source_format: str,
) -> Dict[str, Any]:
    parsed_date, date_issue = parse_date(date)
    parsed_hours, hours_issue = parse_hours(hours)
    company_original = normalize_whitespace(company)
    worker_original = normalize_whitespace(worker)
    work_original = normalize_whitespace(work)
    sop_original = normalize_whitespace(sop)
    exclusion_reason = roster_exclusion_reason(work_original)
    return {
        "Site": sheet_name,
        "Company Original": company_original,
        "Company Normalized": normalize_company(company_original),
        "Worker Original": worker_original,
        "Worker Normalized": normalize_worker(worker_original),
        "Task Original": work_original,
        "Task Normalized": normalize_work(work_original),
        "Roster Count Eligible": not bool(exclusion_reason),
        "Roster Exclusion Reason": exclusion_reason,
        "SOP Original": sop_original,
        "SOP Normalized": normalize_sop(sop_original),
        "Date": parsed_date,
        "Date Text": fmt_date(parsed_date),
        "Hours": parsed_hours,
        "Raw Date": "" if is_blank(date) else str(date),
        "Raw Hours": "" if is_blank(hours) else str(hours),
        "Date Issue": date_issue,
        "Hours Issue": hours_issue,
        "Source Sheet": sheet_name,
        "Source Row": excel_row,
        "Source Format": source_format,
    }


def validate_row_level_quality(df: pd.DataFrame) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    required_map = {
        "Company": "Company Original",
        "Worker": "Worker Original",
        "Task": "Task Original",
        "SOP": "SOP Original",
        "Date": "Date Text",
        "Hours": "Hours",
    }
    for _, row in df.iterrows():
        sheet = row.get("Source Sheet", row.get("Site", ""))
        excel_row = row.get("Source Row", "")
        if is_blank(row.get("Site")):
            issues.append(_issue(sheet, excel_row, "Missing Required Value", "Error", "Site is missing.", "Site"))
        for label, col in required_map.items():
            if label == "Hours":
                # A blank Hours cell in long format is not a work record, but it is still useful to flag.
                if is_blank(row.get("Raw Hours")) and row.get("Source Format") == "Long":
                    issues.append(_issue(sheet, excel_row, "Missing Required Value", "Warning", "Hours is blank.", col))
                continue
            if is_blank(row.get(col)):
                if label == "SOP" and _task_allows_missing_sop(row.get("Task Original")):
                    issues.append(_issue(
                        sheet,
                        excel_row,
                        "Missing SOP Allowed for Task",
                        "Warning",
                        "SOP is blank, but Task includes Inspection or Trouble Shooting. This task may be performed without SOP; verify the exemption before submission.",
                        col,
                        row.get("Task Original"),
                    ))
                else:
                    issues.append(_issue(sheet, excel_row, "Missing Required Value", "Error", f"{label} is missing.", col))
        if row.get("Date Issue"):
            issues.append(_issue(sheet, excel_row, "Date Parse Error", "Error", str(row.get("Date Issue")), "Date", row.get("Raw Date")))
        if row.get("Hours Issue"):
            severity = "Error" if row.get("Hours Issue") in {"Negative Hours"} or str(row.get("Hours Issue")).startswith("Invalid") else "Warning"
            issues.append(_issue(sheet, excel_row, "Hours Quality Issue", severity, str(row.get("Hours Issue")), "Hours", row.get("Raw Hours")))
        if not is_blank(row.get("Raw Hours")) and is_blank(row.get("Worker Original")):
            issues.append(_issue(sheet, excel_row, "Worker Missing With Hours", "Error", "Hours exists but Worker is missing.", "Worker", row.get("Raw Hours")))
        if not is_blank(row.get("Raw Hours")) and is_blank(row.get("Date Text")):
            issues.append(_issue(sheet, excel_row, "Date Missing With Hours", "Error", "Hours exists but Date is missing or invalid.", "Date", row.get("Raw Hours")))
    return issues


def load_and_normalize_workbook(
    file_obj: Any,
    excluded_sheets: Optional[List[str]] = None,
    mapping_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load all selected site sheets and return normalized data, raw data, issues, and mapping summary."""
    excluded = set(excluded_sheets or [])
    mapping_overrides = mapping_overrides or {}
    sheets = list_excel_sheets(file_obj)
    normalized_parts: List[pd.DataFrame] = []
    issue_parts: List[pd.DataFrame] = []
    raw_parts: List[pd.DataFrame] = []
    mapping_rows: List[Dict[str, Any]] = []

    for sheet in sheets:
        if sheet in excluded:
            continue
        df = _read_sheet(file_obj, sheet)
        if df.empty:
            issue_parts.append(pd.DataFrame([_issue(sheet, "", "Empty Sheet", "Warning", "Sheet is empty and was skipped.")]))
            continue
        df_raw = df.copy()
        df_raw.insert(0, "Source Sheet", sheet)
        df_raw.insert(1, "Source Row", [_excel_row_from_index(i) for i in df_raw.index])
        raw_parts.append(df_raw)
        auto_mapping = auto_detect_mapping(df)
        override = mapping_overrides.get(sheet, {})
        effective_mapping = auto_mapping.copy()
        effective_mapping.update({k: v for k, v in override.items() if v not in (None, "", [], {})})
        for field in ["company", "worker", "work", "sop", "date", "hours"]:
            effective_mapping[field] = _resolve_column(df, effective_mapping.get(field))
        effective_mapping["date_columns"] = _resolve_columns(df, effective_mapping.get("date_columns", []))
        normalized, issues = convert_sheet_to_long(df, sheet, effective_mapping)
        normalized_parts.append(normalized)
        issue_parts.append(issues)
        mapping_rows.append({
            "Sheet": sheet,
            "Detected Format": effective_mapping.get("format", "unknown"),
            "Company Column": str(effective_mapping.get("company") or ""),
            "Worker Column": str(effective_mapping.get("worker") or ""),
            "Task Column": str(effective_mapping.get("work") or ""),
            "SOP Column": str(effective_mapping.get("sop") or ""),
            "Date Column": str(effective_mapping.get("date") or ""),
            "Hours Column": str(effective_mapping.get("hours") or ""),
            "Wide Date Columns": ", ".join([str(c) for c in effective_mapping.get("date_columns", [])]),
        })

    normalized_df = _concat_nonempty(normalized_parts)
    issues_df = _concat_nonempty(issue_parts)
    raw_df = _concat_nonempty(raw_parts)
    mapping_df = pd.DataFrame(mapping_rows)
    if not normalized_df.empty:
        normalized_df = normalized_df.sort_values(["Site", "Date", "Company Normalized", "Worker Normalized", "Source Row"], na_position="last").reset_index(drop=True)
    return normalized_df, raw_df, issues_df, mapping_df


def read_sheet_preview(file_obj: Any, sheet_name: str, nrows: int = 5) -> pd.DataFrame:
    try:
        df = _read_sheet(file_obj, sheet_name)
        return df.head(nrows).copy()
    except Exception as exc:
        return pd.DataFrame({"Load Error": [str(exc)]})


def load_master_file(file_obj: Any) -> Dict[str, List[str]]:
    """Load optional master values from an Excel file.

    The function accepts either dedicated sheets named Company/Worker/Task/SOP/Site or any sheet with
    recognizable columns. The first matching column values are used.
    """
    masters: Dict[str, List[str]] = {k: [] for k in MASTER_TYPES}
    if file_obj is None:
        return masters
    file_obj.seek(0)
    try:
        xls = pd.ExcelFile(file_obj, engine="openpyxl")
    except Exception:
        return masters
    for sheet in xls.sheet_names:
        sheet_key = normalize_header(sheet)
        compact_sheet_key = sheet_key.replace(" ", "").replace("_", "")
        if compact_sheet_key in {"instructions", "instruction", "readme", "help", "workerbycompany", "workercompany"}:
            continue
        try:
            df = pd.read_excel(file_obj, sheet_name=sheet, engine="openpyxl", dtype=object)
        except Exception:
            continue
        file_obj.seek(0)
        sheet_key = normalize_header(sheet)
        sheet_tokens = set(sheet_key.split())

        # If the sheet name clearly identifies a master type, use only that type.
        # This prevents false matches such as "work" inside "worker".
        named_type = None
        for master_type, candidates in MASTER_TYPES.items():
            candidate_keys = [normalize_header(c) for c in candidates]
            if any(c == sheet_key or c in sheet_tokens or f"{c} master" == sheet_key for c in candidate_keys):
                named_type = master_type
                break
        if named_type and not df.empty:
            values = df.iloc[:, 0].dropna().map(normalize_whitespace).tolist()
            masters[named_type].extend([v for v in values if v])
            continue

        # Otherwise, inspect columns and use the first recognizable column for each type.
        for master_type, candidates in MASTER_TYPES.items():
            for col in df.columns:
                if _candidate_match(col, candidates) >= 80:
                    values = df[col].dropna().map(normalize_whitespace).tolist()
                    masters[master_type].extend([v for v in values if v])
                    break
    return {k: sorted(set(v)) for k, v in masters.items()}
