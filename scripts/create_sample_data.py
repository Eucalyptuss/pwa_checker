from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_sample_workbook(output_path: str = "sample_pwa_input.xlsx") -> None:
    """Create a sample workbook that intentionally includes OK, Warning, Violation, and typo cases."""
    site_a = pd.DataFrame({
        "Company": ["HD", "H.D.", "HD LLC", "HD", "HN", "HN"],
        "Name": ["A1", "A2", "A3", "A4", "John Smith", "Jon Smith"],
        "Task": ["Firmware update", "Firmware Update", "Firmeware update", "Inspection", "Inspection", "Inspecton"],
        "SOP": ["SOP-001", "SOP001", "S0P-001", "SOP-002", "SOP-003", "SOP-003"],
        "2026-05-04": [8, 0, 0, 0, 4, 0],
        "2026-05-05": [0, 8, 8, 8, 4, 4],
        "2026-06-01": [0, 0, 0, 4, 0, 0],
    })

    site_b = pd.DataFrame({
        "Contractor": ["HD", "HN", "HN", "HN"],
        "Worker": ["A1", "B1", "B2", "B3"],
        "Task": ["Inspection", "Water pump replacement", "Inspection", "Inspection"],
        "Procedure": ["SOP-002", "SOP-010", "SOP-002", "SOP-002"],
        "Work Date": ["2026-05-04", "2026-05-06", "2026-05-06", "2026-05-06"],
        "Work Hours": [5, 7, -1, "25h"],
    })

    summary = pd.DataFrame({"Note": ["This sheet should be excluded automatically."]})

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        site_a.to_excel(writer, sheet_name="Site A", index=False)
        site_b.to_excel(writer, sheet_name="Site B", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)


def build_master_workbook(output_path: str = "sample_master.xlsx") -> None:
    company = pd.DataFrame({"Company": ["HD", "HN"]})
    worker = pd.DataFrame({"Worker": ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "John Smith"]})
    work = pd.DataFrame({"Task": ["Firmware update", "Inspection", "Water pump replacement"]})
    sop = pd.DataFrame({"SOP": ["SOP-001", "SOP-002", "SOP-003", "SOP-010"]})
    site = pd.DataFrame({"Site": ["Site A", "Site B"]})
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        company.to_excel(writer, sheet_name="Company Master", index=False)
        worker.to_excel(writer, sheet_name="Worker Master", index=False)
        work.to_excel(writer, sheet_name="Task Master", index=False)
        sop.to_excel(writer, sheet_name="SOP Master", index=False)
        site.to_excel(writer, sheet_name="Site Master", index=False)


if __name__ == "__main__":
    base = Path(__file__).resolve().parents[1]
    build_sample_workbook(str(base / "sample_pwa_input.xlsx"))
    build_master_workbook(str(base / "sample_master.xlsx"))
    print("Created sample_pwa_input.xlsx and sample_master.xlsx")
