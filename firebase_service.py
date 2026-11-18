"""
firebase_service.py
-------------------
Firestore database operations for Zumra MCP (SSF Theyyottuchira Unit).

Features:
- Clean English schema with NO ward field.
- Dynamic unlimited future year support (2027, 2028, 2029, and beyond).
- On-the-fly Thursday slot generation & upsert/auto-creation.
- Supports both Direct REST API (with Web API Key) and Firebase Admin SDK.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

COLLECTION = "thursday_slots"

# Config from environment
PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "muth-18e58")
API_KEY = os.getenv("FIREBASE_API_KEY", "AIzaSyAEJeP0SqmdrSfiWdTRCViJSyR0FuJU4Rk")
FIRESTORE_REST_BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

# In-memory auth token cache for REST calls
_AUTH_TOKEN: Optional[str] = None
_AUTH_TOKEN_EXPIRY: float = 0.0

EMPTY_BOOKING_FIELDS = {
    "headName": "",
    "houseName": "",
    "phone": "",
    "prayerNote": "",
}


# ---------------------------------------------------------------------------
# Dynamic Thursday Helpers (Unlimited Years Support)
# ---------------------------------------------------------------------------

def format_date_label(d: date) -> str:
    """Format date into clean English label, e.g. 'January 7, 2027 • Thursday'."""
    month_name = d.strftime("%B")
    return f"{month_name} {d.day}, {d.year} • Thursday"


def format_month_label(d: date) -> str:
    """Format month into English label, e.g. 'January 2027'."""
    return f"{d.strftime('%B')} {d.year}"


def generate_slot_metadata(d: date) -> dict:
    """Generate default available slot structure for a given Thursday."""
    return {
        "id": d.isoformat(),
        "date": d.isoformat(),
        "dateLabel": format_date_label(d),
        "month": format_month_label(d),
        "year": d.year,
        "status": "available",
        "headName": "",
        "houseName": "",
        "phone": "",
        "prayerNote": "",
    }


def get_thursdays_for_year(year: int) -> list[date]:
    """Calculate all Thursday dates in a given calendar year dynamically."""
    curr = date(year, 1, 1)
    # Thursday is weekday 3 (Monday = 0, Sunday = 6)
    days_ahead = (3 - curr.weekday()) % 7
    curr = curr.fromordinal(curr.toordinal() + days_ahead)
    thursdays = []
    while curr.year == year:
        thursdays.append(curr)
        curr = curr.fromordinal(curr.toordinal() + 7)
    return thursdays


def parse_year_from_input(year: Optional[int] = None, month: str = "") -> int:
    """Extract or infer target year from year integer or month string, defaulting to current year."""
    if month:
        # Check for 4-digit year in month string like 'November 2026' or 'March 2028'
        match = re.search(r"\b(20\d\d)\b", month)
        if match:
            return int(match.group(1))
    if year is not None and year > 0:
        return year
    return datetime.now().year


# ---------------------------------------------------------------------------
# Firebase Admin SDK Mode (Optional)
# ---------------------------------------------------------------------------
_ADMIN_INITIALIZED = False
_ADMIN_DB = None


def _try_init_firebase_admin() -> bool:
    """Attempts to initialize Firebase Admin SDK if service account is provided."""
    global _ADMIN_INITIALIZED, _ADMIN_DB
    if _ADMIN_INITIALIZED:
        return _ADMIN_DB is not None

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        logger.info("firebase_admin not installed; using direct REST API mode.")
        _ADMIN_INITIALIZED = True
        return False

    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_json:
        try:
            sa_dict = json.loads(sa_json)
            cred = credentials.Certificate(sa_dict)
            firebase_admin.initialize_app(cred)
            _ADMIN_DB = firestore.client()
            _ADMIN_INITIALIZED = True
            logger.info("Firebase Admin initialized from service account JSON.")
            return True
        except Exception as e:
            logger.warning("Could not initialize Firebase Admin from JSON: %s", e)

    key_path = os.getenv("FIREBASE_KEY_PATH", "serviceAccountKey.json")
    if os.path.exists(key_path):
        try:
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
            _ADMIN_DB = firestore.client()
            _ADMIN_INITIALIZED = True
            logger.info("Firebase Admin initialized from %s.", key_path)
            return True
        except Exception as e:
            logger.warning("Could not initialize Firebase Admin from %s: %s", key_path, e)

    _ADMIN_INITIALIZED = True
    return False


# ---------------------------------------------------------------------------
# Firestore REST API Client
# ---------------------------------------------------------------------------

def _get_auth_token() -> Optional[str]:
    """Obtain or return cached anonymous authentication token if needed."""
    global _AUTH_TOKEN, _AUTH_TOKEN_EXPIRY
    if _AUTH_TOKEN and time.time() < _AUTH_TOKEN_EXPIRY - 60:
        return _AUTH_TOKEN

    if not API_KEY:
        return None

    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={API_KEY}"
        resp = httpx.post(url, json={"returnSecureToken": True}, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            _AUTH_TOKEN = data.get("idToken")
            expires_in = int(data.get("expiresIn", 3600))
            _AUTH_TOKEN_EXPIRY = time.time() + expires_in
            return _AUTH_TOKEN
    except Exception as exc:
        logger.debug("Anonymous auth token request note: %s", exc)

    return None


def _make_rest_request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
) -> httpx.Response:
    """Execute an HTTP request to Firestore REST API with API key and auth headers."""
    params = params.copy() if params else {}
    if API_KEY and "key" not in params:
        params["key"] = API_KEY

    headers = {"Content-Type": "application/json"}
    token = _get_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{FIRESTORE_REST_BASE}/{path.lstrip('/')}"
    with httpx.Client(timeout=15.0) as client:
        return client.request(method, url, params=params, json=json_data, headers=headers)


def _parse_firestore_value(val: dict) -> Any:
    """Recursively parse a Firestore typed-value map into native Python types."""
    if "stringValue" in val:
        return val["stringValue"]
    if "integerValue" in val:
        return int(val["integerValue"])
    if "doubleValue" in val:
        return float(val["doubleValue"])
    if "booleanValue" in val:
        return val["booleanValue"]
    if "mapValue" in val:
        fields = val["mapValue"].get("fields", {})
        return {k: _parse_firestore_value(v) for k, v in fields.items()}
    if "arrayValue" in val:
        values = val["arrayValue"].get("values", [])
        return [_parse_firestore_value(v) for v in values]
    if "nullValue" in val:
        return None
    return val


def _clean_doc_dict(data: dict, doc_id: str = "") -> dict:
    """Clean dictionary to match exact English schema with legacy field normalization."""
    date_str = data.get("date", doc_id)
    # Infer year if missing
    year_val = data.get("year")
    if year_val is None and date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        year_val = int(date_str[:4])
    elif year_val is not None:
        try:
            year_val = int(year_val)
        except (ValueError, TypeError):
            year_val = datetime.now().year
    else:
        year_val = datetime.now().year

    # Ensure clean English labels if date is valid
    date_label = data.get("dateLabel", "")
    month_label = data.get("month", "")
    if date_str and (not date_label or "•" not in date_label):
        try:
            parsed_d = datetime.strptime(date_str, "%Y-%m-%d").date()
            date_label = format_date_label(parsed_d)
            if not month_label:
                month_label = format_month_label(parsed_d)
        except ValueError:
            pass

    # Normalize legacy / partial fallback keys
    head_name = (
        data.get("headName")
        or data.get("name")
        or data.get("hostName")
        or ""
    )
    if isinstance(head_name, str):
        head_name = head_name.strip()
    else:
        head_name = str(head_name) if head_name is not None else ""

    house_name = (
        data.get("houseName")
        or data.get("house")
        or ""
    )
    if isinstance(house_name, str):
        house_name = house_name.strip()
    else:
        house_name = str(house_name) if house_name is not None else ""

    phone = (
        data.get("phone")
        or data.get("phoneNumber")
        or data.get("whatsapp")
        or ""
    )
    if isinstance(phone, str):
        phone = phone.strip()
    else:
        phone = str(phone) if phone is not None else ""

    prayer_note = data.get("prayerNote", "") or ""
    if isinstance(prayer_note, str):
        prayer_note = prayer_note.strip()
    else:
        prayer_note = str(prayer_note) if prayer_note is not None else ""

    raw_status = (data.get("status") or "available").strip().lower()
    # If houseName or headName is non-empty even when status is "available",
    # automatically treat and return the slot's effective status as "booked"
    # so partially booked dates are never shown as open.
    if (head_name or house_name) and raw_status == "available":
        effective_status = "booked"
    else:
        effective_status = raw_status if raw_status else "available"

    return {
        "id": doc_id or date_str,
        "date": date_str,
        "dateLabel": date_label,
        "month": month_label,
        "year": year_val if year_val else datetime.now().year,
        "status": effective_status,
        "headName": head_name,
        "houseName": house_name,
        "phone": phone,
        "prayerNote": prayer_note,
    }


def _doc_to_dict(doc: dict) -> dict:
    """Convert a raw Firestore REST document JSON into a clean slot dict."""
    name = doc.get("name", "")
    doc_id = name.split("/")[-1] if "/" in name else ""
    fields = doc.get("fields", {})
    raw = {k: _parse_firestore_value(v) for k, v in fields.items()}
    return _clean_doc_dict(raw, doc_id=doc_id)


def _to_firestore_field(val: Any) -> dict:
    """Convert a Python value into a Firestore REST typed value."""
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    if isinstance(val, str):
        return {"stringValue": val}
    if val is None:
        return {"nullValue": None}
    if isinstance(val, list):
        return {"arrayValue": {"values": [_to_firestore_field(x) for x in val]}}
    if isinstance(val, dict):
        return {"mapValue": {"fields": {k: _to_firestore_field(v) for k, v in val.items()}}}
    return {"stringValue": str(val)}


def _dict_to_firestore_fields(data: dict) -> dict:
    """Convert a Python dict into Firestore fields map (excluding id and ward)."""
    clean_keys = [
        "date",
        "dateLabel",
        "month",
        "year",
        "status",
        "headName",
        "houseName",
        "phone",
        "prayerNote",
    ]
    return {k: _to_firestore_field(data[k]) for k in clean_keys if k in data}


# ---------------------------------------------------------------------------
# Public Read Operations
# ---------------------------------------------------------------------------

def get_slot_by_date(date_str: str) -> Optional[dict]:
    """Fetch a single slot by date from Firestore (returns None if not saved yet)."""
    if _try_init_firebase_admin() and _ADMIN_DB:
        doc = _ADMIN_DB.collection(COLLECTION).document(date_str).get()
        if doc.exists:
            return _clean_doc_dict(doc.to_dict() or {}, doc_id=doc.id)
        return None

    resp = _make_rest_request("GET", f"{COLLECTION}/{date_str}")
    if resp.status_code == 200:
        return _doc_to_dict(resp.json())
    return None


def fetch_all_saved_slots() -> list[dict]:
    """Fetch all saved Thursday slot documents currently in Firestore."""
    if _try_init_firebase_admin() and _ADMIN_DB:
        results = []
        for doc in _ADMIN_DB.collection(COLLECTION).stream():
            results.append(_clean_doc_dict(doc.to_dict() or {}, doc_id=doc.id))
        return results

    resp = _make_rest_request("GET", COLLECTION, params={"pageSize": 300})
    if resp.status_code != 200:
        logger.warning("Failed to fetch slots via REST: %s %s", resp.status_code, resp.text)
        return []

    docs = resp.json().get("documents", [])
    return [_doc_to_dict(d) for d in docs]


def list_slots(year: Optional[int] = None, month: str = "", only_available: bool = False) -> list[dict]:
    """
    List Thursday slots for any given year (e.g. 2026, 2027, 2028, 2029...) with optional month filter.
    Defaults dynamically to datetime.now().year if year is not specified.

    Dynamically generates all Thursdays for the target year and merges any existing
    Firestore records (booked, live, completed) on top of the base schedule so
    2026 and unlimited future years always return complete, accurate data immediately.
    """
    target_year = parse_year_from_input(year=year, month=month)

    # 1. Dynamically generate all Thursdays for the target year
    thursdays = get_thursdays_for_year(target_year)
    slots_map: dict[str, dict] = {
        d.isoformat(): generate_slot_metadata(d) for d in thursdays
    }

    # 2. Fetch saved Firestore records and merge on top
    saved_slots = fetch_all_saved_slots()
    for saved in saved_slots:
        slot_date = saved.get("date", "")
        # Merge if this saved slot belongs to the target year
        if slot_date in slots_map or (saved.get("year") == target_year):
            slots_map[slot_date] = saved

    all_slots = list(slots_map.values())

    # 3. Apply month filter if provided
    if month:
        m_filter = month.strip().lower()
        all_slots = [
            s for s in all_slots
            if m_filter in s.get("month", "").lower()
            or m_filter in s.get("dateLabel", "").lower()
        ]

    # 4. Apply only_available filter if requested
    if only_available:
        all_slots = [s for s in all_slots if s.get("status") == "available"]

    # 5. Sort ascending by date
    all_slots.sort(key=lambda s: s.get("date", ""))
    return all_slots


def get_live_slot() -> Optional[dict]:
    """
    Return the slot with status == 'live'.
    If none is currently live, return the next upcoming 'booked' Thursday.
    """
    saved = fetch_all_saved_slots()
    if not saved:
        return None

    # Check for live slot first
    for s in saved:
        if s.get("status") == "live":
            return s

    # Fall back to next upcoming booked slot
    today_str = date.today().isoformat()
    future_booked = [
        s for s in saved
        if s.get("status") == "booked" and s.get("date", "") >= today_str
    ]
    if future_booked:
        future_booked.sort(key=lambda s: s.get("date", ""))
        return future_booked[0]

    # Any booked slot sorted by date
    all_booked = [s for s in saved if s.get("status") == "booked"]
    if all_booked:
        all_booked.sort(key=lambda s: s.get("date", ""))
        return all_booked[0]

    return None


# ---------------------------------------------------------------------------
# Write Operations (On-the-Fly Creation & Booking)
# ---------------------------------------------------------------------------

def book_slot(
    date_str: str,
    head_name: str,
    house_name: str,
    phone: str,
    prayer_note: str = "",
) -> dict:
    """
    Book a Thursday Zumra slot.

    Validates that date_str is actually a Thursday. If the document does not exist
    in Firestore yet (e.g. for future years like 2028, 2029), it automatically
    creates the document with status 'booked'. If already booked, prevents double-booking.
    """
    # 1. Validate date format
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid date format '{date_str}'. Please use YYYY-MM-DD (e.g., '2027-01-07').",
        }

    # 2. Validate that it is a Thursday
    if d.weekday() != 3:
        day_name = d.strftime("%A")
        return {
            "success": False,
            "error": (
                f"The date '{date_str}' is a {day_name}, not a Thursday. "
                "Only Thursday nights can be booked for Zumra gathering."
            ),
        }

    # 3. Check existing slot
    existing = get_slot_by_date(date_str)
    if existing:
        current_status = existing.get("status", "")
        if current_status != "available":
            head = existing.get("headName", "")
            label = existing.get("dateLabel", date_str)
            msg = f"The slot for {label} is already {current_status}."
            if current_status == "booked" and head:
                msg += f" Currently booked by: {head}."
            return {"success": False, "error": msg}

    # 4. Prepare full slot payload
    slot_payload = {
        "date": date_str,
        "dateLabel": format_date_label(d),
        "month": format_month_label(d),
        "year": d.year,
        "status": "booked",
        "headName": head_name,
        "houseName": house_name,
        "phone": phone,
        "prayerNote": prayer_note,
    }

    # 5. Persist to Firestore (Admin SDK or REST Upsert)
    if _try_init_firebase_admin() and _ADMIN_DB:
        ref = _ADMIN_DB.collection(COLLECTION).document(date_str)
        ref.set(slot_payload, merge=True)
        res = ref.get().to_dict() or {}
        return {"success": True, "slot": _clean_doc_dict(res, doc_id=date_str)}

    # Direct REST API upsert
    url = f"{FIRESTORE_REST_BASE}/{COLLECTION}/{date_str}"
    body = {"fields": _dict_to_firestore_fields(slot_payload)}
    params = [("key", API_KEY)]

    headers = {"Content-Type": "application/json"}
    token = _get_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(url, params=params, json=body, headers=headers)
        if resp.status_code == 200:
            updated_slot = _doc_to_dict(resp.json())
            return {"success": True, "slot": updated_slot}
        else:
            logger.error("REST book error: %s %s", resp.status_code, resp.text)
            return {
                "success": False,
                "error": f"Failed to book slot in Firestore (HTTP {resp.status_code}).",
            }


def cancel_slot(slot_date: str = "", date_str: str = "") -> dict:
    """Reset a booked slot back to 'available', clearing all booking details."""
    target_date = (slot_date or date_str).strip()
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid date format '{target_date}'. Please use YYYY-MM-DD.",
        }

    if d.weekday() != 3:
        return {
            "success": False,
            "error": f"The date '{target_date}' is not a Thursday.",
        }

    existing = get_slot_by_date(target_date)
    if not existing:
        return {
            "success": False,
            "error": f"No Thursday slot found for date '{target_date}'.",
        }

    current_status = existing.get("status", "")
    if current_status != "booked":
        if current_status == "available":
            return {
                "success": False,
                "error": f"The slot for '{target_date}' is already available — nothing to cancel.",
            }
        return {
            "success": False,
            "error": (
                f"Cannot cancel a slot with status '{current_status}'. "
                "Only 'booked' slots may be cancelled."
            ),
        }

    reset_payload = {
        "date": target_date,
        "dateLabel": format_date_label(d),
        "month": format_month_label(d),
        "year": d.year,
        "status": "available",
        **EMPTY_BOOKING_FIELDS,
    }

    if _try_init_firebase_admin() and _ADMIN_DB:
        ref = _ADMIN_DB.collection(COLLECTION).document(target_date)
        ref.set(reset_payload, merge=True)
        res = ref.get().to_dict() or {}
        return {"success": True, "slot": _clean_doc_dict(res, doc_id=target_date)}

    # Direct REST API update
    url = f"{FIRESTORE_REST_BASE}/{COLLECTION}/{target_date}"
    body = {"fields": _dict_to_firestore_fields(reset_payload)}
    params = [("key", API_KEY)]

    headers = {"Content-Type": "application/json"}
    token = _get_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(url, params=params, json=body, headers=headers)
        if resp.status_code == 200:
            updated_slot = _doc_to_dict(resp.json())
            return {"success": True, "slot": updated_slot}
        else:
            logger.error("REST cancel error: %s %s", resp.status_code, resp.text)
            return {
                "success": False,
                "error": f"Failed to cancel slot in Firestore (HTTP {resp.status_code}).",
            }


def replace_host(
    slot_date: str = "",
    new_head_name: str = "",
    new_house_name: str = "",
    new_phone: str = "",
    date_str: str = "",
    head_name: str = "",
    house_name: str = "",
    phone: str = "",
) -> dict:
    """
    Directly overwrite or replace the host for a given Thursday slot.
    Sets status='booked', updates headName, houseName, phone, and clears prayerNote=''.
    Uses an atomic set(..., merge=True) in Firestore.
    """
    target_date = (slot_date or date_str).strip()
    h_name = (new_head_name or head_name).strip()
    hs_name = (new_house_name or house_name).strip()
    ph = (new_phone or phone).strip()

    try:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": f"Invalid date format '{target_date}'. Please use YYYY-MM-DD (e.g. '2026-11-19').",
        }

    if d.weekday() != 3:
        day_name = d.strftime("%A")
        return {
            "success": False,
            "error": f"The date '{target_date}' is a {day_name}, not a Thursday. Only Thursdays can be hosted.",
        }

    slot_payload = {
        "date": target_date,
        "dateLabel": format_date_label(d),
        "month": format_month_label(d),
        "year": d.year,
        "status": "booked",
        "headName": h_name,
        "houseName": hs_name,
        "phone": ph,
        "prayerNote": "",
    }

    if _try_init_firebase_admin() and _ADMIN_DB:
        ref = _ADMIN_DB.collection(COLLECTION).document(target_date)
        ref.set(slot_payload, merge=True)
        res = ref.get().to_dict() or {}
        return {"success": True, "slot": _clean_doc_dict(res, doc_id=target_date)}

    # Direct REST API upsert
    url = f"{FIRESTORE_REST_BASE}/{COLLECTION}/{target_date}"
    body = {"fields": _dict_to_firestore_fields(slot_payload)}
    params = [("key", API_KEY)]

    headers = {"Content-Type": "application/json"}
    token = _get_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(url, params=params, json=body, headers=headers)
        if resp.status_code == 200:
            updated_slot = _doc_to_dict(resp.json())
            return {"success": True, "slot": updated_slot}
        else:
            logger.error("REST replace_host error: %s %s", resp.status_code, resp.text)
            return {
                "success": False,
                "error": f"Failed to replace host in Firestore (HTTP {resp.status_code}).",
            }


# Explicit function aliases for legacy & normalized reads
get_slots_for_year = list_slots
get_current_week_host = get_live_slot
