"""WebSocket bridge server - connects web clients to GPU backend."""

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol

from .protocol import backend_to_ws, read_backend_message, ws_to_backend

# Configuration from environment
BACKEND_HOST = os.getenv("GLADOS_BACKEND_HOST", "10.0.0.15")
BACKEND_PORT = int(os.getenv("GLADOS_BACKEND_PORT", "5555"))
WEBSOCKET_HOST = os.getenv("WEBSOCKET_HOST", "0.0.0.0")
WEBSOCKET_PORT = int(os.getenv("WEBSOCKET_PORT", "8765"))

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("cognitia.bridge")


class BridgeSession:
    """Manages a single WebSocket to TCP bridge session."""
    
    def __init__(self, websocket: WebSocketServerProtocol, client_ip: str):
        self.websocket = websocket
        self.client_ip = client_ip
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.authenticated = False
        self.user_id: Optional[str] = None
        self.running = False
    
    async def connect_to_backend(self) -> bool:
        """Establish TCP connection to GPU backend."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(BACKEND_HOST, BACKEND_PORT),
                timeout=10.0
            )
            logger.info(f"[{self.client_ip}] Connected to backend {BACKEND_HOST}:{BACKEND_PORT}")
            return True
        except asyncio.TimeoutError:
            logger.error(f"[{self.client_ip}] Backend connection timeout")
            return False
        except Exception as e:
            logger.error(f"[{self.client_ip}] Backend connection failed: {e}")
            return False
    
    async def ws_to_backend_forwarder(self):
        """Forward messages from WebSocket to TCP backend."""
        try:
            async for message in self.websocket:
                if not self.running:
                    break
                
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type")
                    
                    # Log message type (not content for privacy)
                    logger.debug(f"[{self.client_ip}] WS->Backend: {msg_type}")
                    
                    # Convert and forward
                    binary_msg = ws_to_backend(msg)
                    self.writer.write(binary_msg)
                    await self.writer.drain()
                    
                except json.JSONDecodeError as e:
                    logger.error(f"[{self.client_ip}] Invalid JSON: {e}")
                    await self.send_error("Invalid JSON message")
                except ValueError as e:
                    logger.error(f"[{self.client_ip}] Protocol error: {e}")
                    await self.send_error(str(e))
                    
        except websockets.ConnectionClosed:
            logger.info(f"[{self.client_ip}] WebSocket closed")
        except Exception as e:
            logger.error(f"[{self.client_ip}] WS->Backend error: {e}")
    
    async def backend_to_ws_forwarder(self):
        """Forward messages from TCP backend to WebSocket."""
        try:
            while self.running:
                binary_msg = await read_backend_message(self.reader)
                
                if binary_msg is None:
                    logger.info(f"[{self.client_ip}] Backend connection closed")
                    break
                
                try:
                    ws_msg = backend_to_ws(binary_msg)
                    msg_type = ws_msg.get("type")
                    
                    # Skip keepalives
                    if msg_type == "keepalive":
                        continue
                    
                    logger.debug(f"[{self.client_ip}] Backend->WS: {msg_type}")
                    await self.websocket.send(json.dumps(ws_msg))
                    
                except ValueError as e:
                    logger.error(f"[{self.client_ip}] Protocol error: {e}")
                except Exception as e:
                    logger.error(f"[{self.client_ip}] Backend->WS error: {e}")
                    
        except Exception as e:
            logger.error(f"[{self.client_ip}] Backend forwarder error: {e}")
    
    async def send_error(self, message: str):
        """Send error message to WebSocket client."""
        try:
            await self.websocket.send(json.dumps({
                "type": "error",
                "message": message
            }))
        except Exception:
            pass
    
    async def run(self):
        """Run the bridge session."""
        # Connect to backend
        if not await self.connect_to_backend():
            await self.send_error("Failed to connect to backend")
            return
        
        self.running = True
        
        # Send connection confirmation
        await self.websocket.send(json.dumps({
            "type": "connected",
            "message": "Connected to Cognitia backend"
        }))
        
        # Run forwarders concurrently
        try:
            await asyncio.gather(
                self.ws_to_backend_forwarder(),
                self.backend_to_ws_forwarder(),
            )
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """Clean up resources."""
        self.running = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


async def handle_connection(websocket: WebSocketServerProtocol):
    """Handle a new WebSocket connection."""
    # Get client IP
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    logger.info(f"[{client_ip}] New WebSocket connection")
    
    session = BridgeSession(websocket, client_ip)
    
    try:
        await session.run()
    except Exception as e:
        logger.error(f"[{client_ip}] Session error: {e}")
    finally:
        logger.info(f"[{client_ip}] Session ended")


async def main():
    """Main entry point for the bridge server."""
    logger.info(f"Starting Cognitia Bridge Server")
    logger.info(f"  WebSocket: {WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
    logger.info(f"  Backend: {BACKEND_HOST}:{BACKEND_PORT}")
    
    # Handle shutdown signals
    stop = asyncio.Event()
    
    def handle_signal():
        logger.info("Shutdown signal received")
        stop.set()
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)
    
    # Start WebSocket server
    async with websockets.serve(
        handle_connection,
        WEBSOCKET_HOST,
        WEBSOCKET_PORT,
        ping_interval=30,
        ping_timeout=10,
    ) as server:
        logger.info(f"Bridge server listening on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        await stop.wait()
    
    logger.info("Bridge server stopped")


def run_bridge():
    """Run the bridge server."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run_bridge()
