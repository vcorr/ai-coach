"""
Secret Manager integration for secure credential storage.

In Cloud Run: fetches secrets from Google Secret Manager.
Locally: falls back to environment variables.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Cache for secrets to avoid repeated API calls
_secret_cache: dict[str, str] = {}
_project_id_cache: str | None = None


def _get_project_from_metadata() -> str | None:
    """Get project ID from GCP metadata server (works in Cloud Run)."""
    global _project_id_cache
    if _project_id_cache:
        return _project_id_cache
    
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"}
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            _project_id_cache = response.read().decode("utf-8")
            return _project_id_cache
    except Exception:
        return None


def get_secret(secret_id: str, env_fallback: str | None = None) -> str | None:
    """
    Get a secret value, with automatic fallback for local development.
    
    Args:
        secret_id: The Secret Manager secret ID (e.g., "garmin-email")
        env_fallback: Environment variable name to use as fallback
        
    Returns:
        The secret value, or None if not found.
        
    Priority:
        1. Environment variable (if env_fallback provided and set)
        2. Google Secret Manager (if running in GCP)
        3. None
    """
    # Check cache first
    if secret_id in _secret_cache:
        return _secret_cache[secret_id]
    
    # Try environment variable first (for local dev)
    if env_fallback:
        env_value = os.getenv(env_fallback)
        if env_value:
            logger.debug(f"Using env var {env_fallback} for secret {secret_id}")
            return env_value
    
    # Try Secret Manager (for Cloud Run)
    try:
        from google.cloud import secretmanager
        
        # Get project ID - try env vars first, then metadata server
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        if not project_id:
            project_id = _get_project_from_metadata()
        if not project_id:
            logger.warning("No GCP project ID found, skipping Secret Manager")
            return None
        
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        
        # Cache the value
        _secret_cache[secret_id] = secret_value
        logger.info(f"Loaded secret {secret_id} from Secret Manager")
        return secret_value
        
    except Exception as e:
        logger.warning(f"Could not fetch secret {secret_id} from Secret Manager: {e}")
        return None


def get_garmin_credentials() -> tuple[str | None, str | None]:
    """
    Get Garmin credentials from secrets or environment.
    
    Returns:
        Tuple of (email, password), either may be None if not found.
    """
    email = get_secret("garmin-email", env_fallback="GARMIN_EMAIL")
    password = get_secret("garmin-password", env_fallback="GARMIN_PASSWORD")
    return email, password

