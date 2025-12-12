<a href="https://trendshift.io/repositories/9828" target="_blank"><img src="https://trendshift.io/api/badge/repositories/9828" alt="dnhkng%2FGlaDOS | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

# GLaDOS Personality Core

This is a project dedicated to building a real-life version of GLaDOS!

**Original Creator**: [dnhkng](https://github.com/dnhkng)

NEW: If you want to chat or join the community, [Join our discord!](https://discord.com/invite/ERTDKwpjNB) If you want to support, [sponsor the project here!](https://ko-fi.com/dnhkng)

https://github.com/user-attachments/assets/c22049e4-7fba-4e84-8667-2c6657a656a0

---

## 🎉 Latest Updates

### 🌐 Web Interface (v2.0 - Simplified)

**Status:** ✅ Production Ready

Access GLaDOS from any device with full voice support and mobile PWA!

#### Quick Start (2 Commands)

**On GPU server:**
```bash
./scripts/start_server.sh  # Starts GLaDOS + WebSocket bridge + Web frontend
```

**From any device:**
```bash
./scripts/start_client.sh --web   # Open web interface
./scripts/start_client.sh --tui   # Launch TUI client
./scripts/start_client.sh --cli   # Launch CLI client
```

**Features:**
- ✅ Full voice input/output (Web Audio API)
- ✅ Mobile PWA (install as app on Android/iOS)
- ✅ Text and voice chat
- ✅ JWT authentication support
- ✅ Real-time WebSocket communication
- ✅ Works on any modern browser

**Default server:** `iberu.me:12345`

#### Web Interface Architecture

```
Browser (http://localhost:8080)
    ↓ WebSocket
WebSocket Bridge (ws://localhost:8765)
    ↓ Binary Protocol
GLaDOS Server (tcp://localhost:5555)
```

**Mobile Installation:**
1. Open `http://your-server-ip:8080` in Chrome (Android) or Safari (iOS)
2. Add to Home screen
3. Use like a native app with full voice support

**Note:** Enterprise deployment options (Kubernetes, Docker Compose, CI/CD) are archived in `archived/deployment-infrastructure/` if needed.

---

### v2.1: JWT-Based Multi-User Authentication ✨

- **Secure authentication** with JWT tokens and bcrypt password hashing
- **Per-user memory isolation** - each user has their own conversation and entity memory
- **Role-based access control (RBAC)** - admin, user, guest, restricted roles
- **Network mode** with authenticated clients
- **Backward compatible** - authentication is optional

#### User Management

```bash
# List all users
python scripts/manage_users.py list

# Create user with role
python scripts/manage_users.py create <username> <email> --role <admin|user|guest|restricted>

# Change user role
python scripts/manage_users.py set-role <username> <role>

# Deactivate user
python scripts/manage_users.py set-active <username> false

# Revoke all user tokens
python scripts/manage_users.py revoke-tokens <username>

# View role permissions
python scripts/manage_users.py permissions <role>
```

#### Role Permission Matrix

| Permission | Admin | User | Guest | Restricted |
|-----------|-------|------|-------|-----------|
| Chat | ✅ | ✅ | ✅ | ✅ |
| View Memory | ✅ | ✅ | ✅ | ❌ |
| Search Memory | ✅ | ✅ | ❌ | ❌ |
| Create Calendar/Reminders/Todos | ✅ | ✅ | ❌ | ❌ |
| View Calendar/Reminders/Todos | ✅ | ✅ | ✅ | ❌ |
| Get Time/Weather | ✅ | ✅ | ✅ | ✅/❌ |
| Manage Users/Roles | ✅ | ❌ | ❌ | ❌ |

---

### Enhanced Network Mode 🌐

- **TUI client** with rich terminal interface (Textual-based)
- **Authentication support** for secure multi-user deployments
- **Real-time audio streaming** over TCP
- **Text-based chat** alongside voice interactions

**Connect with authentication:**
```bash
# TUI client
uv run glados tui --host localhost --port 5555 --auth-token "your-jwt-token"

# Or use token file
uv run glados tui --auth-token-file ~/.glados_token

# Web client (supports auth via web interface)
./scripts/start_client.sh --web
```

---

### Code Quality Improvements (v2.0) 🔧

- **Thread-safe conversation state** - eliminates race conditions
- **Structured exception handling** - clear error types and context
- **Circuit breaker pattern** - prevents cascading LLM failures
- **80% test coverage** - comprehensive unit and integration tests
- **Component lifecycle management** - standardized patterns

#### Recent Fixes

**Database Connections:**
- Fixed all unclosed SQLite connections using context managers (`with` statements)
- Ensures proper resource cleanup even on exceptions
- Compatible with Python 3.13+ strict resource tracking

**pytest Configuration:**
- Fixed ResourceWarning false positives in Python 3.13
- All 73 tests passing cleanly
- Proper warning filtering for SQLite and pytest cleanup

---

## Update 3-1-2025 *Got GLaDOS running on an 8Gb SBC!*

https://github.com/user-attachments/assets/99e599bb-4701-438a-a311-8e6cd595796c

This is really tricky, so only for hardcore geeks! Checkout the 'rock5b' branch, and my OpenAI API for the [RK3588 NPU system](https://github.com/dnhkng/RKLLM-Gradio)

Don't expect support for this, it's in active development, and requires lots of messing about in armbian linux etc.

---

## Goals

*This is a hardware and software project that will create an aware, interactive, and embodied GLaDOS.*

This will entail:
- [x] Train GLaDOS voice generator
- [x] Generate a prompt that leads to a realistic "Personality Core"
- [x] Generate a medium- and long-term memory for GLaDOS (ConversationMemory + EntityMemory with async LLM extraction!)
- [x] Multi-user authentication and memory isolation (v2.1)
- [x] Network mode with TUI client (v2.1)
- [x] Web interface with full voice support (v2.0)
- [ ] Give GLaDOS vision via a VLM (either a full VLM for everything, or a 'vision module' using a tiny VLM the GLaDOS can function call!)
- [ ] Create 3D-printable parts
- [ ] Design the animatronics system

---

## Software Architecture

The initial goals are to develop a low-latency platform, where GLaDOS can respond to voice interactions within 600ms.

To do this, the system constantly records data to a circular buffer, waiting for [voice to be detected](https://github.com/snakers4/silero-vad). When it's determined that the voice has stopped (including detection of normal pauses), it will be [transcribed quickly](https://github.com/huggingface/distil-whisper). This is then passed to streaming [local Large Language Model](https://github.com/ggerganov/llama.cpp), where the streamed text is broken by sentence, and passed to a [text-to-speech system](https://github.com/rhasspy/piper). This means further sentences can be generated while the current is playing, reducing latency substantially.

### Key Features

**Memory System**:
- **ConversationMemory**: Stores recent turns (configurable max), async persistence, LLM summarization
- **EntityMemory**: Extracts user info (name, preferences, relationships) via LLM in background
- **Multi-user isolation**: Each user has separate conversation and entity memory (v2.1)

**Thread Safety & Reliability**:
- Thread-safe conversation state with RLock protection
- Circuit breaker for LLM calls (prevents cascading failures)
- Structured exception handling with full context

**Network Mode**:
- TCP-based audio streaming (16kHz mono int16)
- Text message support for chat-based interactions
- Optional JWT authentication for secure multi-user deployments
- TUI client with rich terminal interface

**Web Interface**:
- WebSocket bridge for browser communication
- Progressive Web App (PWA) with service worker
- Full voice input/output via Web Audio API
- Mobile-friendly, installable on Android/iOS
- Real-time bidirectional communication

### Subgoals
- The other aim of the project is to minimize dependencies, so this can run on constrained hardware. That means no PyTorch or other large packages.
- As I want to fully understand the system, I have removed a large amount of redirection: which means extracting and rewriting code.

---

## Hardware System

This will be based on servo- and stepper-motors. 3D printable STL will be provided to create GlaDOS's body, and she will be given a set of animations to express herself. The vision system will allow her to track and turn toward people and things of interest.

---

# Installation Instructions

Try this simplified process, but be aware it's still in the experimental stage! For all operating systems, you'll first need to install Ollama to run the LLM.

## Install Drivers if necessary!

If you are an Nvidia GPU, make sure you install the necessary drivers and CUDA which you can find here: [CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit)

If you are using another accelerator (ROCm, DirectML etc.), after following the instructions below for you platform, follow up with installing the [best onnxruntime version](https://onnxruntime.ai/docs/install/) for your system.

___If you don't install the appropriate drivers, this system will still work, but the latency will be much greater!___

## Set up a local LLM server

1. Download and install [Ollama](https://github.com/ollama/ollama) for your operating system.
2. Once installed, download a small 3B model for testing - at a terminal or command prompt use: `ollama pull llama3.2`

Note: You can use any OpenAI or Ollama compatible server, local or cloud based. Just edit the glados_config.yaml and update the completion_url, model and the api_key if necessary.

## Operating specific instructions

### Windows Installation Process
1. Open the Microsoft Store, search for `python` and install Python 3.12

### macOS Installation Process
This is still experimental. Any issues can be addressed in the Discord server. If you create an issue related to this, you will be referred to the Discord server. Note: I was getting Segfaults! Please leave feedback!

### Linux Installation Process
Install the PortAudio library, if you don't yet have it installed:

```bash
sudo apt update
sudo apt install libportaudio2
```

## Installing GLaDOS

1. Download this repository, either:
   1. Download and unzip this repository somewhere in your home folder, or
   2. At a terminal, git clone this repository using:
      ```bash
      git clone https://github.com/dnhkng/GLaDOS.git
      ```

2. In a terminal, go to the repository folder and run these commands:

   Mac/Linux:
   ```bash
   python scripts/install.py
   ```

   Windows:
   ```bash
   python scripts\install.py
   ```

   This will install Glados and download the needed AI models

3. To start GLaDOS, run:
   ```bash
   uv run glados
   ```

   If you want something more fancy, try the Text UI (TUI), with:
   ```bash
   uv run glados tui
   ```

---

## Network Mode & Multi-User Setup

GLaDOS v2.1 supports network mode with optional authentication for secure multi-user deployments.

### Quick Start (No Authentication)

**Server**:
```bash
# Edit configs/glados_network_config.yaml to set audio_io: network
uv run glados start --config configs/glados_network_config.yaml
```

**Client** (TUI):
```bash
uv run glados tui --host localhost --port 5555
```

### Secure Multi-User Mode (with Authentication)

#### 1. Create Admin User
```bash
python scripts/create_admin.py
```
Follow prompts to create an admin user and generate JWT secret.

#### 2. Configure Server
Edit `configs/glados_network_config.yaml`:
```yaml
Glados:
  audio_io: network
  network_host: "0.0.0.0"
  network_port: 5555
  memory:
    enabled: true
    persist_path: "data/conversation_memory.json"
    entity_extraction_enabled: true
```

Create authentication middleware in your server script (see `src/glados/auth/README.md` for details).

#### 3. Client Authentication
```bash
# TUI client with authentication
uv run glados tui --host localhost --port 5555 --auth-token "your-jwt-token"
```

### Multi-User Features
- **Per-user memory**: Each user has isolated conversation and entity memory
- **JWT authentication**: Secure token-based auth with 1h access tokens, 30d refresh tokens
- **RBAC ready**: Permission system foundation for future access control
- **Backward compatible**: Auth is optional, works without authentication

---

## Web Interface

### Start Web Server

On your GPU server:
```bash
./scripts/start_server.sh
```

This starts:
- GLaDOS main server (port 5555)
- WebSocket bridge (port 8765)
- Web frontend (port 8080)

### Connect from Browser

```bash
# Open web interface
./scripts/start_client.sh --web

# Or specify custom server
./scripts/start_client.sh --web --server localhost:8080
```

### Features

- ✅ Full voice input (Web Audio API, microphone access)
- ✅ Full voice output (audio playback)
- ✅ Text chat interface
- ✅ Mobile PWA (install as app)
- ✅ JWT authentication support
- ✅ Dark theme
- ✅ Real-time WebSocket connection
- ✅ Works on desktop and mobile

### Access Points

**Local:**
```
http://localhost:8080
```

**Remote:**
```
http://your-server-ip:8080
```

**Production (with domain):**
```
https://iberu.me
```

---

## Speech Generation

You can also get her to say something with:

```bash
uv run glados say "The cake is real"
```

---

## Changing the LLM Model

To use other models, use the command:
```bash
ollama pull {modelname}
```

and then add it to glados_config.yaml as the model:

```yaml
model: "{modelname}"
```

where __{modelname}__ is a placeholder to be replaced with the model you want to use. You can find [more models here!](https://ollama.com/library)

---

## Changing the Voice Model

You can use voices from Kokoro too!
Select a voice from the following:

### Female
**US**
- af_alloy
- af_aoede
- af_jessica
- af_kore
- af_nicole
- af_nova
- af_river
- af_saraha
- af_sky

**British**
- bf_alice
- bf_emma
- bf_isabella
- bf_lily

### Male
**US**
- am_adam
- am_echo
- am_eric
- am_fenrir
- am_liam
- am_michael
- am_onyx
- am_puck

**British**
- bm_daniel
- bm_fable
- bm_george
- bm_lewis

and then add it to glados_config.yaml as the voice, e.g.:

```yaml
voice: "af_bella"
```

---

## OpenAI-compatible TTS Server

To run the OpenAI-compatible TTS server, first install dependencies using the installer script:

Mac/Linux:
```bash
python scripts/install.py --api
```

Windows:
```bash
python scripts\install.py --api
```

Then run the server with:
```bash
./scripts/serve
```

Alternatively, you can run the server in Docker:
```bash
docker compose up -d --build
```

You can generate voice like this:
```bash
curl -X POST http://localhost:5050/v1/audio/speech \
-H "Content-Type: application/json" \
-d '{
    "input": "Hello world! This is a test.",
    "voice": "glados"
}' \
--output speech.mp3
```

NOTE: The server will not automatically reload on changes when running with Docker. When actively developing, it is recommended to run the server locally using the `serve` script.

The server will be available at [http://localhost:5050](http://localhost:5050)

---

## More Personalities or LLM's

Make a copy of the file 'configs/glados_config.yaml' and give it a new name, then edit the parameters:

```yaml
model:  # the LLM model you want to use, see "Changing the LLM Model"
personality_preprompt:
system:  # A description of who the character should be
    - user:  # An example of a question you might ask
    - assistant:  # An example of how the AI should respond
```

To use these new settings, use the command:
```bash
uv run glados start --config configs/assistant_config.yaml
```

---

## Configuration Options

### Memory System

Configure memory in `glados_config.yaml`:

```yaml
memory:
  enabled: true
  max_turns: 50  # Maximum conversation turns to keep
  persist_path: "data/conversation_memory.json"
  persist_interval_seconds: 30.0
  entity_extraction_enabled: true  # Extract user info via LLM
  entity_persist_path: "data/entity_memory.json"
```

**Features**:
- Automatic persistence every 30 seconds
- Background entity extraction (name, preferences, relationships)
- LLM summarization for older conversations
- Thread-safe operations
- Per-user isolation in multi-user mode

### Network & Authentication

```yaml
audio_io: network  # Enable network mode
network_host: "0.0.0.0"
network_port: 5555
```

For authentication setup, see "Secure Multi-User Mode" section above.

---

## Common Issues

1. If you find you are getting stuck in loops, as GLaDOS is hearing herself speak, you have two options:
   1. Solve this by upgrading your hardware. You need to you either headphone, so she can't physically hear herself speak, or a conference-style room microphone/speaker. These have hardware sound cancellation, and prevent these loops.
   2. Disable voice interruption. This means neither you nor GLaDOS can interrupt when GLaDOS is speaking. To accomplish this, edit the `glados_config.yaml`, and change `interruptible:` to `false`.

2. If you get the following error:
   ```
   ImportError: DLL load failed while importing onnxruntime_pybind11_state
   ```

   you can fix it by installing the latest [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170).

---

## Testing the Submodules

Want to mess around with the AI models? You can test the systems by exploring the 'demo.ipynb'.

---

## Development & Testing

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run unit tests
pytest tests/unit -v

# Run integration tests
pytest tests/integration -v

# Run with coverage
pytest --cov=src/glados --cov-report=html

# Type checking
mypy src/glados/core --strict

# Linting
ruff check src
ruff format src
```

### Authentication Tests

```bash
# Test auth database
pytest tests/unit/test_auth_database.py -v

# Test JWT handling
pytest tests/unit/test_jwt.py -v

# Test user manager
pytest tests/unit/test_user_manager.py -v

# Test multi-user memory isolation
PYTHONPATH=src python tests/integration/test_multi_user_memory.py
```

### Web Interface Tests

```bash
# Unit tests for WebSocket bridge
cd websocket-bridge
pytest test_protocol.py -v

# Health checks
curl http://localhost:8766/health
curl http://localhost:8766/ready
curl http://localhost:8766/metrics
```

---

## Project Structure

```
GLaDOS/
├── src/glados/
│   ├── core/           # Core engine, LLM processor, components
│   ├── auth/           # JWT authentication & RBAC (v2.1)
│   ├── memory/         # Conversation & entity memory systems
│   ├── audio_io/       # Audio I/O (sounddevice, network)
│   ├── ASR/            # Speech recognition (Whisper)
│   ├── TTS/            # Text-to-speech (Kokoro, Piper)
│   └── glados_ui/      # TUI client
├── websocket-bridge/   # WebSocket ↔ TCP bridge for web interface
│   ├── bridge_server.py
│   ├── protocol.py
│   └── requirements.txt
├── web/                # Web interface (PWA)
│   ├── index.html
│   ├── js/app.js
│   ├── css/style.css
│   ├── service-worker.js
│   ├── manifest.json
│   └── icons/
├── network/            # Network client & auth
├── configs/            # Configuration files
├── tests/
│   ├── unit/          # Unit tests
│   └── integration/   # Integration tests
├── scripts/           # Installation & utility scripts
│   ├── start_server.sh    # Start everything (GLaDOS + bridge + web)
│   ├── start_client.sh    # Connect (--web/--tui/--cli)
│   ├── manage_users.py    # User management CLI
│   └── create_admin.py    # Create admin user
└── archived/          # Archived deployment infrastructure
    └── deployment-infrastructure/  # K8s, Docker Compose, CI/CD
```

---

## Recent Development Notes

### Database Fixes (2025-12-11)
- Fixed all unclosed SQLite connections using context managers
- 17 database connection instances updated across database.py and manage_users.py
- Ensures proper resource cleanup, compatible with Python 3.13+
- All 73 tests passing cleanly

### pytest Configuration (2025-12-11)
- Fixed ResourceWarning false positives in Python 3.13
- Updated pytest.ini to filter SQLite ResourceWarnings
- Tests now run cleanly without false warning failures

### Web Interface Simplification (2025-12-11)
- Simplified from 65+ files to 2 scripts (start_server.sh + start_client.sh)
- Archived enterprise deployment infrastructure (K8s, Docker Compose, CI/CD)
- Focus on simplicity: < 1 minute deployment vs 30+ minutes
- Enterprise features available in archived/ if needed

### Week 13: RBAC Complete (2024-12-11)
- Implemented comprehensive Role-Based Access Control
- 4 roles: admin, user, guest, restricted
- Permission-based function calling
- User management CLI (manage_users.py)
- Database schema migration with role field
- Full backward compatibility

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=dnhkng/GlaDOS&type=Date)](https://star-history.com/#dnhkng/GlaDOS&Date)

---

## Sponsors

Companies supporting the development of GLaDOS:

<div align="center">

### [Wispr Flow](https://ref.wisprflow.ai/qbHPGg8)

[![Sponsor](https://raw.githubusercontent.com/dnhkng/assets/refs/heads/main/Flow-symbol.svg)](https://ref.wisprflow.ai/qbHPGg8)

[**Talk to code, stay in the Flow.**](https://ref.wisprflow.ai/qbHPGg8)

[Flow is built for devs who live in their tools. Speak and give more context, get better results.](https://ref.wisprflow.ai/qbHPGg8)

</div>

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run the test suite: `pytest tests/ -v`
5. Submit a pull request

For major changes, please open an issue first to discuss what you would like to change.

---

## License

This project maintains the original license from [dnhkng/GLaDOS](https://github.com/dnhkng/GLaDOS).

---

## Credits

**Original Creator**: [dnhkng](https://github.com/dnhkng)

**v2.0 Refactoring**: Code quality improvements, thread safety, exception handling, circuit breakers, testing infrastructure

**v2.1 Authentication & Multi-User**: JWT authentication, RBAC foundation, per-user memory isolation, TUI client

**v2.0 Web Interface**: WebSocket bridge, PWA with voice support, mobile installation, simplified deployment

Join our [Discord community](https://discord.com/invite/ERTDKwpjNB) to connect with other GLaDOS enthusiasts!
