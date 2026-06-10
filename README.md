# PWA Task / Time Compliance Checker

Python Streamlit application for validating PWA task-status Excel files by site.

## Main Checks

- Site + Company cumulative unique worker count limit: max 3 workers per project period
- Date + Company + Worker daily total site hours: max 8 hours across all sites
- Roster full warning when a Site + Company reaches exactly 3 workers
- Limit reached warning when a worker reaches exactly 8 hours in one day
- Company / Worker / Task / SOP similarity warnings using `rapidfuzz`
- Missing required values, invalid dates, invalid hours, negative hours, hours over 24, duplicate rows, and worker-company mismatch
- Exportable Excel audit report with raw and normalized data

## Input Workbook Rules

Each validation target sheet is treated as one Site. Sheet name becomes `Site`.

Automatically excluded sheet names include words such as `Summary`, `Master`, `Config`, and `Reference`. You can manually adjust this in the app.

### Long Format

| Company | Name | Task | SOP | Date | Hours |
|---|---|---|---|---|---:|
| HD | A1 | Firmware update | SOP-001 | 2026-05-04 | 8 |

### Wide Format

| Company | Name | Task | SOP | 2026-05-04 | 2026-05-05 |
|---|---|---|---|---:|---:|
| HD | A1 | Firmware update | SOP-001 | 8 | 0 |

The app converts all inputs internally to:

| Site | Company Original | Company Normalized | Worker Original | Worker Normalized | Task | SOP | Date | Hours |

## Installation

```bash
cd pwa_checker
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Generate Sample Data

```bash
python scripts/create_sample_data.py
```

This creates:

- `sample_pwa_input.xlsx`
- `sample_master.xlsx`

Upload `sample_pwa_input.xlsx` as the PWA file and optionally upload `sample_master.xlsx` as the master file.

Expected sample results include:

- Roster violation: Site A / HD has A1, A2, A3, A4
- Daily hour violation: A1 works Site A 8h + Site B 5h on 2026-05-04
- Limit reached warning: rows totaling exactly 8h
- Typo warnings: H.D. / HD LLC, John Smith / Jon Smith, SOP-001 / SOP001 / S0P-001
- Data quality warnings/errors: negative hours and over-24-hour values

## Streamlit Cloud Deployment

1. Push the `pwa_checker` folder to a GitHub repository.
2. Set `app.py` as the Streamlit entry file.
3. Make sure `requirements.txt` is in the same folder as `app.py` or in the repository root.
4. Do not store customer PWA files in the repository.
5. For confidential operational data, confirm your company's policy before using Streamlit Community Cloud. A private deployment is safer for customer task-status data.

## Important Logic Notes

- A person with entered site time is treated as a worker.
- Travel time is not calculated by the app. The input `Hours` is assumed to be site-stay/work time only.
- Site waiting time, lunch, breaks, meetings, and equipment preparation are included if already entered in `Hours`.
- Similarity warnings are not automatic corrections. The app never merges workers or SOPs automatically.
- PWA checks use normalized grouping keys but the report keeps original values and source row references.


## 실제 PWA 파일 호환성 개선

본 버전은 실제 작업 현황 파일처럼 1행이 비어 있고 2행부터 `Task`, `SOP`, `Company`, `Name`, 날짜 컬럼이 시작되는 Wide Format도 자동 인식합니다.

지원 예시:

| 빈칸 | Task | SOP | Company | Name | 2025-01-01 | 2025-01-02 | ... |
|---|---|---|---|---:|---:|---:|---:|
|  | B Replacement | B Replacement | HD | A1 | 8 | 0 | ... |

헤더가 첫 번째 행에 없더라도 앱이 자동으로 헤더 행을 추론합니다. 분석 가능한 데이터가 없거나 모든 Sheet가 제외된 경우에도 앱이 중단되지 않고 Data Quality Issue로 표시합니다.

## 2026-06-09 revision notes

- Same-date first-access workers are now evaluated as a roster-limit violation event when the cumulative Site + Company worker count exceeds 3. The app no longer labels this case as `Manual Review Required` merely because multiple workers appeared on the same date.
- `Status` is displayed as the first column on validation tables and exported report sheets where a status exists.
- Missing SOP is treated as `Warning`, not `Error`, when `Task` contains `Inspection`, `Trouble Shooting`, or `Troubleshooting`. The Data Quality page explains that SOP may be optional for those tasks and should be verified before customer submission.
- Excel export formatting now safely handles numeric, blank, NaN, list, tuple, set, and dict values. This fixes `TypeError: object of type 'float' has no len()` during report export.


## 2026-06-09 v5 revision notes

- `Master Builder` is now an operator-only function.
- Operator password: `1801`
- The `Master Builder` page is blocked until the password is entered.
- The `Upload` page's `Download Generated Master File` button is also blocked until operator authentication is completed.
- After authentication, `Operator mode active` is shown in the sidebar and can be locked again with `Lock Operator Mode`.
- This is a Streamlit UI-level restriction. For public Streamlit Cloud deployment, move the password to `st.secrets` instead of keeping it directly in source code.

## Generated Reference Master 기능

분석 실행 후 `Upload` 화면 또는 `Master Builder` 메뉴에서 현재 업로드한 PWA Excel 파일 기준의 Reference Master 파일을 다운로드할 수 있습니다.

생성 파일명:

- `pwa_reference_master_generated.xlsx`

생성 Sheet:

1. `Instructions`
2. `Company`
3. `Worker`
4. `Task`
5. `SOP`
6. `Site`
7. `Worker_By_Company`

사용 방법:

1. PWA Excel 파일 업로드
2. `Run Analysis` 실행
3. 운영자 비밀번호 `1801` 입력 후 인증
4. `Download Generated Master File` 또는 `Master Builder > Download Generated Reference Master` 클릭
5. 다운로드한 Master 파일에서 각 Sheet의 첫 번째 기준 컬럼을 검토/수정
   - Company Sheet: `Company`
   - Worker Sheet: `Worker`
   - Task Sheet: `Task`
   - SOP Sheet: `SOP`
   - Site Sheet: `Site`
6. 다음 분석 시 이 파일을 `Optional: Upload Reference Master Excel file`에 업로드

주의사항:

- 생성된 Master는 자동 확정값이 아니라 PWA 파일에서 추출한 후보값입니다.
- 오탈자가 있는 상태로 Master를 확정하면 이후 검증 기준도 오염됩니다.
- `Review Status` 컬럼은 검토 편의를 위한 컬럼입니다. 앱의 Master 로딩 기준은 각 Master Sheet의 첫 번째 기준 컬럼입니다.
- `Worker_By_Company` Sheet는 감사/검토용이며, 현재 typo 기준 Master로 직접 사용되지는 않습니다.

## 2026-06-10 v6 revision notes

- Roster Limit counting now excludes firmware-update related tasks.
  - Examples: `F/W`, `FW`, `F/W Update`, `FW update`, `Firm ware update`, `Firmware update`, and common misspelling variants such as `Firmeware update`.
- Roster Limit counting now excludes `Commissioning` task rows.
  - These rows are treated as site-coordinator records for roster purposes.
- The excluded rows are not deleted.
  - They remain in `Normalized Data`.
  - They remain included in `Daily Hours Check`.
  - They are listed separately in `Rows Excluded from Roster Limit` and in the exported `Roster_Exclusions` sheet.
- `Normalized Data` now includes:
  - `Roster Count Eligible`
  - `Roster Exclusion Reason`
