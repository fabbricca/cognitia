"""
Network Audio I/O for Cognitia.

This module provides a network-based audio I/O implementation that streams
audio between a remote client and the Cognitia server. It implements the same
AudioProtocol interface as SoundDeviceAudioIO, so Cognitia runs unchanged.

The protocol is simple binary TCP:
- Client → Server: 16kHz mono int16 audio chunks (512 samples = 1024 bytes)
- Client → Server: Text messages: [0xFFFFFFFF][length][utf-8 text]
- Server → Client: TTS audio chunks (variable size, prefixed with length)
- Server → Client: Text messages: [0xFFFFFFFE][length][utf-8 text]

With authentication enabled (v2.1+):
- Client → Server: [AUTH_REQUEST][length][jwt_token] (first, on connect)
- Server → Client: [AUTH_RESPONSE_SUCCESS][user_id] or [AUTH_RESPONSE_FAILURE][error]
"""

import queue
import socket
import struct
import threading
import time
from typing import Optional

from loguru import logger
import numpy as np
from numpy.typing import NDArray

from . import VAD

# Optional authentication support (v2.1+)
try:
    from ..auth import AuthenticationMiddleware, ConnectionContext
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    AuthenticationMiddleware = None  # type: ignore
    ConnectionContext = None  # type: ignore


# Protocol markers
TEXT_MESSAGE_FROM_CLIENT = 0xFFFFFFFF
TEXT_MESSAGE_TO_CLIENT = 0xFFFFFFFE
USER_TRANSCRIPTION_TO_CLIENT = 0xFFFFFFFD  # Send ASR transcription back to client
KEEPALIVE_TO_CLIENT = 0xFFFFFFFC


