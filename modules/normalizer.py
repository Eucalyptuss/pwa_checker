from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from typing import Any, Optional, Tuple

import pandas as pd

_COMPANY_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "LTD", "LIMITED", "CO", "COMPANY", "CORP", "CORPORATION",
    "PLC", "LP", "LLP", "GMBH", "USA", "US", "THE"
}


def is_blank(value: Any) -> bool:
    """Return True for values that should be treated as empty user input."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def normalize_whitespace(value: Any) -> str:
    if is_blank(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_header(value: Any) -> str:
    text = normalize_whitespace(value).lower()
    text = re.sub(r"[_\-./()\[\]{}:;]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_general(value: Any) -> str:
    text = normalize_whitespace(value).upper()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"[^0-9A-Z가-힣&+\-/ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_alnum(value: Any) -> str:
    text = normalize_general(value)
    return re.sub(r"[^0-9A-Z가-힣]+", "", text)


def normalize_company(value: Any) -> str:
    """Aggressive company normalization for grouping likely variants such as H.D. and HD LLC."""
    text = normalize_general(value)
    if not text:
        return ""
    text = text.replace("&", " AND ")
    tokens = [t for t in re.split(r"[^0-9A-Z가-힣]+", text) if t]
    tokens = [t for t in tokens if t not in _COMPANY_SUFFIXES]
    if not tokens:
        tokens = [compact_alnum(value)]
    return "".join(tokens)


def normalize_worker(value: Any) -> str:
    text = normalize_general(value)
    # Keep token order. Names are not auto-merged because that can create audit errors.
    return re.sub(r"[^0-9A-Z가-힣 ]+", " ", text).strip()


def normalize_work(value: Any) -> str:
    text = normalize_general(value)
    aliases = {
        "FW": "FIRMWARE",
        "F W": "FIRMWARE",
        "FWUPDATE": "FIRMWARE UPDATE",
        "FIRMWAREUPDATE": "FIRMWARE UPDATE",
    }
    compact = compact_alnum(text)
    return aliases.get(compact, text)


def is_firmware_update_task(value: Any) -> bool:
    """Return True for firmware-update related tasks excluded from roster count.

    Business terms observed in PWA files include FW, F/W, F/W Update, Firm ware
    update, and Firmware update.  The function intentionally checks only task
    text and does not change daily-hour calculations.
    """
    text = normalize_general(value)
    compact = compact_alnum(text)
    if not compact:
        return False
    firmware_markers = {
        "FW",
        "FWUPDATE",
        "FIRMWARE",
        "FIRMWAREUPDATE",
        "FIRMEWARE",
        "FIRMEWAREUPDATE",
        "FIRMWAR",
        "FIRMWARUPDATE",
    }
    return (
        compact in firmware_markers
        or "FIRMWARE" in compact
        or "FIRMEWARE" in compact
        or ("FIRM" in compact and "WARE" in compact)
        or compact.startswith("FW")
    )


def is_commissioning_task(value: Any) -> bool:
    """Return True when Task marks a site coordinator/commissioning role."""
    compact = compact_alnum(value)
    return "COMMISSIONING" in compact


def roster_exclusion_reason(task_value: Any) -> str:
    """Explain why a row is excluded from PWA Roster Limit count."""
    if is_commissioning_task(task_value):
        return "Task is Commissioning; treated as site coordinator and excluded from Roster Limit."
    if is_firmware_update_task(task_value):
        return "Task is Firmware Update/FW-related work and excluded from Roster Limit."
    return ""


def normalize_sop(value: Any) -> str:
    text = normalize_general(value)
    text = text.replace(" ", "")
    text = re.sub(r"[^0-9A-Z가-힣\-]+", "", text)
    return text


def display_value(series: pd.Series) -> str:
    """Return a stable representative non-empty original value for display."""
    vals = [normalize_whitespace(v) for v in series.dropna().tolist() if normalize_whitespace(v)]
    if not vals:
        return ""
    return pd.Series(vals).mode().iloc[0]


def parse_excel_serial_date(value: Any) -> Optional[pd.Timestamp]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return None
        # Excel serial dates in normal business files are usually between 1900 and 2100.
        if 1 <= float(value) <= 73050:
            try:
                return pd.to_datetime(float(value), unit="D", origin="1899-12-30", errors="coerce")
            except Exception:
                return None
    return None


def parse_date(value: Any) -> Tuple[Optional[pd.Timestamp], Optional[str]]:
    if is_blank(value):
        return None, "Missing Date"
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None, "Missing Date"
        return value.normalize(), None
    if isinstance(value, datetime):
        return pd.Timestamp(value).normalize(), None
    serial = parse_excel_serial_date(value)
    if serial is not None and not pd.isna(serial):
        return serial.normalize(), None
    try:
        ts = pd.to_datetime(value, errors="coerce")
    except Exception:
        ts = pd.NaT
    if pd.isna(ts):
        return None, f"Invalid Date: {value}"
    return pd.Timestamp(ts).normalize(), None


def is_date_like_header(value: Any) -> bool:
    if is_blank(value):
        return False
    if isinstance(value, (datetime, pd.Timestamp)):
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return parse_excel_serial_date(value) is not None
    text = normalize_whitespace(value)
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text):
        return True
    if re.fullmatch(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", text):
        return True
    # Avoid parsing generic words such as Name or Time as dates.
    if not re.search(r"\d", text):
        return False
    try:
        ts = pd.to_datetime(text, errors="coerce")
        return not pd.isna(ts)
    except Exception:
        return False


def parse_hours(value: Any) -> Tuple[Optional[float], Optional[str]]:
    if is_blank(value):
        return None, None
    if isinstance(value, bool):
        return None, f"Invalid Hours: {value}"
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None, f"Invalid Hours: {value}"
        hours = float(value)
    else:
        text = normalize_whitespace(value).lower()
        text = text.replace(",", "")
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            return None, f"Invalid Hours: {value}"
        hours = float(match.group(0))
    if hours < 0:
        return hours, "Negative Hours"
    if hours > 24:
        return hours, "Hours Over 24"
    return hours, None


def fmt_date(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d")
