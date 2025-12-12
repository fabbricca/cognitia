# Cognitia v3.0 - Multi-Character AI Chat Platform

## Overview

A production-ready AI voice/text chat platform with:
- Multi-user authentication (email/password)
- Multi-character support (custom personas + RVC voice models)
- Three interaction modes: Text, Voice Messages, Real-time Calls
- Web Interface (retro/hacker aesthetic)
- TUI Interface (simple 50-message log)

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL ACCESS                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│    User Request (ai.iberu.me)                                                   │
│              │                                                                   │
│              ▼                                                                   │
│    ┌─────────────────┐                                                          │
│    │   Cloudflare    │  DNS (non-proxied, points to Oracle VM)                 │
│    └────────┬────────┘                                                          │
│              │                                                                   │
│              ▼                                                                   │
│    ┌─────────────────┐                                                          │
│    │   Oracle VM     │  Pangolin reverse proxy + auth                          │
│    │   (Pangolin)    │                                                          │
│    └────────┬────────┘                                                          │
│              │ WireGuard Tunnel                                                 │
│              ▼                                                                   │
│    ┌─────────────────┐                                                          │
│    │  Home Network   │                                                          │
│    │    (10.0.0.x)   │                                                          │
│    └────────┬────────┘                                                          │
│              │                                                                   │
└──────────────┼──────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         KUBERNETES CLUSTER (k8s-hs)                             │
│                         Nodes: 10.0.0.11, 10.0.0.12                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│    ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐       │
│    │  ingress-nginx  │ ──►  │   glados-api    │ ──►  │  glados-bridge  │       │
│    │   (LoadBalancer)│      │  (FastAPI REST) │      │   (WebSocket)   │       │
│    └─────────────────┘      └────────┬────────┘      └────────┬────────┘       │
│           :443                       │                        │                 │
│                              ┌───────┴───────┐                │                 │
│                              │   PostgreSQL  │                │                 │
│                              │   (Database)  │                │                 │
│                              └───────────────┘                │                 │
│                                                               │                 │
│    Namespace: glados                                          │                 │
│    Secrets: JWT secret, DB credentials, encrypted via SOPS   │                 │
│                                                               │                 │
└───────────────────────────────────────────────────────────────┼─────────────────┘
                                                                │
                                     TCP Connection (Binary Protocol)
                                                                │
                                                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           GPU SERVER (10.0.0.15)                                 │
│                           RTX 3090, 64GB RAM                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│    ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐       │
│    │  Cognitia Engine  │ ◄──► │   Ollama LLM    │      │   RVC Service   │       │
│    │   (TCP:5555)    │      │   (API:11434)   │      │   (API:5050)    │       │
│    └────────┬────────┘      └─────────────────┘      └─────────────────┘       │
│             │                                                                    │
│    ┌────────┴────────────────────────────────────────────────────────┐          │
│    │                         Components                               │          │
│    ├──────────────────────────────────────────────────────────────────┤          │
│    │  • ASR (Parakeet TDT) - Speech to Text                          │          │
│    │  • TTS (Kokoro)       - Text to Speech                          │          │
│    │  • VAD (Silero)       - Voice Activity Detection                │          │
│    │  • RVC                - Voice Cloning                           │          │
│    │  • LLM                - Language Model (Hermes-4)               │          │
│    └─────────────────────────────────────────────────────────────────┘          │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. glados-api (FastAPI REST API)

Runs in K8s, handles:
- **User Management**: Registration, login, JWT tokens
- **Character Management**: Create/edit characters, upload RVC models
- **Chat Sessions**: CRUD for conversations per character
- **Static Files**: Serve web frontend

```
/api/v1/
├── auth/
│   ├── POST /register      - Create new account
│   ├── POST /login         - Get JWT token
│   ├── POST /refresh       - Refresh token
│   └── GET  /me            - Current user info
├── characters/
│   ├── GET  /              - List user's characters
│   ├── POST /              - Create character
│   ├── GET  /{id}          - Get character details
│   ├── PUT  /{id}          - Update character
│   ├── DELETE /{id}        - Delete character
│   └── POST /{id}/voice    - Upload RVC model (.pth + .index)
├── chats/
│   ├── GET  /              - List chats for character
│   ├── POST /              - Create new chat
│   ├── GET  /{id}/messages - Get chat history
│   └── DELETE /{id}        - Delete chat
└── health/
    └── GET  /              - Health check
```

### 2. glados-bridge (WebSocket Bridge)

