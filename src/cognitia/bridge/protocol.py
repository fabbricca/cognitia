"""Protocol translation between WebSocket JSON and Cognitia binary protocol."""

import base64
import json
import struct
from typing import Optional

# Protocol markers (little-endian, matching Cognitia server)
TEXT_FROM_CLIENT = 0xFFFFFFFF
TEXT_TO_CLIENT = 0xFFFFFFFE
AUDIO_FROM_CLIENT = 0xFFFFFFF9
AUDIO_TO_CLIENT = 0xFFFFFFF8
CHARACTER_SWITCH = 0xFFFFFFF7
CALL_MODE_START = 0xFFFFFFF6
CALL_MODE_END = 0xFFFFFFF5
KEEPALIVE = 0xFFFFFFFC
STOP_PLAYBACK = 0xFFFFFFFD

# Header size: marker (4 bytes) + length (4 bytes)
HEADER_SIZE = 8


def ws_to_backend(msg: dict) -> bytes:
    """
    Convert WebSocket JSON message to Cognitia binary protocol.
    
    Args:
        msg: Dictionary with 'type' and message-specific fields
        
    Returns:
        Binary data in Cognitia protocol format
        
    Raises:
        ValueError: If message type is unknown or required fields missing
    """
    msg_type = msg.get("type")
    
    if msg_type == "text":
        marker = TEXT_FROM_CLIENT
        message = msg.get("message", "")
        chat_id = msg.get("chatId", "")
        character_id = msg.get("characterId", "")
        
        # Pack as JSON with metadata
        payload = json.dumps({
            "text": message,
            "chat_id": chat_id,
            "character_id": character_id,
        }).encode("utf-8")
        
    elif msg_type == "audio":
        marker = AUDIO_FROM_CLIENT
        # Audio data is base64 encoded in JSON
        audio_b64 = msg.get("data", "")
        audio_bytes = base64.b64decode(audio_b64)
        
        # Pack metadata + audio
        metadata = {
            "format": msg.get("format", "pcm_s16le"),
            "sample_rate": msg.get("sampleRate", 16000),
            "chat_id": msg.get("chatId", ""),
            "character_id": msg.get("characterId", ""),
        }
        metadata_json = json.dumps(metadata).encode("utf-8")
        metadata_length = len(metadata_json)
        
        # [metadata_length:4][metadata:N][audio:M]
        payload = struct.pack("<I", metadata_length) + metadata_json + audio_bytes
        
    elif msg_type == "character_switch":
        marker = CHARACTER_SWITCH
        payload = json.dumps({
            "character_id": msg.get("characterId", ""),
            "system_prompt": msg.get("systemPrompt", ""),
            "voice_model": msg.get("voiceModel", "af_bella"),
            "rvc_model_path": msg.get("rvcModelPath"),
            "rvc_index_path": msg.get("rvcIndexPath"),
        }).encode("utf-8")
        
    elif msg_type == "call_start":
        marker = CALL_MODE_START
        payload = json.dumps({
            "chat_id": msg.get("chatId", ""),
            "character_id": msg.get("characterId", ""),
        }).encode("utf-8")
        
    elif msg_type == "call_end":
        marker = CALL_MODE_END
        payload = b""
        
    elif msg_type == "stop_playback":
        marker = STOP_PLAYBACK
        payload = b""
        
    else:
        raise ValueError(f"Unknown message type: {msg_type}")
    
    # Pack: [marker:4][length:4][data:N] (little-endian)
    return struct.pack("<II", marker, len(payload)) + payload


def backend_to_ws(binary_data: bytes) -> dict:
    """
    Convert Cognitia binary protocol message to WebSocket JSON.
    
    Args:
        binary_data: Complete binary message including header
        
    Returns:
        Dictionary suitable for JSON serialization
        
    Raises:
        ValueError: If data is malformed or marker unknown
    """
    if len(binary_data) < HEADER_SIZE:
        raise ValueError("Data too short for header")
    
    marker, length = struct.unpack("<II", binary_data[:HEADER_SIZE])
    data = binary_data[HEADER_SIZE:]
    
    if len(data) < length:
        raise ValueError(f"Data truncated: expected {length}, got {len(data)}")
    
    data = data[:length]
    
    if marker == TEXT_TO_CLIENT:
        # Text response - may be JSON with metadata or plain text
        try:
            payload = json.loads(data.decode("utf-8"))
            return {
                "type": "text",
                "message": payload.get("text", ""),
                "isAudio": payload.get("is_audio", False),
            }
        except json.JSONDecodeError:
            return {
                "type": "text",
                "message": data.decode("utf-8"),
                "isAudio": False,
            }
            
    elif marker == AUDIO_TO_CLIENT:
        # Audio response - extract metadata and audio
        if len(data) < 4:
            raise ValueError("Audio data too short")
        
        metadata_length = struct.unpack("<I", data[0:4])[0]
        metadata_json = data[4:4 + metadata_length]
        audio_bytes = data[4 + metadata_length:]
        
        try:
            metadata = json.loads(metadata_json.decode("utf-8"))
        except json.JSONDecodeError:
            metadata = {}
        
        return {
            "type": "audio",
            "format": metadata.get("format", "wav"),
            "sampleRate": metadata.get("sample_rate", 24000),
            "data": base64.b64encode(audio_bytes).decode("ascii"),
        }
        
    elif marker == KEEPALIVE:
        return {"type": "keepalive"}
        
    elif marker == STOP_PLAYBACK:
        return {"type": "stop_playback"}
        
    else:
        return {
            "type": "unknown",
            "marker": f"0x{marker:08X}",
        }


async def read_backend_message(reader) -> Optional[bytes]:
    """
    Read a complete message from the backend TCP stream.
    
    Args:
        reader: asyncio StreamReader
        
    Returns:
        Complete binary message including header, or None if connection closed
    """
    try:
        header = await reader.readexactly(HEADER_SIZE)
    except Exception:
        return None
    
    marker, length = struct.unpack("<II", header)
    
    if length > 0:
        try:
            data = await reader.readexactly(length)
        except Exception:
            return None
    else:
        data = b""
    
    return header + data
