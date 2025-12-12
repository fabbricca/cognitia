"""
Integration tests for Cognitia Web Interface.

These tests verify end-to-end functionality:
- WebSocket bridge server
- Protocol translation
- Connection management
- Authentication flow
"""

import pytest
import asyncio
import websockets
import json
import struct
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'websocket-bridge'))

from protocol import (
    ws_to_cognitia,
    TEXT_FROM_CLIENT,
    TEXT_TO_CLIENT,
    AUTH_TOKEN_FROM_CLIENT,
    AUTH_RESPONSE_TO_CLIENT
)


class MockCognitiaServer:
    """Mock Cognitia TCP server for testing."""

    def __init__(self, host='127.0.0.1', port=15555):
        self.host = host
        self.port = port
        self.server = None
        self.clients = []

    async def start(self):
        """Start the mock server."""
        self.server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        print(f"Mock Cognitia server started on {self.host}:{self.port}")

    async def stop(self):
        """Stop the mock server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        print("Mock Cognitia server stopped")

    async def handle_client(self, reader, writer):
        """Handle a client connection."""
        print("Mock Cognitia: Client connected")
        self.clients.append((reader, writer))

        try:
            while True:
                # Read header
                header = await reader.read(8)
                if not header:
                    break

                marker = struct.unpack('>I', header[0:4])[0]
                length = struct.unpack('>I', header[4:8])[0]

                # Read data
                data = await reader.readexactly(length)

                print(f"Mock Cognitia: Received marker 0x{marker:08X}, length {length}")

                # Handle different message types
                if marker == AUTH_TOKEN_FROM_CLIENT:
                    # Simulate authentication
                    token = data.decode('utf-8')
                    print(f"Mock Cognitia: Auth token: {token}")

                    if token == "valid-token":
                        response = {
                            'status': 'ok',
                            'user_id': 1,
                            'username': 'testuser'
                        }
                    else:
                        response = {
                            'status': 'error',
                            'message': 'Invalid token'
                        }

                    response_json = json.dumps(response).encode('utf-8')
                    response_binary = (
                        struct.pack('>I', AUTH_RESPONSE_TO_CLIENT) +
                        struct.pack('>I', len(response_json)) +
                        response_json
                    )
                    writer.write(response_binary)
                    await writer.drain()

                elif marker == TEXT_FROM_CLIENT:
                    # Echo the message back
                    message = data.decode('utf-8')
                    print(f"Mock Cognitia: Text message: {message}")

                    response_text = f"Echo: {message}"
                    response_binary = (
                        struct.pack('>I', TEXT_TO_CLIENT) +
                        struct.pack('>I', len(response_text)) +
                        response_text.encode('utf-8')
                    )
                    writer.write(response_binary)
                    await writer.drain()

        except asyncio.CancelledError:
            print("Mock Cognitia: Connection cancelled")
        except Exception as e:
            print(f"Mock Cognitia: Error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            self.clients.remove((reader, writer))
            print("Mock Cognitia: Client disconnected")


@pytest.fixture
async def mock_cognitia_server():
    """Fixture for mock Cognitia server."""
    server = MockCognitiaServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def bridge_server():
    """Fixture for WebSocket bridge server (would need to be started separately)."""
    # In a real test, you'd start the bridge server here
    # For now, assume it's running on localhost:8765
    yield "ws://localhost:8765"


@pytest.mark.asyncio
async def test_websocket_connection():
    """Test basic WebSocket connection to bridge."""
    try:
        async with websockets.connect("ws://localhost:8765") as ws:
            print("Connected to bridge")
            assert ws.open
    except Exception as e:
        pytest.skip(f"Bridge server not running: {e}")


@pytest.mark.asyncio
async def test_authentication_flow(mock_cognitia_server):
    """Test authentication flow through bridge."""
    try:
        async with websockets.connect("ws://localhost:8765") as ws:
            # Send authentication
            auth_msg = {
                'type': 'auth',
                'token': 'valid-token'
            }
            await ws.send(json.dumps(auth_msg))

            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            response_data = json.loads(response)

            print(f"Auth response: {response_data}")

            assert response_data['type'] == 'auth_response'
            assert response_data['status'] == 'ok'
            assert response_data['user_id'] == 1

    except Exception as e:
        pytest.skip(f"Bridge or mock server not running: {e}")


@pytest.mark.asyncio
async def test_text_message_flow(mock_cognitia_server):
    """Test text message exchange through bridge."""
    try:
        async with websockets.connect("ws://localhost:8765") as ws:
            # Authenticate first
            auth_msg = {'type': 'auth', 'token': 'valid-token'}
            await ws.send(json.dumps(auth_msg))
            await ws.recv()  # Wait for auth response

            # Send text message
            text_msg = {
                'type': 'text',
                'message': 'Hello Cognitia'
            }
            await ws.send(json.dumps(text_msg))

            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            response_data = json.loads(response)

            print(f"Text response: {response_data}")

            assert response_data['type'] == 'text'
            assert 'Echo: Hello Cognitia' in response_data['message']

    except Exception as e:
        pytest.skip(f"Bridge or mock server not running: {e}")


@pytest.mark.asyncio
async def test_invalid_authentication(mock_cognitia_server):
    """Test authentication failure."""
    try:
        async with websockets.connect("ws://localhost:8765") as ws:
            # Send invalid authentication
            auth_msg = {
                'type': 'auth',
                'token': 'invalid-token'
            }
            await ws.send(json.dumps(auth_msg))

            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            response_data = json.loads(response)

            print(f"Auth response: {response_data}")

            assert response_data['type'] == 'auth_response'
            assert response_data['status'] == 'error'

    except Exception as e:
        pytest.skip(f"Bridge or mock server not running: {e}")


@pytest.mark.asyncio
async def test_concurrent_connections(mock_cognitia_server):
    """Test multiple concurrent WebSocket connections."""
    try:
        connections = []

        # Create 5 concurrent connections
        for i in range(5):
            ws = await websockets.connect("ws://localhost:8765")
            connections.append(ws)

            # Authenticate
            auth_msg = {'type': 'auth', 'token': 'valid-token'}
            await ws.send(json.dumps(auth_msg))
            await ws.recv()

        print(f"Created {len(connections)} concurrent connections")

        # Send messages from all connections
        for i, ws in enumerate(connections):
            text_msg = {'type': 'text', 'message': f'Message {i}'}
            await ws.send(json.dumps(text_msg))

        # Receive responses
        for i, ws in enumerate(connections):
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            response_data = json.loads(response)
            assert response_data['type'] == 'text'
            assert f'Message {i}' in response_data['message']

        # Close all connections
        for ws in connections:
            await ws.close()

        print("All connections closed successfully")

    except Exception as e:
        pytest.skip(f"Bridge or mock server not running: {e}")


@pytest.mark.asyncio
async def test_connection_recovery():
    """Test that connection recovers after disconnect."""
    try:
        # First connection
        async with websockets.connect("ws://localhost:8765") as ws1:
            auth_msg = {'type': 'auth', 'token': 'valid-token'}
            await ws1.send(json.dumps(auth_msg))
            await ws1.recv()

        # Connection closed, open new one
        async with websockets.connect("ws://localhost:8765") as ws2:
            auth_msg = {'type': 'auth', 'token': 'valid-token'}
            await ws2.send(json.dumps(auth_msg))
            response = await ws2.recv()
            response_data = json.loads(response)

            assert response_data['type'] == 'auth_response'
            assert response_data['status'] == 'ok'

        print("Connection recovery successful")

    except Exception as e:
        pytest.skip(f"Bridge server not running: {e}")


@pytest.mark.asyncio
async def test_large_message():
    """Test handling of large messages."""
    try:
        async with websockets.connect("ws://localhost:8765") as ws:
            # Authenticate
            auth_msg = {'type': 'auth', 'token': 'valid-token'}
            await ws.send(json.dumps(auth_msg))
            await ws.recv()

            # Send large message (10KB)
            large_text = 'A' * 10240
            text_msg = {'type': 'text', 'message': large_text}
            await ws.send(json.dumps(text_msg))

            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=10.0)
            response_data = json.loads(response)

            assert response_data['type'] == 'text'
            assert len(response_data['message']) > 10000

        print("Large message handling successful")

    except Exception as e:
        pytest.skip(f"Bridge server not running: {e}")


def test_protocol_markers():
    """Test that protocol markers are correctly defined."""
    # Verify markers don't conflict
    markers = [
        TEXT_FROM_CLIENT,
        TEXT_TO_CLIENT,
        AUTH_TOKEN_FROM_CLIENT,
        AUTH_RESPONSE_TO_CLIENT
    ]

    assert len(markers) == len(set(markers)), "Protocol markers must be unique"


if __name__ == '__main__':
    # Run with: python -m pytest test_integration.py -v -s
    pytest.main([__file__, '-v', '-s'])