Runs in K8s, handles real-time communication:
- WebSocket connections from browsers
- TCP connection to GPU backend
- Protocol translation (JSON ↔ Binary)
- Session management
- Audio streaming (bidirectional)

**WebSocket Protocol:**
```
// Client → Bridge
{ type: "auth", token: "jwt..." }
{ type: "text", chatId: "...", message: "Hello" }
{ type: "audio", chatId: "...", format: "pcm", data: "base64..." }
{ type: "call_start", chatId: "..." }
{ type: "call_end" }

// Bridge → Client
{ type: "auth_ok", userId: "...", username: "..." }
{ type: "text", message: "Response...", isAudio: false }
{ type: "audio", format: "wav", data: "base64..." }
{ type: "call_audio", data: "base64..." }
{ type: "error", message: "..." }
```

### 3. Cognitia Engine (GPU Backend)

Python application on GPU server:
- Listens on TCP:5555
- Handles binary protocol from bridge
- Processes: ASR → LLM → TTS → RVC
- Streams audio responses
- Loads character configs dynamically

**Binary Protocol (unchanged):**
```
Header: [marker:4 bytes][length:4 bytes]
Markers:
  0xFFFFFFFF - TEXT_FROM_CLIENT
  0xFFFFFFFE - TEXT_TO_CLIENT  
  0xFFFFFFF9 - AUDIO_FROM_CLIENT
  0xFFFFFFF8 - AUDIO_TO_CLIENT
  0xFFFFFFF7 - CHARACTER_SWITCH
  0xFFFFFFF6 - CALL_MODE_START
  0xFFFFFFF5 - CALL_MODE_END
```

### 4. PostgreSQL Database

Schema:
```sql
-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Characters (per user)
CREATE TABLE characters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    system_prompt TEXT NOT NULL,
    voice_model VARCHAR(100) DEFAULT 'af_bella',
    rvc_model_path VARCHAR(255),
    rvc_index_path VARCHAR(255),
    avatar_url VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Chats (per character)
CREATE TABLE chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    character_id UUID REFERENCES characters(id) ON DELETE CASCADE,
    title VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Messages
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID REFERENCES chats(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- 'user' or 'assistant'
    content TEXT NOT NULL,
    audio_url VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Web Frontend

### Design: Retro/Hacker Aesthetic
- Dark theme with green/cyan accents (Matrix-style)
- Monospace fonts (JetBrains Mono, Fira Code)
- CRT scanline effects (subtle)
- Terminal-like message bubbles
- Glitch effects on transitions

### Layout
```
┌────────────────────────────────────────────────────────────────────┐
│  ╔══════════════════════════════════════════════════════════════╗  │
│  ║  GLADOS v3.0 ████████████████████████████  [user@system] ▓▓  ║  │
│  ╚══════════════════════════════════════════════════════════════╝  │
├──────────────────┬─────────────────────────────────────────────────┤
│  CHARACTERS      │  CHAT: Cognitia                          [📞]  │
│ ┌──────────────┐ │ ┌─────────────────────────────────────────────┐ │
│ │ > Cognitia   │ │ │ [12:34] USER                               │ │
│ │   Cognitia     │ │ │ > Hello there                              │ │
│ │   Custom AI  │ │ │                                            │ │
│ │              │ │ │ [12:34] COURTNEY                           │ │
│ │  [+ NEW]     │ │ │ > What do you want? I'm busy.              │ │
│ └──────────────┘ │ │                                    [▶ PLAY]│ │
│                  │ │                                            │ │
│                  │ │                                            │ │
│                  │ │                                            │ │
│                  │ └─────────────────────────────────────────────┘ │
│                  │ ┌─────────────────────────────────────────────┐ │
│                  │ │ [📎] [🎤 HOLD]    Type message...    [SEND]│ │
│                  │ └─────────────────────────────────────────────┘ │
└──────────────────┴─────────────────────────────────────────────────┘
```

### Interaction Modes
1. **Text**: Type and send, receive text (+ audio if response is long)
2. **Voice Message**: Hold mic button, record, release to send
3. **Phone Call**: Click call button, real-time bidirectional audio

## TUI Interface

Simple terminal interface:
- Connects via WebSocket to bridge
- Shows last 50 messages (no scroll-back)
- Text input at bottom
- Audio output via system speakers

```
┌─ Cognitia TUI ────────────────────────────────────────────────────────┐
│ [12:30:15] USER: Hey Cognitia                                       │
│ [12:30:18] COURTNEY: What do you want?                              │
│ [12:30:25] USER: I need help with something                         │
│ [12:30:28] COURTNEY: Spill it. I don't have all day.               │
│                                                                      │
│                                                                      │
│                                                                      │
│ ─────────────────────────────────────────────────────────────────── │
│ > Type your message here...                                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Deployment Structure (homeserver repo)

