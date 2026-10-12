#!/bin/bash
# Deploy Phase 3 agent to Google Cloud Run

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}[DEPLOY] GitHub Issue Triage Agent — Phase 3${NC}"
echo ""

# Check prerequisites
echo -e "${YELLOW}[CHECK] Prerequisites...${NC}"
command -v gcloud &> /dev/null || { echo "gcloud CLI not found. Install from: https://cloud.google.com/sdk/docs/install"; exit 1; }
echo -e "${GREEN}[OK] gcloud CLI found${NC}"

# Get project ID
PROJECT_ID=$(gcloud config get-value project)
echo -e "${GREEN}[OK] Project ID: $PROJECT_ID${NC}"

# Get service name from user or use default
SERVICE_NAME="${1:-github-triage-agent}"
echo -e "${YELLOW}[INFO] Service name: $SERVICE_NAME${NC}"

# Check .env file
if [ ! -f .env ]; then
    echo -e "${YELLOW}[ERROR] .env file not found. Create it first.${NC}"
    exit 1
fi

# Load environment variables
source .env

# Check required variables
if [ -z "$ANTHROPIC_API_KEY" ] || [ -z "$GITHUB_TOKEN" ] || [ -z "$GITHUB_REPO" ]; then
    echo -e "${YELLOW}[ERROR] Missing required environment variables in .env${NC}"
    echo "Required: ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_REPO"
    exit 1
fi

echo -e "${GREEN}[OK] Environment variables loaded${NC}"
echo ""

# Update app.yaml with environment variables
echo -e "${YELLOW}[UPDATE] Updating app.yaml with secrets...${NC}"
cat > app.yaml << EOF
runtime: python312

env_variables:
  ANTHROPIC_API_KEY: "$ANTHROPIC_API_KEY"
  GITHUB_TOKEN: "$GITHUB_TOKEN"
  GITHUB_REPO: "$GITHUB_REPO"
  LANGFUSE_PUBLIC_KEY: "${LANGFUSE_PUBLIC_KEY:- }"
  LANGFUSE_SECRET_KEY: "${LANGFUSE_SECRET_KEY:- }"
  LANGFUSE_HOST: "${LANGFUSE_HOST:- }"

entrypoint: gunicorn -b :$PORT main:app

health_checks:
  - path: /health
EOF
echo -e "${GREEN}[OK] app.yaml updated${NC}"
echo ""

# Deploy to Cloud Run
echo -e "${YELLOW}[DEPLOY] Deploying to Cloud Run...${NC}"
gcloud run deploy $SERVICE_NAME \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY,GITHUB_TOKEN=$GITHUB_TOKEN,GITHUB_REPO=$GITHUB_REPO" \
  --memory 512Mi \
  --timeout 300 \
  --max-instances 10

echo ""
echo -e "${GREEN}[SUCCESS] Deployment complete!${NC}"
echo ""

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --platform managed --region us-central1 --format 'value(status.url)')
echo -e "${GREEN}[URL] Service deployed at: $SERVICE_URL${NC}"
echo ""

# Test health endpoint
echo -e "${YELLOW}[TEST] Testing /health endpoint...${NC}"
curl -s "$SERVICE_URL/health" | python -m json.tool
echo ""

echo -e "${GREEN}[NEXT] Try these endpoints:${NC}"
echo "  GET  $SERVICE_URL/"
echo "  POST $SERVICE_URL/triage (with body: {\"limit\": 5})"
echo "  GET  $SERVICE_URL/approvals"
echo "  POST $SERVICE_URL/status"