import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from garminconnect import Garmin

from services.secrets import get_garmin_credentials

logger = logging.getLogger(__name__)

# Default token directory used by garminconnect/garth
TOKEN_DIR = Path.home() / ".garminconnect"


class GarminService:
    """Service for interacting with Garmin Connect API."""

    def __init__(self) -> None:
        self.client: Garmin | None = None

    def login(self, email: str | None = None, password: str | None = None) -> bool:
        """
        Authenticate with Garmin Connect.
        
        First tries to resume session from stored tokens.
        Falls back to fresh login with credentials if needed.
        
        Args:
            email: Garmin account email (defaults to GARMIN_EMAIL env var)
            password: Garmin account password (defaults to GARMIN_PASSWORD env var)
        
        Returns:
            True if login successful, False otherwise.
            
        Invariant:
            If this returns True, self.client is guaranteed to be a valid, 
            authenticated Garmin instance. If False, self.client is None.
        """
        # Get credentials from secrets (Secret Manager or env vars)
        if not email or not password:
            secret_email, secret_password = get_garmin_credentials()
            email = email or secret_email
            password = password or secret_password

        # Try to resume from stored tokens first
        if TOKEN_DIR.exists():
            try:
                client = Garmin()
                client.login(tokenstore=str(TOKEN_DIR))
                self.client = client
                logger.info("Resumed session from stored tokens")
                return True
            except Exception as e:
                logger.warning(f"Could not resume session: {e}")

        # Fall back to fresh login
        if not email or not password:
            logger.error("No credentials provided and no valid stored session")
            self.client = None
            return False

        try:
            client = Garmin(email, password)
            client.login()
            # Save tokens for future use
            try:
                TOKEN_DIR.mkdir(parents=True, exist_ok=True)
                client.garth.dump(str(TOKEN_DIR))
            except OSError as e:
                logger.warning(f"Could not persist tokens (non-fatal): {e}")
            self.client = client
            logger.info("Fresh login successful")
            return True
        except Exception as e:
            logger.error(f"Login failed: {e}")
            self.client = None
            return False

    def get_display_name(self) -> str | None:
        """Get the user's display name to verify login worked."""
        if not self.client:
            return None
        try:
            return self.client.get_full_name()
        except Exception as e:
            logger.error(f"Failed to get display name: {e}")
            return None

    def get_today_stats(self) -> dict[str, Any]:
        """
        Get today's key health metrics for coaching decisions.
        
        Returns:
            Dict with body_battery, sleep_score, hrv_status, training_readiness
        """
        if not self.client:
            return {"error": "Not logged in"}

        today = date.today().isoformat()
        stats: dict[str, Any] = {"date": today}

        # Body Battery
        try:
            bb_data = self.client.get_body_battery(today)
            if bb_data and len(bb_data) > 0:
                # Get the most recent reading
                latest = bb_data[-1] if isinstance(bb_data, list) else bb_data
                stats["body_battery"] = latest.get("bodyBatteryLevel") or latest.get("charged")
        except Exception as e:
            logger.warning(f"Failed to get body battery: {e}")
            stats["body_battery"] = None

        # Sleep Score - look back up to 7 days to find most recent
        try:
            stats["sleep_score"] = None
            stats["sleep_hours"] = None
            stats["sleep_date"] = None
            
            for days_ago in range(7):
                check_date = (date.today() - timedelta(days=days_ago)).isoformat()
                sleep_data = self.client.get_sleep_data(check_date)
                if sleep_data:
                    daily_sleep = sleep_data.get("dailySleepDTO") or {}
                    sleep_seconds = daily_sleep.get("sleepTimeSeconds")
                    if sleep_seconds and sleep_seconds > 0:
                        stats["sleep_score"] = daily_sleep.get("sleepScores", {}).get("overall", {}).get("value")
                        stats["sleep_hours"] = round(sleep_seconds / 3600, 1)
                        stats["sleep_date"] = check_date
                        # Sleep stage percentages
                        deep = daily_sleep.get("deepSleepSeconds") or 0
                        light = daily_sleep.get("lightSleepSeconds") or 0
                        rem = daily_sleep.get("remSleepSeconds") or 0
                        awake = daily_sleep.get("awakeSleepSeconds") or 0
                        stats["deep_sleep_pct"] = round(deep / sleep_seconds * 100)
                        stats["light_sleep_pct"] = round(light / sleep_seconds * 100)
                        stats["rem_sleep_pct"] = round(rem / sleep_seconds * 100)
                        stats["awake_pct"] = round(awake / sleep_seconds * 100)
                        break
        except Exception as e:
            logger.warning(f"Failed to get sleep data: {e}")
            stats["sleep_score"] = None
            stats["sleep_hours"] = None

        # HRV Status
        try:
            hrv_data = self.client.get_hrv_data(today)
            if hrv_data:
                stats["hrv_status"] = hrv_data.get("hrvSummary", {}).get("status")
                stats["hrv_value"] = hrv_data.get("hrvSummary", {}).get("lastNightAvg")
        except Exception as e:
            logger.warning(f"Failed to get HRV data: {e}")
            stats["hrv_status"] = None
            stats["hrv_value"] = None

        # Training Readiness
        try:
            stats["training_readiness"] = None
            stats["training_readiness_level"] = None
            tr_data = self.client.get_training_readiness(today)
            if tr_data and len(tr_data) > 0:
                latest = tr_data[-1] if isinstance(tr_data, list) else tr_data
                stats["training_readiness"] = latest.get("score")
                stats["training_readiness_level"] = latest.get("level")
        except Exception as e:
            logger.warning(f"Failed to get training readiness: {e}")

        return stats

    def get_recent_activities(self, days: int = 7) -> list[dict[str, Any]]:
        """
        Get recent activities to determine gym/run balance.
        
        Args:
            days: Number of days to look back (default 7)
        
        Returns:
            List of simplified activity records with type, date, and duration
        """
        if not self.client:
            return []

        try:
            # Fetch activities (the API returns most recent first)
            activities = self.client.get_activities(0, days * 2)  # Fetch extra to ensure coverage
            
            cutoff = date.today() - timedelta(days=days - 1)
            recent = []
            
            for act in activities:
                # Parse activity date
                start_time = act.get("startTimeLocal", "")
                if start_time:
                    act_date = start_time.split("T")[0]
                    if act_date >= cutoff.isoformat():
                        recent.append({
                            "date": act_date,
                            "type": act.get("activityType", {}).get("typeKey", "unknown"),
                            "name": act.get("activityName", ""),
                            "duration_minutes": round(act.get("duration", 0) / 60, 1),
                        })
            
            return recent
        except Exception as e:
            logger.error(f"Failed to get activities: {e}")
            return []


# Singleton instance for the app
garmin_service = GarminService()