```
cluster/
└── glados/
    ├── kustomization.yaml
    ├── namespace.yaml
    ├── api/
    │   ├── deployment.yaml
    │   ├── service.yaml
    │   └── configmap.yaml
    ├── bridge/
    │   ├── deployment.yaml
    │   └── service.yaml
    ├── database/
    │   ├── statefulset.yaml
    │   ├── service.yaml
    │   └── pvc.yaml
    ├── ingress.yaml
    └── secrets.yaml (SOPS encrypted)
```

## Development Phases

### Phase 1: Core Infrastructure
- [ ] Clean up old code (archive web/, websocket-bridge/, auth/, etc.)
- [ ] Create new FastAPI project structure
- [ ] Set up PostgreSQL schema
- [ ] Implement user auth (register/login/JWT)

### Phase 2: Character System
- [ ] Character CRUD API
- [ ] RVC model upload/storage
- [ ] Dynamic character loading in engine

### Phase 3: Communication
- [ ] New WebSocket bridge
- [ ] Protocol for character switching
- [ ] Text/audio message handling

### Phase 4: Web Frontend
- [ ] Retro UI design
- [ ] Auth pages (login/register)
- [ ] Chat interface
- [ ] Audio recording/playback
- [ ] Phone call mode

### Phase 5: TUI
- [ ] Simple curses-based TUI
- [ ] WebSocket connection
- [ ] 50-message buffer

### Phase 6: K8s Deployment
- [ ] Create Flux manifests
- [ ] Configure ingress
- [ ] Set up secrets
- [ ] Deploy and test

## File Structure (New)

```
/home/iberu/Documents/Cognitia/
├── ARCHITECTURE.md          # This file
├── pyproject.toml          # Updated dependencies
├── configs/                # Engine configs
├── models/                 # AI models (ASR, TTS)
├── rvc_models/             # RVC voice models
├── data/                   # Uploaded user data
│   └── rvc/               # User-uploaded RVC models
├── src/
│   └── glados/
│       ├── __init__.py
│       ├── ASR/           # Keep - Speech recognition
│       ├── TTS/           # Keep - Text to speech
│       ├── Vision/        # Keep - Vision (optional)
│       ├── audio_io/      # Keep - Audio I/O backends
│       ├── core/          # Keep - Engine core
│       ├── memory/        # Keep - Conversation memory
│       ├── utils/         # Keep - Utilities
│       ├── api/           # NEW - FastAPI REST API
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── auth.py
│       │   ├── characters.py
│       │   ├── chats.py
│       │   ├── models.py
│       │   └── database.py
│       ├── bridge/        # NEW - WebSocket bridge
│       │   ├── __init__.py
│       │   ├── server.py
│       │   ├── protocol.py
│       │   └── session.py
│       └── tui/           # NEW - Simple TUI
│           ├── __init__.py
│           └── app.py
├── web/                   # NEW - Web frontend (rebuilt)
│   ├── index.html
│   ├── login.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js
│       ├── websocket.js
│       ├── audio.js
│       └── auth.js
├── k8s/                   # NEW - Kubernetes manifests
│   ├── api/
│   ├── bridge/
│   ├── database/
│   ├── ingress.yaml
│   └── kustomization.yaml
└── archived/              # Old code moved here
    ├── old-web/
    ├── old-websocket-bridge/
    ├── old-auth/
    └── old-network/
```

## Security Considerations

1. **JWT Tokens**: HS256, 1-hour access, 30-day refresh
2. **Passwords**: bcrypt hashing
3. **HTTPS**: TLS via cert-manager wildcard
4. **CORS**: Strict origin checking
5. **File Uploads**: Size limits, type validation for RVC models
6. **Rate Limiting**: Per-user request limits

## Performance Notes

- **VRAM Budget**: ~10GB for LLM, ~1GB for ASR, ~0.5GB for TTS, ~1GB for RVC
- If needed, switch to smaller LLM (e.g., Hermes-2-Pro-7B)
- Audio chunks: 32ms for real-time, batch for messages
- WebSocket: Binary frames for audio, JSON for control
