"""
Cognitia Entrance - K8s Authentication Proxy

This is the frontend-facing service that runs in Kubernetes and handles:
- User authentication (JWT)
- Character/Chat CRUD (PostgreSQL)
- WebSocket proxy to GPU Core (all requests are pre-authenticated)
- Static file serving for Web UI

The entrance does NOT do any AI processing - it just authenticates and proxies.
"""
