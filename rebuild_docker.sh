#!/bin/bash
set -e

echo "============================================"
echo "  Rebuilding GLaDOS Docker Images"
echo "============================================"
echo ""

# Docker username
DOCKER_USER="fabbricca"

# Build web frontend
echo "▶ Building web frontend..."
cd web
docker build -t ${DOCKER_USER}/glados-web-frontend:latest .
echo "✓ Web frontend built"
echo ""

# Build websocket bridge
echo "▶ Building websocket bridge..."
cd ../websocket-bridge
docker build -t ${DOCKER_USER}/glados-websocket-bridge:latest .
echo "✓ WebSocket bridge built"
echo ""

cd ..

echo "============================================"
echo "  Build Complete!"
echo "============================================"
echo ""
echo "Images built:"
echo "  - ${DOCKER_USER}/glados-web-frontend:latest"
echo "  - ${DOCKER_USER}/glados-websocket-bridge:latest"
echo ""
echo "Next steps:"
echo "  1. Push images:    docker push ${DOCKER_USER}/glados-web-frontend:latest"
echo "                     docker push ${DOCKER_USER}/glados-websocket-bridge:latest"
echo ""
echo "  2. Restart K8s:    kubectl rollout restart deployment/web-frontend -n glados"
echo "                     kubectl rollout restart deployment/websocket-bridge -n glados"
echo ""
