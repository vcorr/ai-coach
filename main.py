import logging
from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI

from services.garmin import garmin_service

# Load .env file for local development
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Hybrid Athlete Coach")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "AI Coach is running", "version": "0.2.0"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


# === Debug endpoints ===


@app.get("/debug/garmin-login")
async def debug_garmin_login() -> dict[str, str | None]:
    """Test Garmin authentication."""
    success = garmin_service.login()

    if success:
        display_name = garmin_service.get_display_name()
        return {
            "status": "success",
            "message": "Garmin login successful",
            "display_name": display_name,
        }
    else:
        return {
            "status": "error",
            "message": "Garmin login failed. Check GARMIN_EMAIL and GARMIN_PASSWORD env vars.",
        }


@app.get("/debug/garmin-data")
async def debug_garmin_data() -> dict[str, Any]:
    """Fetch all Garmin data needed for coaching."""
    # Ensure we're logged in
    if not garmin_service.client:
        success = garmin_service.login()
        if not success:
            return {"error": "Garmin login failed"}

    return {
        "today_stats": garmin_service.get_today_stats(),
        "recent_activities": garmin_service.get_recent_activities(),
    }


@app.get("/debug/garmin-sleep-raw")
async def debug_garmin_sleep_raw() -> dict[str, Any]:
    """Debug: See raw sleep API responses for last 7 days."""
    if not garmin_service.client:
        success = garmin_service.login()
        if not success:
            return {"error": "Garmin login failed"}

    client = garmin_service.client
    assert client is not None  # Guarded by login check above

    results: dict[str, Any] = {}
    for days_ago in range(7):
        check_date = (date.today() - timedelta(days=days_ago)).isoformat()
        try:
            raw = client.get_sleep_data(check_date)
            results[check_date] = raw
        except Exception as e:
            results[check_date] = {"error": str(e)}

    return results
