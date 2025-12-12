"""Simple TUI for GLaDOS chat - 50 message buffer, no scroll."""

import asyncio
import json
import os
import sys
from collections import deque
from datetime import datetime
from typing import Optional

try:
    import websockets
except ImportError:
    print("Error: websockets not installed. Run: pip install websockets")
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None

# Configuration
API_URL = os.getenv("COGNITIA_API_URL", "http://localhost:8000")
WS_URL = os.getenv("COGNITIA_WS_URL", "ws://localhost:8000/ws")
MAX_MESSAGES = 50


class Message:
    """Chat message."""
    
    def __init__(self, role: str, content: str, timestamp: Optional[datetime] = None):
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.now()
    
    def format(self) -> str:
        """Format message for display."""
        time_str = self.timestamp.strftime("%H:%M:%S")
        role_str = self.role.upper()[:10].ljust(10)
        return f"[{time_str}] {role_str}: {self.content}"


class TUIApp:
    """Simple TUI application."""
    
    def __init__(self, api_url: str = API_URL, ws_url: str = WS_URL):
        self.api_url = api_url
        self.ws_url = ws_url
        self.messages: deque = deque(maxlen=MAX_MESSAGES)
        self.websocket = None
        self.running = False
        self.connected = False
        self.authenticated = False
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.character_name = "COGNITIA"
        self.current_response = ""  # For streaming responses
    
    def clear_screen(self):
        """Clear terminal screen."""
        os.system("clear" if os.name != "nt" else "cls")
    
    def render(self):
        """Render the current state."""
        self.clear_screen()
        
        # Header
        print("╔" + "═" * 70 + "╗")
        status = "●" if self.connected and self.authenticated else "○"
        auth_status = "AUTH" if self.authenticated else "NOAUTH"
        print(f"║  Cognitia TUI  {status} [{auth_status}]  Character: {self.character_name:<30}║")
        print("╠" + "═" * 70 + "╣")
        
        # Messages area (reserve space for input)
        try:
            terminal_height = os.get_terminal_size().lines
        except:
            terminal_height = 24
        message_lines = terminal_height - 7  # Header + input area
        
        # Get last N messages that fit
        displayed = list(self.messages)[-message_lines:]
        
        for msg in displayed:
            line = msg.format()
            # Truncate if too long
            if len(line) > 68:
                line = line[:65] + "..."
            print(f"║ {line:<68}║")
        
        # Fill remaining space
        for _ in range(message_lines - len(displayed)):
            print(f"║{' ' * 70}║")
        
        # Input area
        print("╠" + "═" * 70 + "╣")
        print("║ Type your message (or 'quit' to exit, 'login' to authenticate):" + " " * 4 + "║")
        print("╚" + "═" * 70 + "╝")
    
    def add_message(self, role: str, content: str):
        """Add a message to the buffer."""
        self.messages.append(Message(role, content))
    
    async def login(self, email: str, password: str) -> bool:
        """Login to get authentication token."""
        if not httpx:
            self.add_message("ERROR", "httpx not installed, cannot login")
            return False
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/auth/login",
                    json={"email": email, "password": password}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.token = data.get("access_token")
                    self.user_id = data.get("user_id")
                    self.add_message("SYSTEM", "Login successful!")
                    return True
                else:
                    self.add_message("ERROR", f"Login failed: {response.text}")
                    return False
        except Exception as e:
            self.add_message("ERROR", f"Login error: {e}")
            return False
    
    async def register(self, email: str, password: str) -> bool:
        """Register a new account."""
        if not httpx:
            self.add_message("ERROR", "httpx not installed, cannot register")
            return False
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/auth/register",
                    json={"email": email, "password": password}
                )
                
                if response.status_code in (200, 201):
                    self.add_message("SYSTEM", "Registration successful! Logging in...")
                    return await self.login(email, password)
                else:
                    self.add_message("ERROR", f"Registration failed: {response.text}")
                    return False
        except Exception as e:
            self.add_message("ERROR", f"Registration error: {e}")
            return False
    
    async def connect(self):
        """Connect to the WebSocket server."""
        try:
            self.websocket = await websockets.connect(self.ws_url)
            self.connected = True
            self.add_message("SYSTEM", f"Connected to {self.ws_url}")
            
            # Authenticate if we have a token
            if self.token:
                await self.websocket.send(json.dumps({
                    "type": "auth",
                    "token": self.token
                }))
                
                # Wait for auth response
                response = await asyncio.wait_for(
                    self.websocket.recv(),
                    timeout=10.0
                )
                msg = json.loads(response)
                
                if msg.get("type") == "auth_success":
                    self.authenticated = True
                    self.add_message("SYSTEM", "WebSocket authenticated!")
                else:
                    self.add_message("ERROR", f"Auth failed: {msg.get('message', 'Unknown')}")
            
            return True
        except Exception as e:
            self.add_message("ERROR", f"Connection failed: {e}")
            return False
    
    async def receive_messages(self):
        """Receive messages from WebSocket."""
        try:
            async for message in self.websocket:
                if not self.running:
                    break
                
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type")
                    
                    if msg_type == "text_chunk":
                        # Streaming response
                        chunk = msg.get("text", msg.get("chunk", ""))
                        self.current_response += chunk
                        # Update the last message if it's from assistant
                        if self.messages and self.messages[-1].role == self.character_name:
                            self.messages[-1].content = self.current_response
                        else:
                            self.add_message(self.character_name, self.current_response)
                        self.render()
                        
                    elif msg_type == "text_complete":
                        # Response complete
                        full_text = msg.get("text", self.current_response)
                        if self.messages and self.messages[-1].role == self.character_name:
                            self.messages[-1].content = full_text
                        else:
                            self.add_message(self.character_name, full_text)
                        self.current_response = ""
                        self.render()
                        
                    elif msg_type == "transcription":
                        # Our speech was transcribed
                        text = msg.get("text", "")
                        self.add_message("USER (voice)", text)
                        self.render()
                        
                    elif msg_type == "status":
                        self.add_message("SYSTEM", msg.get("message", ""))
                        self.render()
                        
                    elif msg_type == "error":
                        self.add_message("ERROR", msg.get("message", "Unknown error"))
                        self.render()
                        
                except json.JSONDecodeError:
                    pass
                    
        except websockets.ConnectionClosed:
            self.connected = False
            self.authenticated = False
            self.add_message("SYSTEM", "Disconnected from server")
            self.render()
        except Exception as e:
            self.add_message("ERROR", str(e))
            self.render()
    
    async def send_message(self, text: str):
        """Send a text message."""
        if not self.websocket or not self.connected:
            self.add_message("ERROR", "Not connected")
            return
        
        if not self.authenticated:
            self.add_message("ERROR", "Not authenticated. Use 'login' first.")
            return
        
        try:
            await self.websocket.send(json.dumps({
                "type": "text",
                "message": text,
            }))
            self.add_message("USER", text)
            self.render()
        except Exception as e:
            self.add_message("ERROR", f"Send failed: {e}")
            self.render()
    
    async def handle_command(self, cmd: str) -> bool:
        """Handle special commands. Returns True if command was handled."""
        parts = cmd.split(maxsplit=2)
        command = parts[0].lower()
        
        if command == "login":
            loop = asyncio.get_event_loop()
            self.add_message("SYSTEM", "Enter email:")
            self.render()
            email = await loop.run_in_executor(None, input, "> ")
            self.add_message("SYSTEM", "Enter password:")
            self.render()
            password = await loop.run_in_executor(None, input, "> ")
            
            if await self.login(email.strip(), password.strip()):
                # Reconnect WebSocket with new token
                if self.websocket:
                    await self.websocket.close()
                await self.connect()
            self.render()
            return True
        
        elif command == "register":
            loop = asyncio.get_event_loop()
            self.add_message("SYSTEM", "Enter email:")
            self.render()
            email = await loop.run_in_executor(None, input, "> ")
            self.add_message("SYSTEM", "Enter password (min 8 chars):")
            self.render()
            password = await loop.run_in_executor(None, input, "> ")
            
            if await self.register(email.strip(), password.strip()):
                if self.websocket:
                    await self.websocket.close()
                await self.connect()
            self.render()
            return True
        
        elif command == "reconnect":
            if self.websocket:
                await self.websocket.close()
            await self.connect()
            self.render()
            return True
        
        elif command == "clear":
            self.messages.clear()
            self.render()
            return True
        
        elif command == "help":
            self.add_message("HELP", "Commands: login, register, reconnect, clear, quit")
            self.render()
            return True
        
        return False
    
    async def input_loop(self):
        """Handle user input."""
        loop = asyncio.get_event_loop()
        
        while self.running:
            try:
                # Read input in a thread to not block
                user_input = await loop.run_in_executor(None, input, "> ")
                
                if user_input.lower() in ("quit", "exit", "q"):
                    self.running = False
                    break
                
                if user_input.strip():
                    # Check for commands
                    if await self.handle_command(user_input.strip()):
                        continue
                    
                    # Regular message
                    await self.send_message(user_input.strip())
                    
            except EOFError:
                self.running = False
                break
            except KeyboardInterrupt:
                self.running = False
                break
    
    async def run(self):
        """Run the TUI application."""
        self.running = True
        self.add_message("SYSTEM", "Welcome to Cognitia TUI!")
        self.add_message("SYSTEM", "Type 'help' for commands, 'login' to authenticate")
        self.render()
        
        # Connect to WebSocket
        await self.connect()
        self.render()
        
        # Run receive and input loops concurrently
        receive_task = asyncio.create_task(self.receive_messages())
        input_task = asyncio.create_task(self.input_loop())
        
        try:
            await asyncio.gather(receive_task, input_task, return_exceptions=True)
        finally:
            if self.websocket:
                await self.websocket.close()
        
        print("\nGoodbye!")


def run_tui(api_url: Optional[str] = None, ws_url: Optional[str] = None):
    """Run the TUI application."""
    api = api_url or os.getenv("COGNITIA_API_URL", API_URL)
    ws = ws_url or os.getenv("COGNITIA_WS_URL", WS_URL)
    app = TUIApp(api, ws)
    
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print("\nExiting...")


def main():
    """Entry point for the TUI application."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Cognitia TUI Chat Client")
    parser.add_argument("--api-url", help="API server URL", default=None)
    parser.add_argument("--ws-url", help="WebSocket server URL", default=None)
    args = parser.parse_args()
    
    run_tui(args.api_url, args.ws_url)


if __name__ == "__main__":
    main()
