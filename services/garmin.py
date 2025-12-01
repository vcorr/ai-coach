import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from garminconnect import Garmin

from services.secrets import get_garmin_credentials

logger = logging.getLogger(__name__)

# Default token directory used by garminconnect/garth
TOKEN_DIR = Path.home() / ".garminconnect"


def _humanize_sleep_feedback(feedback: str) -> str | None:
    """Convert Garmin's sleep feedback codes to human-readable text."""
    if not feedback:
        return None
    
    # Map known feedback codes to readable descriptions
    feedback_map = {
        "POSITIVE_LONG_AND_DEEP": "Long sleep with good deep sleep",
        "POSITIVE_SHORT_BUT_DEEP": "Short but restorative with good deep sleep",
        "POSITIVE_OVERALL_GOOD": "Good overall sleep quality",
        "NEGATIVE_LONG_BUT_NOT_ENOUGH_REM": "Long sleep but not enough REM",
        "NEGATIVE_LONG_BUT_NOT_ENOUGH_DEEP": "Long sleep but not enough deep sleep",
        "NEGATIVE_SHORT_AND_LIGHT": "Short and light sleep",
        "NEGATIVE_TOO_MUCH_AWAKE": "Too much time awake during the night",
        "NEGATIVE_RESTLESS": "Restless sleep",
    }
    
    if feedback in feedback_map:
        return feedback_map[feedback]
    
    # Fallback: convert SCREAMING_SNAKE_CASE to readable text
    return feedback.replace("_", " ").lower().capitalize()


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
        
        Returns structured data optimized for LLM understanding:
        - body: Core physiological metrics (resting HR, body battery, stress)
        - sleep: Sleep quality and stage breakdown
        - recovery: Training readiness and recovery time
        """
        if not self.client:
            return {"error": "Not logged in"}

        today = date.today().isoformat()
        stats: dict[str, Any] = {"date": today}

        # === BODY: Physiological metrics from user summary ===
        try:
            summary = self.client.get_user_summary(today)
            if summary:
                stats["body"] = {
                    "resting_hr": summary.get("restingHeartRate"),
                    "resting_hr_7day_avg": summary.get("lastSevenDaysAvgRestingHeartRate"),
                    "body_battery": {
                        "current": summary.get("bodyBatteryMostRecentValue"),
                        "charged": summary.get("bodyBatteryChargedValue"),
                        "drained": summary.get("bodyBatteryDrainedValue"),
                        "high": summary.get("bodyBatteryHighestValue"),
                        "low": summary.get("bodyBatteryLowestValue"),
                    },
                    "stress": {
                        "avg": summary.get("averageStressLevel"),
                        "max": summary.get("maxStressLevel"),
                        "high_duration_seconds": summary.get("highStressDuration"),
                    },
                }
        except Exception as e:
            logger.warning(f"Failed to get user summary: {e}")
            stats["body"] = None

        # === SLEEP: Look back up to 7 days to find most recent ===
        try:
            stats["sleep"] = None
            
            for days_ago in range(7):
                check_date = (date.today() - timedelta(days=days_ago)).isoformat()
                sleep_data = self.client.get_sleep_data(check_date)
                if sleep_data:
                    daily_sleep = sleep_data.get("dailySleepDTO") or {}
                    sleep_seconds = daily_sleep.get("sleepTimeSeconds")
                    if sleep_seconds and sleep_seconds > 0:
                        scores = daily_sleep.get("sleepScores") or {}
                        raw_feedback = daily_sleep.get("sleepScoreFeedback") or ""
                        
                        stats["sleep"] = {
                            "date": check_date,
                            "score": scores.get("overall", {}).get("value"),
                            "quality": scores.get("overall", {}).get("qualifierKey"),
                            "duration_hours": round(sleep_seconds / 3600, 1),
                            "feedback": _humanize_sleep_feedback(raw_feedback),
                            "stages": {
                                "deep": {
                                    "pct": round((daily_sleep.get("deepSleepSeconds") or 0) / sleep_seconds * 100),
                                    "quality": scores.get("deepPercentage", {}).get("qualifierKey"),
                                },
                                "light": {
                                    "pct": round((daily_sleep.get("lightSleepSeconds") or 0) / sleep_seconds * 100),
                                    "quality": scores.get("lightPercentage", {}).get("qualifierKey"),
                                },
                                "rem": {
                                    "pct": round((daily_sleep.get("remSleepSeconds") or 0) / sleep_seconds * 100),
                                    "quality": scores.get("remPercentage", {}).get("qualifierKey"),
                                },
                                "awake": {
                                    "pct": round((daily_sleep.get("awakeSleepSeconds") or 0) / sleep_seconds * 100),
                                    "quality": scores.get("awakeCount", {}).get("qualifierKey"),
                                },
                            },
                        }
                        break
        except Exception as e:
            logger.warning(f"Failed to get sleep data: {e}")
            stats["sleep"] = None

        # === RECOVERY: Training readiness and recovery metrics ===
        try:
            stats["recovery"] = None
            tr_data = self.client.get_training_readiness(today)
            if tr_data and len(tr_data) > 0:
                # Get the most recent reading (first item is usually most recent)
                latest = tr_data[0] if isinstance(tr_data, list) else tr_data
                recovery_minutes = latest.get("recoveryTime") or 0
                stats["recovery"] = {
                    "score": latest.get("score"),
                    "level": latest.get("level"),
                    "feedback": latest.get("feedbackShort"),
                    "recovery_time_hours": round(recovery_minutes / 60, 1) if recovery_minutes else None,
                    "hrv_weekly_avg": latest.get("hrvWeeklyAverage"),
                    "factors": {
                        "sleep": latest.get("sleepScoreFactorFeedback"),
                        "recovery_time": latest.get("recoveryTimeFactorFeedback"),
                        "training_load": latest.get("acwrFactorFeedback"),
                    },
                }
        except Exception as e:
            logger.warning(f"Failed to get training readiness: {e}")
            stats["recovery"] = None

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