class NetworkAudioIO:
    """Network-based Audio I/O that streams audio over TCP.
    
    Replaces SoundDeviceAudioIO for remote audio streaming while maintaining
    the exact same interface. All Cognitia logic (VAD, interruption, queues)
    works unchanged.
    
    Also supports text messages from the unified client.
    """

    SAMPLE_RATE: int = 16000
    VAD_SIZE: int = 32  # ms
    VAD_THRESHOLD: float = 0.8
    CHUNK_SAMPLES: int = 512  # 32ms at 16kHz

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5555,
        vad_threshold: float | None = None,
        auth_middleware: Optional["AuthenticationMiddleware"] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.vad_threshold = vad_threshold if vad_threshold else self.VAD_THRESHOLD

        self._vad_model = VAD()
        self._sample_queue: queue.Queue[tuple[NDArray[np.float32], bool]] = queue.Queue()
        self._text_message_queue: queue.Queue[str] = queue.Queue()  # For text messages from client

        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._client_addr = None
        self._client_connected = False

        self._is_playing = False
        self._stop_speaking_event = threading.Event()
        self._shutdown_event = threading.Event()

        self._listen_thread: Optional[threading.Thread] = None
        self._keepalive_thread: Optional[threading.Thread] = None
        self._playback_lock = threading.Lock()

        # Authentication (v2.1+)
        self._auth_middleware = auth_middleware
        self._connection_context: Optional["ConnectionContext"] = None

    def start_listening(self) -> None:
        """Start the TCP server and wait for client connection."""
        self._shutdown_event.clear()
        
        # Create server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(1)
        self._server_socket.settimeout(1.0)  # Allow checking shutdown
        
        logger.info(f"Network audio server listening on {self.host}:{self.port}")
        
        # Wait for client in a thread
        self._listen_thread = threading.Thread(target=self._accept_and_receive, daemon=True)
        self._listen_thread.start()
        
        # Start keepalive thread
        self._keepalive_thread = threading.Thread(target=self._send_keepalives, daemon=True)
        self._keepalive_thread.start()

    def _send_keepalives(self) -> None:
        """Send periodic keepalive packets to client."""
        while not self._shutdown_event.is_set():
            if self._client_connected and self._client_socket:
                try:
                    # Send keepalive: [0xFFFFFFFC][0]
                    header = struct.pack("<II", KEEPALIVE_TO_CLIENT, 0)
                    with self._playback_lock:
                        self._client_socket.sendall(header)
                except:
                    pass
            time.sleep(2.0)

    def _accept_and_receive(self) -> None:
        """Accept client connection and receive audio and text messages."""
        while not self._shutdown_event.is_set():
            # Wait for client
            logger.info("Waiting for client connection...")
            while not self._shutdown_event.is_set():
                try:
                    self._client_socket, self._client_addr = self._server_socket.accept()
                    self._client_socket.settimeout(0.1)
                    self._client_connected = True
                    logger.success(f"Client connected from {self._client_addr}")
                    break
                except socket.timeout:
                    continue
                except OSError:
                    return
            
            if self._shutdown_event.is_set():
                return

            # ========================================================================
            # AUTHENTICATION (v2.1+)
            # ========================================================================
            # Perform authentication handshake before processing audio/text
            if self._auth_middleware:
                logger.info("Performing authentication handshake...")
                self._connection_context = self._auth_middleware.authenticate_connection(
                    self._client_socket
                )

                if not self._connection_context:
                    logger.warning("Authentication failed, closing connection")
                    self._client_connected = False
                    if self._client_socket:
                        try:
                            self._client_socket.close()
                        except:
                            pass
                        self._client_socket = None
                    continue  # Go back to waiting for new client

                logger.success(f"Authenticated as: {self._connection_context.username}")
            else:
                logger.debug("Authentication disabled, allowing unauthenticated connection")
                self._connection_context = None
            # ========================================================================

            # Receive audio chunks and text messages
            buffer = b""
            chunk_size = self.CHUNK_SAMPLES * 2  # int16 = 2 bytes
            chunk_count = 0
            
            while not self._shutdown_event.is_set():
                try:
                    data = self._client_socket.recv(4096)
                    if not data:
                        logger.info("Client disconnected")
                        break
                    
                    buffer += data
                    
                    # Check for text message header first (8 bytes: marker + length)
                    while len(buffer) >= 8:
                        # Peek at potential marker
                        potential_marker = struct.unpack("<I", buffer[:4])[0]
                        
                        if potential_marker == TEXT_MESSAGE_FROM_CLIENT:
                            # Text message: [0xFFFFFFFF][length][utf-8 text]
                            text_length = struct.unpack("<I", buffer[4:8])[0]
                            total_msg_size = 8 + text_length
                            
                            if len(buffer) < total_msg_size:
                                break  # Wait for more data
                            
                            text_bytes = buffer[8:total_msg_size]
                            buffer = buffer[total_msg_size:]
                            
                            text = text_bytes.decode('utf-8', errors='replace')
                            logger.success(f"Received text message: '{text}'")
                            self._text_message_queue.put(text)
                            continue
                        
                        # Not a text message - process as audio chunk
                        if len(buffer) < chunk_size:
                            break
                        
                        chunk_bytes = buffer[:chunk_size]
                        buffer = buffer[chunk_size:]
                        
                        # Convert to float32 [-1, 1]
                        audio_int16 = np.frombuffer(chunk_bytes, dtype=np.int16)
                        audio_float = audio_int16.astype(np.float32) / 32768.0
                        
                        # Run VAD
                        vad_value = self._vad_model(np.expand_dims(audio_float, 0))
                        vad_confidence = bool(vad_value > self.vad_threshold)
                        
                        self._sample_queue.put((audio_float, vad_confidence))
                        
                        chunk_count += 1
                        if chunk_count % 100 == 0:
                            max_val = np.max(np.abs(audio_float))
                            logger.debug(f"Received {chunk_count} chunks, max={max_val:.3f}, vad={vad_value:.3f}")
                        
                except socket.timeout:
                    continue
                except (OSError, ConnectionResetError) as e:
                    logger.error(f"Client connection lost: {e}")
                    break
                except Exception as e:
                    logger.error(f"Client connection error: {e}")
                    break
            
            # Cleanup after disconnect - loop back to accept new client
            logger.warning("Client disconnected - cleaning up socket")
            self._client_connected = False
            self._connection_context = None  # Reset auth context
            if self._client_socket:
                try:
                    self._client_socket.close()
                except:
                    pass
                self._client_socket = None

            logger.info("Ready for new client connection")

    def stop_listening(self) -> None:
        """Stop the server and close connections."""
        self._shutdown_event.set()
        
        if self._client_socket:
            try:
                self._client_socket.close()
            except:
                pass
            self._client_socket = None
        
        if self._server_socket:
            try:
                self._server_socket.close()
            except:
                pass
            self._server_socket = None
        
        if self._listen_thread:
            self._listen_thread.join(timeout=2.0)
            self._listen_thread = None

    def start_speaking(
        self,
        audio_data: NDArray[np.float32],
        sample_rate: int | None = None,
        text: str = "",
    ) -> None:
        """Send audio to the client for playback."""
        if not self._client_connected or self._client_socket is None:
            logger.warning("No client connected, cannot play audio")
            return
        
        if sample_rate is None:
            sample_rate = self.SAMPLE_RATE
        
        # Stop any current playback
        self.stop_speaking()
        self._stop_speaking_event.clear()
        self._is_playing = True
        
        # Convert to int16
        audio_int16 = (audio_data * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()
        
        # Send: [4 bytes length][4 bytes sample_rate][audio data]
        header = struct.pack("<II", len(audio_bytes), sample_rate)
        
        try:
            with self._playback_lock:
                self._client_socket.sendall(header + audio_bytes)
        except (OSError, BrokenPipeError) as e:
            logger.error(f"Failed to send audio: {e}")
            self._is_playing = False

    def measure_percentage_spoken(
        self,
        total_samples: int,
        sample_rate: int | None = None,
    ) -> tuple[bool, int]:
        """Wait for playback to complete or be interrupted."""
        if sample_rate is None:
            sample_rate = self.SAMPLE_RATE
        
        # Calculate expected playback time
        duration = total_samples / sample_rate
        
        # Wait, checking for interruption
        interrupted = self._stop_speaking_event.wait(timeout=duration)
        
        if interrupted:
            return True, 0
        
        self._is_playing = False
        return False, 100

    def check_if_speaking(self) -> bool:
        """Check if audio is currently being played."""
        return self._is_playing

    def stop_speaking(self) -> None:
        """Stop audio playback."""
        if self._is_playing:
            self._stop_speaking_event.set()
            
            # Send stop command to client
            if self._client_socket:
                try:
                    # Length 0 = stop playback
                    self._client_socket.sendall(struct.pack("<II", 0, 0))
                except:
                    pass
            
            self._is_playing = False

    def get_sample_queue(self) -> queue.Queue[tuple[NDArray[np.float32], bool]]:
        """Get the queue containing audio samples and VAD confidence."""
        return self._sample_queue

    def get_text_message_queue(self) -> queue.Queue[str]:
        """Get the queue containing text messages from client."""
        return self._text_message_queue

    def send_text_to_client(self, text: str) -> None:
        """Send a text message to the client."""
        if not self._client_connected or self._client_socket is None:
            logger.warning("No client connected, cannot send text")
            # Try to wait briefly for reconnection
            for _ in range(5):
                time.sleep(0.1)
                if self._client_connected and self._client_socket:
                    break
            if not self._client_connected or self._client_socket is None:
                return
        
        text_bytes = text.encode('utf-8')
        # Protocol: [0xFFFFFFFE][length][utf-8 text]
        header = struct.pack("<II", TEXT_MESSAGE_TO_CLIENT, len(text_bytes))
        
        try:
            with self._playback_lock:
                self._client_socket.sendall(header + text_bytes)
        except (OSError, BrokenPipeError) as e:
            logger.error(f"Failed to send text: {e}")

    def send_user_transcription(self, text: str) -> None:
        """Send user's transcribed speech back to the client for display."""
        if not self._client_connected or self._client_socket is None:
            return

        text_bytes = text.encode('utf-8')
        # Protocol: [0xFFFFFFFD][length][utf-8 text]
        header = struct.pack("<II", USER_TRANSCRIPTION_TO_CLIENT, len(text_bytes))

        try:
            with self._playback_lock:
                self._client_socket.sendall(header + text_bytes)
        except (OSError, BrokenPipeError) as e:
            logger.error(f"Failed to send user transcription: {e}")

    def get_connection_context(self) -> Optional["ConnectionContext"]:
        """
        Get the current connection's authentication context.

        Returns:
            ConnectionContext with user info and permissions, or None if:
            - No client connected
            - Authentication disabled
            - Not yet authenticated

        Use this to access user_id for memory isolation and permissions for RBAC.
        """
        return self._connection_context
