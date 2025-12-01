#!/bin/bash
set -euo pipefail

# Setup Workload Identity Federation for GitHub Actions -> Cloud Run deployment
# Run this once to configure GCP for keyless GitHub Actions authentication

PROJECT_ID="${PROJECT_ID:-meal-app-6f9e5}"
REGION="${REGION:-europe-north1}"
GITHUB_REPO="${1:-}"  # Format: owner/repo (e.g., vcorr/ai-coach)

if [[ -z "$GITHUB_REPO" ]]; then
    echo "Usage: $0 <owner/repo>"
    echo "Example: $0 vcorr/ai-coach"
    exit 1
fi

# Strip https://github.com/ if provided
GITHUB_REPO="${GITHUB_REPO#https://github.com/}"
GITHUB_REPO="${GITHUB_REPO%.git}"

# Verify gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1 | grep -q .; then
    echo "ERROR: Not authenticated with gcloud. Run: gcloud auth login"
    exit 1
fi

# Verify project exists and is accessible
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    echo "ERROR: Cannot access project '$PROJECT_ID'"
    echo "Make sure you're authenticated: gcloud auth login"
    echo "And the project exists: gcloud projects list"
    exit 1
fi

echo "=== Setting up Workload Identity Federation ==="
echo "Project: $PROJECT_ID"
echo "GitHub Repo: $GITHUB_REPO"
echo ""

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable iamcredentials.googleapis.com --project="$PROJECT_ID"
gcloud services enable run.googleapis.com --project="$PROJECT_ID"
gcloud services enable artifactregistry.googleapis.com --project="$PROJECT_ID"

# Create Workload Identity Pool (if not exists)
POOL_NAME="github-pool"
echo "Creating Workload Identity Pool..."
gcloud iam workload-identity-pools create "$POOL_NAME" \
    --project="$PROJECT_ID" \
    --location="global" \
    --display-name="GitHub Actions Pool" \
    2>/dev/null || echo "Pool already exists, continuing..."

# Create Workload Identity Provider
PROVIDER_NAME="github-provider"
echo "Creating Workload Identity Provider..."
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_NAME" \
    --project="$PROJECT_ID" \
    --location="global" \
    --workload-identity-pool="$POOL_NAME" \
    --display-name="GitHub Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    2>/dev/null || echo "Provider already exists, continuing..."

# Create Service Account for GitHub Actions
SA_NAME="github-actions-deploy"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "Creating Service Account..."
gcloud iam service-accounts create "$SA_NAME" \
    --project="$PROJECT_ID" \
    --display-name="GitHub Actions Deploy" \
    2>/dev/null || echo "Service account already exists, continuing..."

# Grant necessary roles to the service account
echo "Granting roles to service account..."

# Cloud Run Admin (to deploy)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/run.admin" \
    --condition=None \
    --quiet

# Artifact Registry Writer (to push images)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/artifactregistry.writer" \
    --condition=None \
    --quiet

# Service Account User (to act as the Cloud Run service account)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/iam.serviceAccountUser" \
    --condition=None \
    --quiet

# Allow GitHub Actions to impersonate this service account
echo "Configuring Workload Identity binding..."
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --project="$PROJECT_ID" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')/locations/global/workloadIdentityPools/$POOL_NAME/attribute.repository/$GITHUB_REPO"

# Get the values needed for GitHub secrets
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/providers/${PROVIDER_NAME}"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Add these secrets to your GitHub repository:"
echo "  Settings -> Secrets and variables -> Actions -> New repository secret"
echo ""
echo "  WIF_PROVIDER:"
echo "    $WIF_PROVIDER"
echo ""
echo "  WIF_SERVICE_ACCOUNT:"
echo "    $SA_EMAIL"
echo ""
echo "After adding secrets, push to main branch to trigger deployment!"

