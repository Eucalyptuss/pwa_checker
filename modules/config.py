from __future__ import annotations

EXCLUDE_SHEET_KEYWORDS = {
    "SUMMARY", "MASTER", "CONFIG", "REFERENCE", "REF", "README", "HELP", "INSTRUCTION", "INSTRUCTIONS", "SETTING", "SETTINGS"
}

# Internal mapping key remains "work" for backward compatibility with prior code,
# but the user-facing column name is Task.
COLUMN_CANDIDATES = {
    "company": ["company", "contractor", "vendor", "subcontractor", "회사", "업체", "소속"],
    "worker": ["name", "worker", "employee", "technician", "person", "담당자", "작업자", "이름", "인원"],
    "work": ["task", "work scope", "work", "activity", "description", "작업내용", "작업 현황", "업무내용"],
    "sop": ["sop", "sop no", "procedure", "procedure no", "work instruction", "wi", "sop 번호"],
    "date": ["date", "work date", "날짜", "작업일"],
    "hours": ["hours", "work hours", "time", "작업시간", "시간"],
}

REQUIRED_FIELDS = ["Site", "Company", "Worker", "Date", "Hours", "Task", "SOP"]

STATUS_ORDER = ["Error", "Violation", "Manual Review Required", "Roster Full", "Warning", "OK"]

STATUS_COLORS = {
    "OK": "#DCFCE7",
    "Warning": "#FEF3C7",
    "Roster Full": "#FFEDD5",
    "Violation": "#FECACA",
    "Error": "#FCA5A5",
    "Manual Review Required": "#EDE9FE",
}

STATUS_FONT_COLORS = {
    "OK": "#14532D",
    "Warning": "#713F12",
    "Roster Full": "#7C2D12",
    "Violation": "#7F1D1D",
    "Error": "#450A0A",
    "Manual Review Required": "#3B0764",
}

MASTER_TYPES = {
    "Company": ["company", "contractor", "vendor", "회사", "업체"],
    "Worker": ["worker", "name", "employee", "person", "작업자", "담당자", "이름"],
    "Task": ["task", "work", "work scope", "activity", "description", "작업", "작업내용", "작업 현황", "업무내용"],
    "SOP": ["sop", "procedure", "wi", "sop 번호"],
    "Site": ["site", "location", "site name", "현장", "사이트"],
}
