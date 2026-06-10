from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .normalizer import display_value, fmt_date, is_blank

STATUS_SORT_RANK = {
    "Error": 0,
    "Violation": 1,
    "Manual Review Required": 2,
    "Roster Full": 3,
    "Warning": 4,
    "OK": 5,
    "Allowed": 5,
}


def status_first(df: pd.DataFrame) -> pd.DataFrame:
    """Move Status to the first column for screen/export readability."""
    if df is None or df.empty or "Status" not in df.columns:
        return df
    cols = ["Status"] + [c for c in df.columns if c != "Status"]
    return df.loc[:, cols]


def _sort_by_status(df: pd.DataFrame, extra_cols: List[str] | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    if "Status" in out.columns:
        out["__status_rank__"] = out["Status"].map(STATUS_SORT_RANK).fillna(99)
        sort_cols = ["__status_rank__"] + [c for c in (extra_cols or []) if c in out.columns]
        out = out.sort_values(sort_cols, na_position="last").drop(columns="__status_rank__")
    elif extra_cols:
        out = out.sort_values([c for c in extra_cols if c in out.columns], na_position="last")
    return out.reset_index(drop=True)


def _valid_work_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    required_cols = ["Company Normalized", "Worker Normalized", "Date", "Hours"]
    if not all(c in out.columns for c in required_cols):
        return pd.DataFrame()
    out = out[
        out["Company Normalized"].fillna("").astype(str).ne("")
        & out["Worker Normalized"].fillna("").astype(str).ne("")
        & out["Date"].notna()
        & out["Hours"].notna()
        & (out["Hours"] > 0)
        & (out["Hours"] <= 24)
    ].copy()
    return out


def _valid_roster_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows eligible for Site+Company roster-limit counting.

    Firmware-update related tasks and Commissioning/site-coordinator rows remain
    in normalized data and daily-hour checks, but are excluded from roster count.
    """
    valid = _valid_work_rows(df)
    if valid.empty:
        return valid
    if "Roster Count Eligible" not in valid.columns:
        return valid
    eligible = valid["Roster Count Eligible"].fillna(True).astype(bool)
    return valid[eligible].copy()


def build_roster_exclusions(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "Status", "Site", "Company", "Company Key", "Worker", "Worker Key", "Task",
        "Date", "Hours", "Roster Exclusion Reason", "Source Sheet", "Source Row"
    ]
    valid = _valid_work_rows(df)
    if valid.empty or "Roster Count Eligible" not in valid.columns:
        return pd.DataFrame(columns=cols)
    excluded = valid[~valid["Roster Count Eligible"].fillna(True).astype(bool)].copy()
    if excluded.empty:
        return pd.DataFrame(columns=cols)
    rows: List[Dict[str, Any]] = []
    for _, row in excluded.iterrows():
        rows.append({
            "Status": "Warning",
            "Site": row.get("Site", ""),
            "Company": row.get("Company Original", ""),
            "Company Key": row.get("Company Normalized", ""),
            "Worker": row.get("Worker Original", ""),
            "Worker Key": row.get("Worker Normalized", ""),
            "Task": row.get("Task Original", ""),
            "Date": fmt_date(row.get("Date")),
            "Hours": row.get("Hours", ""),
            "Roster Exclusion Reason": row.get("Roster Exclusion Reason", ""),
            "Source Sheet": row.get("Source Sheet", ""),
            "Source Row": row.get("Source Row", ""),
        })
    return status_first(_sort_by_status(pd.DataFrame(rows), ["Site", "Company", "Worker", "Date", "Source Row"]))


def _build_first_access(valid: pd.DataFrame) -> pd.DataFrame:
    return (
        valid.groupby(["Site", "Company Normalized", "Worker Normalized"], dropna=False)
        .agg(
            Company=("Company Original", display_value),
            Worker=("Worker Original", display_value),
            First_Access_Date=("Date", "min"),
            Source_Rows=("Source Row", lambda s: ", ".join(map(str, sorted(set(pd.to_numeric(s, errors="coerce").dropna().astype(int).tolist()))))),
        )
        .reset_index()
    )


def _violation_date_from_first_access(group: pd.DataFrame) -> Any:
    """Return the first date where cumulative worker count exceeds 3.

    Same-date first-access workers are evaluated as a date group.  This avoids
    arbitrarily selecting a single 4th person when the purpose is detecting the
    roster violation, not assigning violator priority.
    """
    cumulative = 0
    for date, date_group in group.sort_values("First_Access_Date").groupby("First_Access_Date", sort=True):
        cumulative += len(date_group)
        if cumulative > 3:
            return date
    return pd.NaT


def build_roster_check(df: pd.DataFrame) -> pd.DataFrame:
    valid = _valid_roster_rows(df)
    cols = ["Status", "Site", "Company", "Company Key", "Unique Worker Count", "Workers", "First Access Date", "Violation Date", "Review Note"]
    if valid.empty:
        return pd.DataFrame(columns=cols)

    first = _build_first_access(valid)
    rows: List[Dict[str, Any]] = []
    for (site, company_key), group in first.groupby(["Site", "Company Normalized"], dropna=False):
        group = group.sort_values(["First_Access_Date", "Worker Normalized"]).reset_index(drop=True)
        count = len(group)
        company_display = display_value(group["Company"])
        workers = ", ".join(group["Worker"].astype(str).tolist())
        status = "Violation" if count > 3 else "Roster Full" if count == 3 else "OK"
        violation_date = _violation_date_from_first_access(group) if count > 3 else pd.NaT
        note = ""
        if count > 3:
            same_date_count = int(group[group["First_Access_Date"].eq(violation_date)].shape[0]) if not pd.isna(violation_date) else 0
            note = (
                f"Cumulative Site+Company worker count exceeded the 3-person PWA limit on {fmt_date(violation_date)}. "
                f"{same_date_count} worker(s) first appeared on that date. Same-date workers are treated as a roster-limit violation event, not a priority/violator assignment."
            )
        rows.append({
            "Status": status,
            "Site": site,
            "Company": company_display,
            "Company Key": company_key,
            "Unique Worker Count": count,
            "Workers": workers,
            "First Access Date": fmt_date(group["First_Access_Date"].min()),
            "Violation Date": fmt_date(violation_date),
            "Review Note": note,
        })
    return status_first(_sort_by_status(pd.DataFrame(rows), ["Site", "Company"]))


def build_roster_sequence(df: pd.DataFrame) -> pd.DataFrame:
    valid = _valid_roster_rows(df)
    cols = [
        "Status", "Site", "Company", "Company Key", "Worker", "Worker Key", "First Access Date",
        "Roster Sequence", "Same-Date First Access Count", "Cumulative Count After Date", "Source Rows", "Review Note"
    ]
    if valid.empty:
        return pd.DataFrame(columns=cols)

    first = _build_first_access(valid)
    out_rows: List[Dict[str, Any]] = []
    for (site, company_key), group in first.groupby(["Site", "Company Normalized"], dropna=False):
        group = group.sort_values(["First_Access_Date", "Worker Normalized"]).reset_index(drop=True)
        cumulative_before = 0
        sequence_counter = 0
        for first_date, date_group in group.groupby("First_Access_Date", sort=True):
            date_group = date_group.sort_values("Worker Normalized")
            same_date_count = len(date_group)
            cumulative_after = cumulative_before + same_date_count
            if cumulative_after > 3:
                status = "Violation"
                note = (
                    "Cumulative worker count exceeded the 3-person PWA limit on this first access date. "
                    "All workers first appearing in this date group are marked as Violation because the check validates whether the roster limit was exceeded; it does not assign individual priority."
                )
            elif cumulative_after == 3:
                status = "Roster Full"
                note = "Roster reached the 3-person limit on this first access date. Additional workers are not allowed for this Site+Company."
            else:
                status = "OK"
                note = ""

            for _, row in date_group.iterrows():
                sequence_counter += 1
                out_rows.append({
                    "Status": status,
                    "Site": site,
                    "Company": row["Company"],
                    "Company Key": company_key,
                    "Worker": row["Worker"],
                    "Worker Key": row["Worker Normalized"],
                    "First Access Date": fmt_date(row["First_Access_Date"]),
                    "Roster Sequence": sequence_counter,
                    "Same-Date First Access Count": same_date_count,
                    "Cumulative Count After Date": cumulative_after,
                    "Source Rows": row["Source_Rows"],
                    "Review Note": note,
                })
            cumulative_before = cumulative_after
    return status_first(_sort_by_status(pd.DataFrame(out_rows), ["Site", "Company", "First Access Date", "Worker"]))


def build_daily_hours_check(df: pd.DataFrame) -> pd.DataFrame:
    valid = _valid_work_rows(df)
    cols = ["Status", "Date", "Company", "Company Key", "Worker", "Worker Key", "Sites", "Site Detail", "Total Hours"]
    if valid.empty:
        return pd.DataFrame(columns=cols)
    grouped_site = (
        valid.groupby(["Date", "Company Normalized", "Worker Normalized", "Site"], dropna=False)
        .agg(Hours=("Hours", "sum"), Company=("Company Original", display_value), Worker=("Worker Original", display_value))
        .reset_index()
    )
    rows: List[Dict[str, Any]] = []
    for (date, company_key, worker_key), group in grouped_site.groupby(["Date", "Company Normalized", "Worker Normalized"], dropna=False):
        total = float(group["Hours"].sum())
        if total > 8:
            status = "Violation"
        elif abs(total - 8) < 1e-9:
            status = "Warning"
        else:
            status = "OK"
        site_detail = ", ".join([f"{r.Site}: {float(r.Hours):g}h" for r in group.sort_values("Site").itertuples()])
        rows.append({
            "Status": status,
            "Date": fmt_date(date),
            "Company": display_value(group["Company"]),
            "Company Key": company_key,
            "Worker": display_value(group["Worker"]),
            "Worker Key": worker_key,
            "Sites": ", ".join(sorted(group["Site"].astype(str).unique().tolist())),
            "Site Detail": site_detail,
            "Total Hours": round(total, 2),
        })
    return status_first(_sort_by_status(pd.DataFrame(rows), ["Date", "Company", "Worker"]))


def build_violations(roster_check: pd.DataFrame, daily_hours: pd.DataFrame, roster_sequence: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    if roster_check is not None and not roster_check.empty and "Status" in roster_check.columns:
        for _, row in roster_check[roster_check["Status"].eq("Violation")].iterrows():
            rows.append({
                "Status": "Violation",
                "Violation Type": "PWA Roster Limit",
                "Site": row.get("Site", ""),
                "Date": row.get("Violation Date", ""),
                "Company": row.get("Company", ""),
                "Worker": "",
                "Details": f"Unique worker count is {row.get('Unique Worker Count')}. Limit is 3. Workers: {row.get('Workers')}. {row.get('Review Note', '')}",
            })
    if daily_hours is not None and not daily_hours.empty and "Status" in daily_hours.columns:
        for _, row in daily_hours[daily_hours["Status"].eq("Violation")].iterrows():
            rows.append({
                "Status": "Violation",
                "Violation Type": "Daily Hours Over 8",
                "Site": row.get("Sites", ""),
                "Date": row.get("Date", ""),
                "Company": row.get("Company", ""),
                "Worker": row.get("Worker", ""),
                "Details": f"Total hours: {row.get('Total Hours')}h. Detail: {row.get('Site Detail')}",
            })
    out = pd.DataFrame(rows)
    return status_first(_sort_by_status(out, ["Violation Type", "Site", "Date", "Company", "Worker"])) if not out.empty else pd.DataFrame(columns=["Status", "Violation Type", "Site", "Date", "Company", "Worker", "Details"])


def build_data_quality_issues(df: pd.DataFrame, loader_issues: pd.DataFrame) -> pd.DataFrame:
    parts: List[pd.DataFrame] = []
    if loader_issues is not None and not loader_issues.empty:
        parts.append(status_first(loader_issues.copy()))
    if df is None or df.empty:
        out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        return status_first(_sort_by_status(out, ["Sheet", "Excel Row"])) if not out.empty else out

    issues: List[Dict[str, Any]] = []
    valid_cols = ["Site", "Company Normalized", "Worker Normalized", "Task Normalized", "SOP Normalized", "Date Text", "Hours"]
    dup_mask = df.duplicated(valid_cols, keep=False) if all(c in df.columns for c in valid_cols) else pd.Series(False, index=df.index)
    for _, row in df[dup_mask].iterrows():
        issues.append({
            "Status": "Warning",
            "Issue Type": "Duplicate Possible Row",
            "Severity": "Warning",
            "Sheet": row.get("Source Sheet", ""),
            "Excel Row": row.get("Source Row", ""),
            "Column": "All",
            "Value": "",
            "Message": "Same Site, Company, Worker, Task, SOP, Date, and Hours exists more than once.",
        })

    if "Worker Normalized" in df.columns:
        worker_company = (
            df[df["Worker Normalized"].fillna("").astype(str).ne("")]
            .groupby("Worker Normalized")
            .agg(
                Worker=("Worker Original", display_value),
                Companies=("Company Original", lambda s: sorted(set([str(v) for v in s if not is_blank(v)]))),
                CompanyKeys=("Company Normalized", lambda s: sorted(set([str(v) for v in s if not is_blank(v)]))),
            )
            .reset_index()
        )
        for _, row in worker_company.iterrows():
            if len(row["CompanyKeys"]) > 1:
                issues.append({
                    "Status": "Warning",
                    "Issue Type": "Worker With Multiple Companies",
                    "Severity": "Warning",
                    "Sheet": "Multiple",
                    "Excel Row": "",
                    "Column": "Company/Worker",
                    "Value": row["Worker"],
                    "Message": f"Worker appears under multiple companies: {', '.join(row['Companies'])}",
                })

    part = pd.DataFrame(issues)
    if not part.empty:
        parts.append(part)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not out.empty:
        out = out.drop_duplicates().reset_index(drop=True)
        out = status_first(_sort_by_status(out, ["Sheet", "Excel Row", "Issue Type"]))
    return out


def summarize_results(
    normalized: pd.DataFrame,
    roster_check: pd.DataFrame,
    daily_hours: pd.DataFrame,
    typo_warnings: pd.DataFrame,
    data_quality: pd.DataFrame,
) -> Dict[str, Any]:
    if normalized is None or normalized.empty:
        return {
            "Total Sites": 0,
            "Total Companies": 0,
            "Total Workers": 0,
            "Total Hours": 0,
            "Roster Violations": 0,
            "Daily Hour Violations": 0,
            "Typo Warnings": 0,
            "Data Quality Issues": len(data_quality) if data_quality is not None else 0,
        }
    return {
        "Total Sites": int(normalized["Site"].nunique()) if "Site" in normalized.columns else 0,
        "Total Companies": int(normalized["Company Normalized"].replace("", pd.NA).dropna().nunique()) if "Company Normalized" in normalized.columns else 0,
        "Total Workers": int(normalized["Worker Normalized"].replace("", pd.NA).dropna().nunique()) if "Worker Normalized" in normalized.columns else 0,
        "Total Hours": round(float(normalized["Hours"].fillna(0).sum()), 2) if "Hours" in normalized.columns else 0,
        "Roster Violations": int(roster_check["Status"].eq("Violation").sum()) if roster_check is not None and not roster_check.empty and "Status" in roster_check.columns else 0,
        "Daily Hour Violations": int(daily_hours["Status"].eq("Violation").sum()) if daily_hours is not None and not daily_hours.empty and "Status" in daily_hours.columns else 0,
        "Typo Warnings": len(typo_warnings) if typo_warnings is not None else 0,
        "Data Quality Issues": len(data_quality) if data_quality is not None else 0,
    }
