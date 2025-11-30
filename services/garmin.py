import os
import logging
from pathlib import Path

from garminconnect import Garmin

logger = logging.getLogger(__name__)

# Default token directory used by garminconnect/garth
TOKEN_DIR = Path.home() / ".garminconnect"


class GarminService:
    """Service for interacting with Garmin Connect API."""

    def __init__(self):
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
        """
        email = email or os.getenv("GARMIN_EMAIL")
        password = password or os.getenv("GARMIN_PASSWORD")

        self.client = Garmin()

        # Try to resume from stored tokens first
        if TOKEN_DIR.exists():
            try:
                self.client.login(tokenstore=str(TOKEN_DIR))
                logger.info("Resumed session from stored tokens")
                return True
            except Exception as e:
                logger.warning(f"Could not resume session: {e}")

        # Fall back to fresh login
        if not email or not password:
            logger.error("No credentials provided and no valid stored session")
            return False

        try:
            self.client = Garmin(email, password)
            self.client.login()
            # Save tokens for future use
            self.client.garth.dump(str(TOKEN_DIR))
            logger.info("Fresh login successful, tokens saved")
            return True
        except Exception as e:
            logger.error(f"Login failed: {e}")
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


# Singleton instance for the app
garmin_service = GarminService()

