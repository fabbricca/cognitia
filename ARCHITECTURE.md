# Cognitia v3.0 - Architecture

## Overview

Cognitia is a multi-character AI voice assistant platform with:
- Multi-user authentication (email/password + JWT)
- Multi-character support (custom personas, voice models, RVC cloning)
- Three interaction modes: Text, Voice Messages, Real-time Calls
- Web Interface with retro/hacker aesthetic

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL ACCESS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│    User Request (cognitia.iberu.me)                                          │
│              │                                                               │
│              ▼                                                               │
│    ┌─────────────────┐                                                       │
│    │   Cloudflare    │  DNS (non-proxied, points to Oracle VM)              │
│    └────────┬────────┘                                                       │
│              │                                                               │
│              ▼                                                               │
│    ┌─────────────────┐                                                       │
│    │   Oracle VM     │  Pangolin reverse proxy                              │
│    │   (Pangolin)    │                                                       │
│    └────────┬────────┘                                                       │
│              │ WireGuard Tunnel                                              │
│              ▼                                                               │
└──────────────┼───────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KUBERNETES CLUSTER (Entrance)                        │
│                         Nodes: 10.0.0.11, 10.0.0.12                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│    ┌─────────────────────────────────────────────────────────────────────┐   │
│    │                    cognitia-entrance (FastAPI)                       │   │
│    │                                                                       │   │
│    │   Responsibilities:                                                   │   │
│    │   • User Authentication (register, login, JWT tokens)                │   │
│    │   • Character CRUD (create, read, update, delete)                    │   │
│    │   • Chat/Message CRUD                                                │   │
│    │   • WebSocket proxy to GPU Core (pre-authenticated)                  │   │
│    │   • Static file serving (Web UI)                                     │   │
│    │                                                                       │   │
│    │   NO AI Processing - just auth and proxy!                            │   │
│    └───────────────────────────────┬─────────────────────────────────────┘   │
│                                    │                                         │
│    ┌───────────────────────────────┴───────────────────────────────────┐     │
│    │                         PostgreSQL                                 │     │
│    │   Tables: users, characters, chats, messages                      │     │
│    └───────────────────────────────────────────────────────────────────┘     │
│                                                                              │
└──────────────────────────────────────────────┬───────────────────────────────┘
                                               │
                           HTTP/WebSocket (trusted, pre-authenticated)
                                               │
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           GPU SERVER (Core)                                  │
│                           10.0.0.15 - RTX 3090, 64GB RAM                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│    ┌─────────────────────────────────────────────────────────────────────┐   │
│    │                    cognitia-core (FastAPI + WebSocket)               │   │
│    │                                                                       │   │
│    │   Orchestrator handles the complete AI pipeline:                     │   │
│    │                                                                       │   │
│    │   1. RECEIVE REQUEST (from K8s Entrance)                             │   │
│    │      └─ Contains: userId, modelId, message, communicationType        │   │
│    │                                                                       │   │
│    │   2. PARALLEL PROCESSING (two threads)                               │   │
│    │      ├─ Thread 1: STT if audio/phone → Parakeet ASR                  │   │
│    │      └─ Thread 2: Fetch context (conversation, personas, entities)   │   │
│    │                                                                       │   │
│    │   3. ENRICH SYSTEM PROMPT                                            │   │
│    │      └─ Inject: conversation summary, entities, user persona         │   │
│    │                                                                       │   │
│    │   4. LLM PROCESSING                                                  │   │
│    │      └─ Stream response from Ollama (Hermes-4-14B)                   │   │
│    │                                                                       │   │
│    │   5. RESPONSE ROUTING                                                │   │
│    │      ├─ Text chat + short response → return text only                │   │
│    │      ├─ Text chat + long response → TTS (Kokoro + optional RVC)      │   │
│    │      └─ Phone call → always TTS                                      │   │
│    │                                                                       │   │
│    │   6. RETURN RESPONSE (to K8s Entrance → Client)                      │   │
│    │      └─ Stream of either text chunks or audio                        │   │
│    └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│    ┌──────────────────────────────────────────────────────────────────────┐  │
│    │                           AI Models                                   │  │
│    ├──────────────────────────────────────────────────────────────────────┤  │
│    │  • ASR: Parakeet TDT/CTC (ONNX) - Speech to Text                    │  │
│    │  • VAD: Silero v5 (ONNX) - Voice Activity Detection                 │  │
│    │  • TTS: Kokoro v1.0 (ONNX) - Text to Speech                         │  │
│    │  • RVC: Voice Cloning Service (Docker) - Voice Conversion           │  │
│    │  • LLM: Ollama → Hermes-4-14B-GGUF                                  │  │
│    └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Request Flow

