from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from rapidfuzz import fuzz, process

from .normalizer import (
    compact_alnum,
    display_value,
    is_blank,
    normalize_company,
    normalize_general,
    normalize_sop,
    normalize_whitespace,
    normalize_work,
    normalize_worker,
)


def _status_first(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Status" not in df.columns:
        return df
    return df.loc[:, ["Status"] + [c for c in df.columns if c != "Status"]]


def _unique_values(df: pd.DataFrame, value_col: str, key_cols: Optional[List[str]] = None) -> pd.DataFrame:
    if df.empty or value_col not in df.columns:
        return pd.DataFrame()
    key_cols = key_cols or []
    cols = key_cols + [value_col]
    temp = df[cols + ["Site", "Source Row"]].copy()
    temp[value_col] = temp[value_col].map(normalize_whitespace)
    temp = temp[temp[value_col].ne("")]
    return temp.drop_duplicates().reset_index(drop=True)


def _score(a: str, b: str, mode: str = "token") -> int:
    if mode == "simple":
        return int(fuzz.ratio(a, b))
    if mode == "partial":
        return int(fuzz.partial_ratio(a, b))
    return int(fuzz.token_sort_ratio(a, b))


def _variant_group_warnings(
    df: pd.DataFrame,
    value_col: str,
    norm_func,
    warning_type: str,
    context_cols: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    context_cols = context_cols or []
    temp = df[[value_col, "Site", "Source Row"] + [c for c in context_cols if c in df.columns]].copy()
    temp[value_col] = temp[value_col].map(normalize_whitespace)
    temp = temp[temp[value_col].ne("")]
    if temp.empty:
        return []
    temp["__key__"] = temp[value_col].map(norm_func)
    rows: List[Dict[str, Any]] = []
    for key, group in temp.groupby("__key__"):
        originals = sorted(set(group[value_col].tolist()))
        if key and len(originals) > 1:
            suggested = originals[0]
            for original in originals[1:]:
                rows.append({
                    "Type": warning_type,
                    "Original Value": original,
                    "Suggested Value": suggested,
                    "Similarity Score": 100,
                    "Site": ", ".join(sorted(set(group["Site"].astype(str).tolist()))),
                    "Company": display_value(group["Company Original"]) if "Company Original" in group.columns else "",
                    "Worker A": "",
                    "Worker B": "",
                    "Row": ", ".join(map(str, sorted(set(group["Source Row"].astype(str).tolist())))),
                    "Recommendation": "Same normalized key but different original spelling. Manual review before correction.",
                    "Status": "Warning",
                })
    return rows


def _pairwise_similarity_warnings(
    values: List[str], warning_type: str, threshold: int, mode: str = "token") -> List[Tuple[str, str, int]]:
    warnings: List[Tuple[str, str, int]] = []
    clean = sorted(set([normalize_whitespace(v) for v in values if normalize_whitespace(v)]))
    if len(clean) > 400:
        # Pairwise comparison is O(n^2). Cap to prevent UI lockups in very large files.
        clean = clean[:400]
    for a, b in combinations(clean, 2):
        if compact_alnum(a) == compact_alnum(b):
            score = 100
        else:
            score = _score(a, b, mode=mode)
        if threshold <= score < 100 or (score == 100 and a != b):
            warnings.append((a, b, score))
    return warnings


def check_company_similarity(df: pd.DataFrame, master_values: Optional[List[str]] = None, threshold: int = 86) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    rows.extend(_variant_group_warnings(df, "Company Original", normalize_company, "Company Name Similarity Warning"))
    values = sorted(set(df.get("Company Original", pd.Series(dtype=str)).dropna().map(normalize_whitespace).tolist()))
    if master_values:
        choices = [normalize_whitespace(v) for v in master_values if normalize_whitespace(v)]
        for value in values:
            match = process.extractOne(value, choices, scorer=fuzz.token_sort_ratio)
            if match and threshold <= int(match[1]) < 100 and normalize_company(value) != normalize_company(match[0]):
                rows.append({
                    "Type": "Company Master Similarity Warning",
                    "Original Value": value,
                    "Suggested Value": match[0],
                    "Similarity Score": int(match[1]),
                    "Site": "",
                    "Company": value,
                    "Worker A": "",
                    "Worker B": "",
                    "Row": "",
                    "Recommendation": "Compare against Company Master. Do not auto-correct without review.",
                    "Status": "Warning",
                })
    else:
        for a, b, score in _pairwise_similarity_warnings(values, "Company Name Similarity Warning", threshold):
            if normalize_company(a) != normalize_company(b):
                rows.append({
                    "Type": "Company Name Similarity Warning",
                    "Original Value": a,
                    "Suggested Value": b,
                    "Similarity Score": score,
                    "Site": "",
                    "Company": a,
                    "Worker A": "",
                    "Worker B": "",
                    "Row": "",
                    "Recommendation": "Potential company spelling variant. Manual review required.",
                    "Status": "Warning",
                })
    return _status_first(pd.DataFrame(rows))


def check_worker_similarity(df: pd.DataFrame, master_values: Optional[List[str]] = None, threshold: int = 88) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    rows.extend(_variant_group_warnings(df, "Worker Original", normalize_worker, "Worker Name Similarity Warning", context_cols=["Company Original"]))
    valid = df[df["Worker Original"].fillna("").astype(str).ne("")].copy() if not df.empty else pd.DataFrame()
    if valid.empty:
        return _status_first(pd.DataFrame(rows))
    if master_values:
        choices = [normalize_whitespace(v) for v in master_values if normalize_whitespace(v)]
        for _, group in valid.groupby(["Site", "Company Normalized"], dropna=False):
            company = display_value(group["Company Original"])
            for value in sorted(set(group["Worker Original"].map(normalize_whitespace).tolist())):
                match = process.extractOne(value, choices, scorer=fuzz.token_sort_ratio)
                if match and threshold <= int(match[1]) < 100 and normalize_worker(value) != normalize_worker(match[0]):
                    rows.append({
                        "Type": "Worker Master Similarity Warning",
                        "Original Value": value,
                        "Suggested Value": match[0],
                        "Similarity Score": int(match[1]),
                        "Site": display_value(group["Site"]),
                        "Company": company,
                        "Worker A": value,
                        "Worker B": match[0],
                        "Row": "",
                        "Recommendation": "Possible worker name typo. Do not merge automatically.",
                        "Status": "Warning",
                    })
    else:
        for (site, company_key), group in valid.groupby(["Site", "Company Normalized"], dropna=False):
            company = display_value(group["Company Original"])
            values = sorted(set(group["Worker Original"].map(normalize_whitespace).tolist()))
            for a, b, score in _pairwise_similarity_warnings(values, "Worker Name Similarity Warning", threshold):
                if normalize_worker(a) != normalize_worker(b):
                    rows.append({
                        "Type": "Worker Name Similarity Warning",
                        "Original Value": a,
                        "Suggested Value": b,
                        "Similarity Score": score,
                        "Site": site,
                        "Company": company,
                        "Worker A": a,
                        "Worker B": b,
                        "Row": "",
                        "Recommendation": "Possible same person. Manual review required. Do not auto-merge.",
                        "Status": "Warning",
                    })
    return _status_first(pd.DataFrame(rows))


def check_work_similarity(df: pd.DataFrame, master_values: Optional[List[str]] = None, threshold: int = 85) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    rows.extend(_variant_group_warnings(df, "Task Original", normalize_work, "Task Similarity Warning"))
    values = sorted(set(df.get("Task Original", pd.Series(dtype=str)).dropna().map(normalize_whitespace).tolist()))
    if master_values:
        choices = [normalize_whitespace(v) for v in master_values if normalize_whitespace(v)]
        for value in values:
            match = process.extractOne(value, choices, scorer=fuzz.token_sort_ratio)
            if match and threshold <= int(match[1]) < 100 and normalize_work(value) != normalize_work(match[0]):
                rows.append({
                    "Type": "Task Master Similarity Warning",
                    "Original Value": value,
                    "Suggested Value": match[0],
                    "Similarity Score": int(match[1]),
                    "Site": "",
                    "Company": "",
                    "Worker A": "",
                    "Worker B": "",
                    "Row": "",
                    "Recommendation": "Compare against Task Master. Manual review required.",
                    "Status": "Warning",
                })
    else:
        for a, b, score in _pairwise_similarity_warnings(values, "Task Similarity Warning", threshold):
            if normalize_work(a) != normalize_work(b):
                rows.append({
                    "Type": "Task Similarity Warning",
                    "Original Value": a,
                    "Suggested Value": b,
                    "Similarity Score": score,
                    "Site": "",
                    "Company": "",
                    "Worker A": "",
                    "Worker B": "",
                    "Row": "",
                    "Recommendation": "Possible task spelling variant. Manual review required.",
                    "Status": "Warning",
                })
    return _status_first(pd.DataFrame(rows))


def check_sop_similarity(df: pd.DataFrame, master_values: Optional[List[str]] = None, threshold: int = 88) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    rows.extend(_variant_group_warnings(df, "SOP Original", normalize_sop, "SOP Similarity Warning"))
    values = sorted(set(df.get("SOP Original", pd.Series(dtype=str)).dropna().map(normalize_whitespace).tolist()))
    if master_values:
        choices = [normalize_whitespace(v) for v in master_values if normalize_whitespace(v)]
        for value in values:
            match = process.extractOne(value, choices, scorer=fuzz.ratio)
            if match and threshold <= int(match[1]) < 100 and normalize_sop(value) != normalize_sop(match[0]):
                rows.append({
                    "Type": "SOP Master Similarity Warning",
                    "Original Value": value,
                    "Suggested Value": match[0],
                    "Similarity Score": int(match[1]),
                    "Site": "",
                    "Company": "",
                    "Worker A": "",
                    "Worker B": "",
                    "Row": "",
                    "Recommendation": "SOP can differ by one character. Manual review required.",
                    "Status": "Warning",
                })
    else:
        for a, b, score in _pairwise_similarity_warnings(values, "SOP Similarity Warning", threshold, mode="simple"):
            if normalize_sop(a) != normalize_sop(b):
                rows.append({
                    "Type": "SOP Similarity Warning",
                    "Original Value": a,
                    "Suggested Value": b,
                    "Similarity Score": score,
                    "Site": "",
                    "Company": "",
                    "Worker A": "",
                    "Worker B": "",
                    "Row": "",
                    "Recommendation": "Possible SOP typo. Do not auto-correct.",
                    "Status": "Warning",
                })
    return _status_first(pd.DataFrame(rows))


def build_typo_warnings(
    df: pd.DataFrame,
    masters: Optional[Dict[str, List[str]]] = None,
    company_threshold: int = 86,
    worker_threshold: int = 88,
    work_threshold: int = 85,
    sop_threshold: int = 88,
) -> pd.DataFrame:
    masters = masters or {}
    if df is None or df.empty:
        return pd.DataFrame()
    parts = [
        check_company_similarity(df, masters.get("Company") or None, company_threshold),
        check_worker_similarity(df, masters.get("Worker") or None, worker_threshold),
        check_work_similarity(df, masters.get("Task") or None, work_threshold),
        check_sop_similarity(df, masters.get("SOP") or None, sop_threshold),
    ]
    parts = [p for p in parts if p is not None and not p.empty]
    if not parts:
        return pd.DataFrame(columns=["Status", "Type", "Original Value", "Suggested Value", "Similarity Score", "Site", "Company", "Worker A", "Worker B", "Row", "Recommendation"])
    out = pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)
    out = out.sort_values(["Type", "Similarity Score"], ascending=[True, False]).reset_index(drop=True)
    return _status_first(out)
