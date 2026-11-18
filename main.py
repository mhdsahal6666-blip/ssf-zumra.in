"""
main.py
-------
FastAPI + FastMCP server for Zumra — SSF Theyyottuchira Unit Thursday night
family gathering booking system.

Features:
- Clean English schema with NO ward field.
- Unlimited dynamic year support (2027, 2028, 2029, and beyond).
- Streamable HTTP transport at /mcp for Gemini Connectors.
- Liveness check at GET /health.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastmcp import FastMCP
from pydantic import BaseModel, Field

import firebase_service as db

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("zumra-mcp")

# ─────────────────────────────────────────────────────────────────────────────
# Environment & Assets
# ─────────────────────────────────────────────────────────────────────────────
PORT: int = int(os.getenv("PORT", "8000"))
BASE_DIR: str = os.path.dirname(__file__)
ICON_PATH: str = os.path.join(BASE_DIR, "icon.png")
LOGO_SVG_PATH: str = os.path.join(BASE_DIR, "logo.svg")
FAVICON_PATH: str = os.path.join(BASE_DIR, "favicon.ico")

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas (Clean English, No Ward)
# ─────────────────────────────────────────────────────────────────────────────
class ZumraSlot(BaseModel):
    """Schema for a Thursday gathering slot (SSF Theyyottuchira Unit)."""
    id: str = Field(description="Firestore document ID (YYYY-MM-DD)")
    date: str = Field(description="Thursday date in YYYY-MM-DD format, e.g. '2027-01-07'")
    dateLabel: str = Field(description="English date label, e.g. 'January 7, 2027 • Thursday'")
    month: str = Field(description="English month and year, e.g. 'January 2027'")
    year: int = Field(description="Year as an integer, e.g. 2027")
    status: str = Field(description="Slot status: 'available', 'booked', 'live', or 'completed'")
    headName: str = Field(default="", description="Name of the family head / host")
    houseName: str = Field(default="", description="House / residence name")
    phone: str = Field(default="", description="Contact phone number of the host")
    prayerNote: str = Field(default="", description="Special prayer or dua request from the host family")


# ─────────────────────────────────────────────────────────────────────────────
# FastMCP Instance & HTTP App
# ─────────────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="zumra-mcp",
    instructions=(
        "You are the official booking assistant for SSF Theyyottuchira Unit — Zumra (സുംറ). "
        "Help unit members check, book, and manage Thursday night family gathering (zumra) slots. "
        "Support current year (2026), 2027, and all future years dynamically (2028, 2029+). "
        "Always confirm host name, house name, phone, and optional prayer note before confirming bookings. "
        "Communicate politely in English or Malayalam as preferred by the user."
    ),
)

# FastMCP ASGI sub-application with Streamable HTTP transport at /mcp
mcp_app = mcp.http_app(path="/mcp")

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Zumra MCP",
    description="MCP backend for SSF Theyyottuchira Unit — Zumra Thursday gathering bookings.",
    version="2.0.0",
    lifespan=mcp_app.lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health_check() -> dict:
    """Liveness probe endpoint for Koyeb / Render health checks."""
    return {"status": "ok", "service": "zumra-mcp", "unit": "SSF Theyyottuchira Unit"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Serve the Zumra logo as favicon for browser and MCP connector discovery."""
    if os.path.exists(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    if os.path.exists(ICON_PATH):
        return FileResponse(ICON_PATH, media_type="image/png")
    return Response(status_code=404)


@app.get("/logo.svg", include_in_schema=False)
async def logo_svg() -> Response:
    """Serve the custom green-and-blue leaf logo in SVG format."""
    if os.path.exists(LOGO_SVG_PATH):
        return FileResponse(LOGO_SVG_PATH, media_type="image/svg+xml")
    return Response(status_code=404)


@app.get("/logo.png", include_in_schema=False)
@app.get("/icon.png", include_in_schema=False)
async def icon() -> Response:
    """Serve the Zumra logo icon."""
    if os.path.exists(ICON_PATH):
        return FileResponse(ICON_PATH, media_type="image/png")
    return Response(status_code=404)


# Mount FastMCP app at root (routes /mcp to the MCP sub-application)
app.mount("/", mcp_app)


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_this_week_zumra() -> dict:
    """
    Get the current week's Zumra Thursday family gathering details for SSF Theyyottuchira Unit.

    Returns the slot that is currently live (this week's gathering).
    If no slot is currently live, returns the next upcoming booked Thursday gathering.

    The returned details include:
    - date, dateLabel, month, year
    - status ('live' | 'booked')
    - headName (host family head)
    - houseName (host house / residence)
    - phone (host contact number)
    - prayerNote (special prayer / dua request from the family)

    Returns an informational message if no upcoming booked gathering is scheduled.
    """
    slot = db.get_live_slot()
    if not slot:
        return {
            "found": False,
            "unit": "SSF Theyyottuchira Unit",
            "message": (
                "No live or upcoming booked Zumra slot found for SSF Theyyottuchira Unit. "
                "Upcoming Thursday slots are open and available for booking."
            ),
        }

    return {
        "found": True,
        "unit": "SSF Theyyottuchira Unit",
        "slot": slot,
        "summary": (
            f"This week's Zumra (SSF Theyyottuchira Unit) is at the home of "
            f"{slot.get('headName', '—')} ({slot.get('houseName', '—')}). "
            f"Date: {slot.get('dateLabel', slot.get('date', '—'))}."
        ),
    }


@mcp.tool()
def list_zumra_slots(
    year: Optional[int] = None,
    month: str = "",
    only_available: bool = False,
) -> list[dict]:
    """
    Dynamically list Thursday Zumra slots for any given year with optional month filter.

    Supports 2026, 2027, and any unlimited future year (e.g., 2028, 2029, 2030) on the fly.
    If year is omitted, it defaults in real time to the current year (datetime.now().year),
    so in 2026 it lists 2026 slots and automatically transitions to 2027 on January 1, 2027.

    Automatically generates all Thursdays for the requested year and merges real-time
    Firestore booking records so slots always return complete and accurate information.

    Args:
        year: Optional calendar year to list (defaults dynamically to current year, e.g. 2026).
              Supports 2026, 2027, 2028, 2029, and beyond.
        month: Optional filter by month name (e.g., 'November 2026', 'January 2027', or 'November').
        only_available: If True, only returns slots with status 'available'.

    Returns:
        List of slot objects sorted by date ascending. Each slot contains:
        id, date, dateLabel, month, year, status ('available' or 'booked'),
        headName, houseName, phone, prayerNote. (No ward field).

    Examples:
        list_zumra_slots()                                   → current year Thursdays (e.g. 2026)
        list_zumra_slots(year=2026)                          → all 2026 Thursdays
        list_zumra_slots(year=2027)                          → all 2027 Thursdays
        list_zumra_slots(month="November 2026")              → November 2026 Thursdays
        list_zumra_slots(only_available=True)                → all open Thursdays this year
    """
    target_year = year if (year is not None and year > 0) else datetime.now().year
    return db.list_slots(year=target_year, month=month, only_available=only_available)


@mcp.tool()
def book_zumra_thursday(
    date: str,
    head_name: str,
    house_name: str,
    phone: str,
    prayer_note: str = "",
) -> dict:
    """
    Book a Thursday Zumra gathering for a host family in SSF Theyyottuchira Unit.

    Works dynamically for any valid Thursday date in 2027, 2028, 2029, or beyond.
    If the slot does not exist in Firestore yet, it creates the slot on-the-fly
    with status 'booked'. If the slot is already booked, it prevents double-booking.

    Args:
        date:        Thursday date in YYYY-MM-DD format, e.g. '2027-01-07' or '2028-04-13'.
                     Must be a valid Thursday date.
        head_name:   Name of the family head / host (e.g., 'Ahmed Ali').
        house_name:  House / residence name (e.g., 'Rahmath Manzil').
        phone:       Contact phone number of the host.
        prayer_note: Optional special prayer / dua request from the host family.

    Returns:
        On success → { "success": True, "slot": { ...booked slot details... }, "message": "..." }
        On failure → { "success": False, "error": "<reason>" }
    """
    if not date or len(date) != 10 or date[4] != "-" or date[7] != "-":
        return {
            "success": False,
            "error": f"Invalid date format '{date}'. Please use YYYY-MM-DD (e.g. '2027-01-07').",
        }
    if not head_name.strip():
        return {"success": False, "error": "head_name cannot be empty."}
    if not house_name.strip():
        return {"success": False, "error": "house_name cannot be empty."}
    if not phone.strip():
        return {"success": False, "error": "phone cannot be empty."}

    result = db.book_slot(
        date_str=date.strip(),
        head_name=head_name.strip(),
        house_name=house_name.strip(),
        phone=phone.strip(),
        prayer_note=prayer_note.strip(),
    )
    if result.get("success"):
        slot = result.get("slot", {})
        result["message"] = (
            f"✅ Booking confirmed for SSF Theyyottuchira Unit! "
            f"{slot.get('dateLabel', date)} at {house_name} ({head_name}). JazakAllah Khair!"
        )
    return result


@mcp.tool()
def cancel_zumra_booking(date: str) -> dict:
    """
    Cancel an existing booked Thursday Zumra slot and reset it to 'available'.

    Clears headName, houseName, phone, and prayerNote, re-opening the slot
    for other families to book.

    Only slots with status 'booked' can be cancelled.

    Args:
        date: Thursday date in YYYY-MM-DD format, e.g. '2026-11-19' or '2027-01-07'.

    Returns:
        On success → { "success": True, "slot": { ...reset slot... }, "message": "..." }
        On failure → { "success": False, "error": "<reason>" }
    """
    if not date or len(date) != 10 or date[4] != "-" or date[7] != "-":
        return {
            "success": False,
            "error": f"Invalid date format '{date}'. Please use YYYY-MM-DD.",
        }

    result = db.cancel_slot(slot_date=date.strip())
    if result.get("success"):
        slot = result.get("slot", {})
        result["message"] = (
            f"🗑️ Booking for {slot.get('dateLabel', date)} has been cancelled. "
            "The slot is now available again for booking."
        )
    return result


@mcp.tool()
def replace_zumra_host(
    date: str,
    head_name: str,
    house_name: str,
    phone: str,
) -> dict:
    """
    Directly replace, update, or repair a Thursday Zumra host booking without using the web UI.

    Overwrites the slot with status 'booked', setting the new host details
    (headName, houseName, phone) and clearing prayerNote in one atomic Firestore
    operation. Useful for swapping hosts or repairing partial/broken records.

    Args:
        date:       Thursday date in YYYY-MM-DD format, e.g. '2026-11-19'.
        head_name:  Name of the host / family head (e.g. 'Ahmed Ali').
        house_name: House / residence name (e.g. 'Rahmath Manzil').
        phone:      Contact phone number of the host.

    Returns:
        On success → { "success": True, "slot": { ... }, "message": "..." }
        On failure → { "success": False, "error": "<reason>" }
    """
    if not date or len(date) != 10 or date[4] != "-" or date[7] != "-":
        return {
            "success": False,
            "error": f"Invalid date format '{date}'. Please use YYYY-MM-DD (e.g. '2026-11-19').",
        }
    if not head_name.strip():
        return {"success": False, "error": "head_name cannot be empty."}
    if not house_name.strip():
        return {"success": False, "error": "house_name cannot be empty."}
    if not phone.strip():
        return {"success": False, "error": "phone cannot be empty."}

    result = db.replace_host(
        slot_date=date.strip(),
        new_head_name=head_name.strip(),
        new_house_name=house_name.strip(),
        new_phone=phone.strip(),
    )
    if result.get("success"):
        slot = result.get("slot", {})
        result["message"] = (
            f"🔄 Host successfully updated for {slot.get('dateLabel', date)}! "
            f"Host: {slot.get('headName')} ({slot.get('houseName')}), Phone: {slot.get('phone')}."
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Zumra MCP server on 0.0.0.0:%d", PORT)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        reload=False,
    )