### Text Message Flow

```
Client                 Entrance (K8s)              Core (GPU)
  │                        │                          │
  │─── WS: auth ──────────>│                          │
  │<── auth_success ───────│                          │
  │                        │                          │
  │─── WS: text msg ──────>│                          │
  │                        │── HTTP: process ────────>│
  │                        │   (userId, modelId,      │
  │                        │    message, history,     │
  │                        │    systemPrompt)         │
  │                        │                          │
  │                        │        ┌─────────────────┤
  │                        │        │ 1. Skip STT     │
  │                        │        │ 2. Fetch context│
  │                        │        │ 3. Enrich prompt│
  │                        │        │ 4. LLM stream   │
  │                        │        │ 5. Route output │
  │                        │        └─────────────────┤
  │                        │                          │
  │                        │<── Stream text chunks ───│
  │<── text_chunk ─────────│                          │
  │<── text_chunk ─────────│                          │
  │<── text_complete ──────│                          │
  │                        │                          │
  │                        │<── (if long) audio ──────│
  │<── audio (optional) ───│                          │
  │                        │                          │
```

### Voice Message Flow

```
Client                 Entrance (K8s)              Core (GPU)
  │                        │                          │
  │─── WS: audio msg ─────>│                          │
  │   (base64 audio)       │                          │
  │                        │── HTTP: process ────────>│
  │                        │   (communicationType:    │
  │                        │    "audio")              │
  │                        │                          │
  │                        │        ┌─────────────────┤
  │                        │        │ Thread 1: STT   │───> Parakeet ASR
  │                        │        │ Thread 2: ctx   │───> DB lookup
  │                        │        │ (parallel)      │
  │                        │        └─────────────────┤
  │                        │                          │
  │                        │<── transcription ────────│
  │<── transcription ──────│                          │
  │                        │                          │
  │                        │<── text_chunk (stream) ──│
  │<── text_chunk ─────────│                          │
  │                        │                          │
  │                        │<── audio response ───────│
  │<── audio ──────────────│   (TTS: Kokoro + RVC)    │
  │                        │                          │
```

## Component Details

### 1. Entrance (K8s) - `cognitia.entrance.server`

Runs in Kubernetes, handles everything except AI processing:

**Endpoints:**
```
/api/auth/
├── POST /register      - Create new account
├── POST /login         - Get JWT tokens
├── POST /refresh       - Refresh access token
└── GET  /me            - Current user info

/api/characters/
├── GET  /              - List user's characters
├── POST /              - Create character
├── GET  /{id}          - Get character
├── PUT  /{id}          - Update character
└── DELETE /{id}        - Delete character

/api/chats/
├── GET  /              - List chats
├── POST /              - Create chat
├── GET  /{id}          - Get chat
└── DELETE /{id}        - Delete chat

/api/chats/{id}/messages/
├── GET  /              - List messages
└── POST /              - Create message

/ws                     - WebSocket (auth required)
/health                 - Health check

/                       - Static files (Web UI)
```

**WebSocket Protocol:**
```json
// Client → Server
{"type": "auth", "token": "jwt..."}
{"type": "text", "chatId": "uuid", "characterId": "uuid", "message": "Hello"}
{"type": "audio", "chatId": "uuid", "characterId": "uuid", "data": "base64..."}
{"type": "character_switch", "characterId": "uuid"}

// Server → Client
{"type": "auth_success", "userId": "uuid"}
{"type": "text_chunk", "content": "partial response..."}
{"type": "text_complete", "content": "full response"}
{"type": "audio", "content": "base64...", "sample_rate": 24000}
{"type": "transcription", "content": "what user said"}
{"type": "error", "message": "error description"}
{"type": "status", "message": "info", "mode": "full|text-only"}
```

### 2. Core (GPU) - `cognitia.core.server`

Runs on the GPU server, handles all AI processing:

**Endpoints:**
```
POST /process           - Process a message (main endpoint)
POST /transcribe        - Transcribe audio (standalone)
POST /synthesize        - Synthesize speech (standalone)
/ws                     - WebSocket for streaming
/health                 - Health check
```

**Processing Request:**
```json
{
  "user_id": "uuid",
  "model_id": "uuid",
  "message": "text or base64 audio",
  "communication_type": "text|audio|phone",
  "system_prompt": "You are...",
  "conversation_history": [{"role": "user", "content": "..."}],
  "voice": "af_bella",
  "rvc_model_path": "/path/to/model.pth",
  "rvc_enabled": false,
  "temperature": 0.8,
  "max_tokens": 2048
}
```

