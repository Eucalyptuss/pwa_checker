from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from modules.exporter import build_excel_report
from modules.master_builder import build_master_file, build_master_tables
from modules.loader import (
    auto_detect_mapping,
    list_excel_sheets,
    load_and_normalize_workbook,
    load_master_file,
    read_sheet_preview,
    should_exclude_sheet,
)
from modules.typo_checker import build_typo_warnings
from modules.ui_components import filter_dataframe, inject_css, render_kpis, show_table
from modules.validator import (
    build_daily_hours_check,
    build_data_quality_issues,
    build_roster_check,
    build_roster_exclusions,
    build_roster_sequence,
    build_violations,
    summarize_results,
)

st.set_page_config(page_title="PWA Task Compliance Checker", layout="wide")
inject_css()

APP_TITLE = "PWA Task / Time Compliance Checker"
ADMIN_PASSWORD = "1801"



def _init_state() -> None:
    defaults = {
        "results": None,
        "sheets": [],
        "excluded_sheets": [],
        "mapping_overrides": {},
        "admin_authenticated": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _select_or_none(label: str, options: List[Any], value: Any, key: str):
    display_options = ["<Auto/None>"] + [str(c) for c in options]
    default_str = str(value) if value is not None else "<Auto/None>"
    idx = display_options.index(default_str) if default_str in display_options else 0
    selected = st.selectbox(label, display_options, index=idx, key=key)
    return None if selected == "<Auto/None>" else selected




def _operator_access_box(context: str = "Master Builder") -> bool:
    """Render a lightweight operator password gate for master-file generation.

    This is a UI-level restriction for normal Streamlit use. For public deployments,
    replace ADMIN_PASSWORD with st.secrets["operator_password"].
    """
    if st.session_state.get("admin_authenticated"):
        return True

    with st.expander(f"Operator Access Required - {context}", expanded=True):
        st.caption("Master 생성 기능은 운영자 전용입니다. 비밀번호를 입력해야 사용할 수 있습니다.")
        password = st.text_input(
            "Operator password",
            type="password",
            key=f"operator_password_{context}",
            placeholder="Enter operator password",
        )
        if st.button("Unlock Operator Function", key=f"operator_unlock_{context}", use_container_width=True):
            if password == ADMIN_PASSWORD:
                st.session_state.admin_authenticated = True
                st.success("Operator access unlocked.")
                st.rerun()
            else:
                st.error("Incorrect operator password.")
    return False


def _operator_logout_button() -> None:
    if st.session_state.get("admin_authenticated"):
        with st.sidebar:
            st.success("Operator mode active")
            if st.button("Lock Operator Mode", use_container_width=True):
                st.session_state.admin_authenticated = False
                st.rerun()

def _mapping_ui(file_obj, selected_sheets: List[str]) -> Dict[str, Dict[str, Any]]:
    overrides: Dict[str, Dict[str, Any]] = {}
    if not selected_sheets:
        return overrides
    st.markdown("#### Column Detection / Manual Mapping")
    st.caption("자동 인식이 맞으면 그대로 두면 됩니다. 잘못 인식된 Sheet만 수동으로 수정하세요.")
    for sheet in selected_sheets:
        with st.expander(f"{sheet} mapping", expanded=False):
            preview = read_sheet_preview(file_obj, sheet, nrows=8)
            st.dataframe(preview, use_container_width=True, height=220)
            detected = auto_detect_mapping(preview)
            cols = list(preview.columns)
            c1, c2, c3 = st.columns(3)
            with c1:
                company = _select_or_none("Company", cols, detected.get("company"), f"map_{sheet}_company")
                worker = _select_or_none("Worker", cols, detected.get("worker"), f"map_{sheet}_worker")
            with c2:
                work = _select_or_none("Task", cols, detected.get("work"), f"map_{sheet}_work")
                sop = _select_or_none("SOP", cols, detected.get("sop"), f"map_{sheet}_sop")
            with c3:
                date = _select_or_none("Date(Long)", cols, detected.get("date"), f"map_{sheet}_date")
                hours = _select_or_none("Hours(Long)", cols, detected.get("hours"), f"map_{sheet}_hours")
            detected_date_cols = [str(c) for c in detected.get("date_columns", [])]
            date_columns = st.multiselect(
                "Date columns for Wide Format",
                [str(c) for c in cols],
                default=[c for c in detected_date_cols if c in [str(x) for x in cols]],
                key=f"map_{sheet}_date_cols",
            )
            forced_format = st.radio(
                "Input Format",
                ["auto", "long", "wide"],
                index=0,
                horizontal=True,
                key=f"map_{sheet}_format",
            )
            overrides[sheet] = {
                "company": company,
                "worker": worker,
                "work": work,
                "sop": sop,
                "date": date,
                "hours": hours,
                "date_columns": date_columns,
                "format": forced_format if forced_format != "auto" else detected.get("format", "unknown"),
            }
    return overrides


def run_analysis(uploaded_file, master_file, excluded_sheets: List[str], mapping_overrides: Dict[str, Dict[str, Any]], thresholds: Dict[str, int]) -> Dict[str, Any]:
    normalized, raw, loader_issues, mapping = load_and_normalize_workbook(uploaded_file, excluded_sheets, mapping_overrides)
    masters = load_master_file(master_file) if master_file is not None else {}
    roster_check = build_roster_check(normalized)
    roster_sequence = build_roster_sequence(normalized)
    roster_exclusions = build_roster_exclusions(normalized)
    daily_hours = build_daily_hours_check(normalized)
    typo_warnings = build_typo_warnings(
        normalized,
        masters=masters,
        company_threshold=thresholds["company"],
        worker_threshold=thresholds["worker"],
        work_threshold=thresholds["work"],
        sop_threshold=thresholds["sop"],
    )
    data_quality = build_data_quality_issues(normalized, loader_issues)
    violations = build_violations(roster_check, daily_hours, roster_sequence)
    summary = summarize_results(normalized, roster_check, daily_hours, typo_warnings, data_quality)
    return {
        "normalized": normalized,
        "raw": raw,
        "mapping": mapping,
        "roster_check": roster_check,
        "roster_sequence": roster_sequence,
        "roster_exclusions": roster_exclusions,
        "daily_hours": daily_hours,
        "typo_warnings": typo_warnings,
        "data_quality": data_quality,
        "violations": violations,
        "summary": summary,
    }


def upload_page() -> None:
    st.header("Upload / Analyze")
    uploaded_file = st.file_uploader("Upload PWA Excel file", type=["xlsx", "xlsm", "xls"])
    master_file = st.file_uploader("Optional: Upload Reference Master Excel file", type=["xlsx", "xlsm", "xls"], key="master")

    with st.sidebar.expander("Similarity thresholds", expanded=False):
        company_threshold = st.slider("Company", 70, 100, 86)
        worker_threshold = st.slider("Worker", 70, 100, 88)
        work_threshold = st.slider("Task", 70, 100, 85)
        sop_threshold = st.slider("SOP", 70, 100, 88)

    if uploaded_file is None:
        st.info("PWA Excel 파일을 업로드하면 Sheet 선택, 컬럼 매핑, 검증을 진행할 수 있습니다.")
        return

    try:
        sheets = list_excel_sheets(uploaded_file)
    except Exception as exc:
        st.error(f"Could not read Excel file: {exc}")
        return

    default_excluded = [s for s in sheets if should_exclude_sheet(s)]
    excluded = st.multiselect(
        "Exclude sheets from PWA validation",
        sheets,
        default=default_excluded,
        help="Summary, Master, Config, Reference 등 검증 대상이 아닌 Sheet를 제외하세요.",
    )
    selected_sheets = [s for s in sheets if s not in excluded]
    st.write(f"Validation target sheets: **{len(selected_sheets)}** / {len(sheets)}")
    overrides = _mapping_ui(uploaded_file, selected_sheets)

    if st.button("Run Analysis", type="primary", use_container_width=True):
        with st.spinner("Analyzing workbook..."):
            uploaded_file.seek(0)
            if master_file is not None:
                master_file.seek(0)
            results = run_analysis(
                uploaded_file,
                master_file,
                excluded,
                overrides,
                {
                    "company": company_threshold,
                    "worker": worker_threshold,
                    "work": work_threshold,
                    "sop": sop_threshold,
                },
            )
            st.session_state.results = results
        st.success("Analysis completed.")

    current_results = st.session_state.get("results")
    if current_results:
        render_kpis(current_results["summary"])
        st.markdown("#### Generated Master File")
        if _operator_access_box("Upload Generated Master Download"):
            master_bytes = build_master_file(current_results.get("normalized"))
            st.download_button(
                "Download Generated Master File",
                data=master_bytes,
                file_name="pwa_reference_master_generated.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                help="현재 업로드한 PWA 파일에서 Company, Worker, Task, SOP, Site 기준 Master를 생성합니다.",
            )
        show_table(current_results["violations"], "Detected Violations", height=320)
        show_table(current_results["data_quality"], "Data Quality Issues", height=320)


def dashboard_page(results: Dict[str, Any]) -> None:
    st.header("Dashboard")
    render_kpis(results.get("summary", {}))
    c1, c2 = st.columns(2)
    with c1:
        show_table(results.get("violations"), "Violations", height=400)
    with c2:
        show_table(results.get("data_quality"), "Data Quality Issues", height=400)


def roster_page(results: Dict[str, Any]) -> None:
    st.header("PWA Roster Check")
    st.info("Firmware Update/FW-related tasks and Commissioning site-coordinator rows are excluded from Roster Limit counting, but they remain in Normalized Data and Daily Hours Check.")
    show_table(filter_dataframe(results.get("roster_check"), "roster"), "Site + Company Cumulative Worker Count")
    show_table(filter_dataframe(results.get("roster_sequence"), "sequence"), "Roster First Access Sequence")
    show_table(filter_dataframe(results.get("roster_exclusions"), "roster_exclusions"), "Rows Excluded from Roster Limit", height=360)


def daily_hours_page(results: Dict[str, Any]) -> None:
    st.header("Daily Hours Check")
    show_table(filter_dataframe(results.get("daily_hours"), "daily"), "Date + Company + Worker Total Site Hours")


def typo_page(results: Dict[str, Any]) -> None:
    st.header("Typo / Similarity Check")
    st.warning("Similarity warnings are review targets only. The app never auto-merges workers, companies, SOPs, or task names.")
    show_table(filter_dataframe(results.get("typo_warnings"), "typo"), "Similarity Warnings")


def quality_page(results: Dict[str, Any]) -> None:
    st.header("Data Quality")
    show_table(filter_dataframe(results.get("data_quality"), "quality"), "Data Quality Issues")


def normalized_page(results: Dict[str, Any]) -> None:
    st.header("Normalized Data")
    show_table(results.get("normalized"), "Internal Long Format Data")
    show_table(results.get("mapping"), "Column Mapping Summary", height=300)


def master_builder_page(results: Dict[str, Any]) -> None:
    st.header("Master Builder")
    if not _operator_access_box("Master Builder"):
        st.stop()
    st.caption("업로드한 PWA Excel 파일의 정규화 데이터를 기준으로 Reference Master 파일을 생성합니다. 생성된 파일은 다음 분석부터 Optional Reference Master Excel file로 업로드하여 오탈자 검증 기준으로 사용할 수 있습니다.")
    normalized = results.get("normalized")
    tables = build_master_tables(normalized)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Companies", len(tables.get("Company", pd.DataFrame())))
    with c2:
        st.metric("Workers", len(tables.get("Worker", pd.DataFrame())))
    with c3:
        st.metric("Tasks", len(tables.get("Task", pd.DataFrame())))
    with c4:
        st.metric("SOPs", len(tables.get("SOP", pd.DataFrame())))
    with c5:
        st.metric("Sites", len(tables.get("Site", pd.DataFrame())))

    master_bytes = build_master_file(normalized)
    st.download_button(
        "Download Generated Reference Master",
        data=master_bytes,
        file_name="pwa_reference_master_generated.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.info("다운로드 후 첫 번째 컬럼의 표준값을 검토/수정하세요. Company, Worker, Task, SOP, Site 시트의 첫 번째 기준 컬럼이 다음 분석의 Master 값으로 사용됩니다.")
    for sheet_name in ["Company", "Worker", "Task", "SOP", "Site", "Worker_By_Company"]:
        with st.expander(f"{sheet_name} preview", expanded=sheet_name in {"Company", "Worker", "Task", "SOP"}):
            show_table(tables.get(sheet_name), f"{sheet_name} Master", height=320)


def export_page(results: Dict[str, Any]) -> None:
    st.header("Export")
    report = build_excel_report(results)
    st.download_button(
        "Download Excel Audit Report",
        data=report,
        file_name="pwa_compliance_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.caption("Report sheets: Summary, PWA_Roster_Check, Roster_Sequence, Roster_Exclusions, Daily_Hours_Check, Violations, Typo_Warnings, Data_Quality_Issues, Normalized_Data, Raw_Data, Column_Mapping")


def main() -> None:
    _init_state()
    st.title(APP_TITLE)
    st.caption("Upload a PWA task-status workbook and validate roster limits, daily hours, typo warnings, and data quality issues.")
    _operator_logout_button()
    page = st.sidebar.radio(
        "Menu",
        [
            "Upload",
            "Dashboard",
            "PWA Roster Check",
            "Daily Hours Check",
            "Typo / Similarity Check",
            "Data Quality",
            "Normalized Data",
            "Master Builder",
            "Export",
        ],
    )
    results = st.session_state.get("results")
    if page == "Upload":
        upload_page()
        return
    if not results:
        st.info("Run analysis from the Upload page first.")
        return
    if page == "Dashboard":
        dashboard_page(results)
    elif page == "PWA Roster Check":
        roster_page(results)
    elif page == "Daily Hours Check":
        daily_hours_page(results)
    elif page == "Typo / Similarity Check":
        typo_page(results)
    elif page == "Data Quality":
        quality_page(results)
    elif page == "Normalized Data":
        normalized_page(results)
    elif page == "Master Builder":
        master_builder_page(results)
    elif page == "Export":
        export_page(results)


if __name__ == "__main__":
    main()
