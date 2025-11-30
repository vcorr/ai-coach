import logging

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
async def root():
    return {"message": "AI Coach is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# === Debug endpoints (Phase 2.1) ===


@app.get("/debug/garmin-login")
async def debug_garmin_login():
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