**Processing Response:**
```json
{
  "type": "text|audio",
  "content": "response text or base64 audio",
  "text_content": "always the text version",
  "sample_rate": 24000
}
```

### 3. Orchestrator - `cognitia.core.orchestrator`

The brain of the Core, handles the processing pipeline:

```python
class Orchestrator:
    async def process(request: ProcessingRequest) -> ProcessingResponse:
        # 1. PARALLEL PROCESSING
        with ThreadPoolExecutor:
            stt_future = process_stt_if_needed(message, communication_type)
            ctx_future = fetch_context(user_id, model_id, history)
        
        user_message, context = await gather(stt_future, ctx_future)
        
        # 2. ENRICH SYSTEM PROMPT
        enriched_prompt = enrich_system_prompt(context)
        
        # 3. LLM PROCESSING
        response = await stream_llm_response(messages, enriched_prompt)
        
        # 4. ROUTE OUTPUT
        if communication_type == PHONE or len(response) > THRESHOLD:
            audio = synthesize_speech(response, voice)
            if rvc_enabled:
                audio = apply_rvc(audio, model_path)
            return ProcessingResponse(type="audio", content=audio)
        else:
            return ProcessingResponse(type="text", content=response)
```

## Database Schema

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

## Directory Structure

```
cognitia/
├── ARCHITECTURE.md              # This file
├── pyproject.toml               # Python package config
├── requirements.txt             # Dependencies
├── Dockerfile                   # For GPU Core
├── deploy/
│   └── Dockerfile.entrance      # For K8s Entrance
├── configs/
│   └── *.yaml                   # Configuration files
├── models/
│   ├── ASR/                     # Speech recognition models
│   └── TTS/                     # Text-to-speech models
├── rvc_models/                  # RVC voice models
├── web/                         # Static web UI
│   ├── index.html
│   ├── css/
│   └── js/
└── src/cognitia/
    ├── __init__.py
    ├── cli.py                   # CLI entry point
    │
    ├── core/                    # GPU Core (AI processing)
    │   ├── __init__.py
    │   ├── server.py            # FastAPI server
    │   └── orchestrator.py      # Processing pipeline
    │
    ├── entrance/                # K8s Entrance (auth + proxy)
    │   ├── __init__.py
    │   ├── server.py            # FastAPI server
    │   ├── auth.py              # JWT handling
    │   ├── database.py          # SQLAlchemy models
    │   └── schemas.py           # Pydantic schemas
    │
    ├── ASR/                     # Speech recognition
    ├── TTS/                     # Text-to-speech
    ├── memory/                  # Conversation memory
    └── utils/                   # Shared utilities
```

## Running the Services

### GPU Core (on GPU server)
```bash
# Install dependencies
pip install -e .

# Download models
cognitia download

# Run Core server
cognitia core --host 0.0.0.0 --port 8080

# Or with environment variables
OLLAMA_URL=http://localhost:11434 \
OLLAMA_MODEL=hermes-4 \
RVC_URL=http://localhost:5050 \
cognitia core
```

### Entrance (on K8s or locally)
```bash
# Run Entrance server
cognitia entrance --host 0.0.0.0 --port 8000

# With environment variables
DATABASE_URL=postgresql+asyncpg://user:pass@host/db \
JWT_SECRET=your-secret \
COGNITIA_CORE_URL=http://10.0.0.15:8080 \
cognitia entrance
```

### Docker

```bash
# Build Core image
docker build -t cognitia-core -f Dockerfile .

# Build Entrance image
docker build -t cognitia-entrance -f deploy/Dockerfile.entrance .
```

## Security Considerations

1. **JWT Tokens**: HS256, 1-hour access, 30-day refresh
2. **Passwords**: bcrypt hashing
3. **HTTPS**: TLS via cert-manager wildcard
4. **Core Trust**: All requests to Core are pre-authenticated
5. **CORS**: Configurable origins
6. **Rate Limiting**: Implement per-user limits (TODO)

## VRAM Budget

- LLM (Hermes-4-14B): ~10GB
- ASR (Parakeet TDT): ~1GB
- TTS (Kokoro): ~0.5GB
- RVC: ~1GB
- **Total**: ~12.5GB (fits in RTX 3090's 24GB)

## Future Enhancements

- [ ] Vision module (VLM integration)
- [ ] Function calling
- [ ] Long-term memory with vector DB
- [ ] Rate limiting
- [ ] Admin dashboard
- [ ] Multiple LLM backends
