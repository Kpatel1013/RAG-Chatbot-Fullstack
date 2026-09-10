#!/usr/bin/env bash

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
STACK="RagChatbotStack"

get_output() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

BACKEND_REPO="$(get_output BackendRepoUri)"
FRONTEND_REPO="$(get_output FrontendRepoUri)"

echo "Logging in to ECR..."
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

echo "Building and pushing backend..."
docker build -t "$BACKEND_REPO:latest" "$ROOT/backend" && docker push "$BACKEND_REPO:latest"

echo "Building and pushing frontend..."
docker build --build-arg VITE_API_URL= -t "$FRONTEND_REPO:latest" "$ROOT/frontend" && docker push "$FRONTEND_REPO:latest"

CLUSTER="$(get_output ClusterName)"
aws ecs update-service --cluster "$CLUSTER" --service "$(get_output BackendServiceName)" --force-new-deployment --region "$REGION" >/dev/null
aws ecs update-service --cluster "$CLUSTER" --service "$(get_output FrontendServiceName)" --force-new-deployment --region "$REGION" >/dev/null

echo "Done → $(get_output AppUrl)"
