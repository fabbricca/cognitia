"""
Cognitia Core Orchestrator

The orchestrator sits in front of the AI processing pipelines and handles:
1. Communication type detection (text, audio, phone)
2. Parallel processing:
   - Thread 1: STT conversion if audio/phone, else passthrough
   - Thread 2: Context retrieval (conversation history, personas)
3. System prompt enrichment with retrieved context
4. LLM processing (streaming)
5. Response routing:
   - Text chat + short response → return text only
   - Text chat + long response → TTS (Kokoro + optional RVC)
   - Phone call → always TTS

This module does NOT handle authentication - all requests reaching here are trusted.
"""

import asyncio
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Optional, Any, Callable
import threading

import httpx
import numpy as np
from numpy.typing import NDArray
from loguru import logger

from ..ASR import get_audio_transcriber, TranscriberProtocol
from ..TTS import get_speech_synthesizer, SpeechSynthesizerProtocol
from ..utils import spoken_text_converter as stc


class CommunicationType(str, Enum):
    """Type of communication channel."""
    TEXT = "text"
    AUDIO = "audio"  # Voice messages
    PHONE = "phone"  # Real-time call


@dataclass
class UserContext:
    """User-specific context for personalization."""
    user_id: str
    username: Optional[str] = None
    persona: Optional[str] = None  # User's description/preferences
    timezone: Optional[str] = None
    language: str = "en"


@dataclass
class ModelContext:
    """AI model/character context."""
    model_id: str
    name: str
    system_prompt: str
    voice: str = "af_bella"
    rvc_model_path: Optional[str] = None
    rvc_index_path: Optional[str] = None
    rvc_enabled: bool = False


@dataclass
class ConversationContext:
    """Conversation state and history."""
    conversation_history: list[dict] = field(default_factory=list)
    summary: Optional[str] = None  # Summary of older messages
    entities: dict[str, Any] = field(default_factory=dict)  # Extracted entities
    last_n_messages: int = 20  # How many recent messages to include


@dataclass
class ProcessingContext:
    """Complete context assembled during parallel processing."""
    user_message: str  # Text message (after STT if was audio)
    user: UserContext
    model: ModelContext
    conversation: ConversationContext
    enriched_system_prompt: str = ""


@dataclass
class ProcessingRequest:
    """Request to process a message."""
    user_id: str
    model_id: str
    message: str  # Text or base64 audio
    communication_type: CommunicationType = CommunicationType.TEXT
    # Pre-fetched context (from entrance)
    system_prompt: str = "You are a helpful AI assistant."
    conversation_history: list[dict] = field(default_factory=list)
    user_persona: Optional[str] = None
    model_name: str = "Assistant"
    voice: str = "af_bella"
    rvc_model_path: Optional[str] = None
    rvc_index_path: Optional[str] = None
    rvc_enabled: bool = False
    # LLM settings
    temperature: float = 0.8
    max_tokens: int = 2048


@dataclass
class ProcessingResponse:
    """Response from processing a message."""
    type: str  # "text" or "audio"
    content: str  # Text content or base64 audio
    text_content: str = ""  # Always the text content (for logging/storage)
    sample_rate: int = 24000


class Orchestrator:
    """
    Main orchestrator for the Cognitia core.
    
    Handles the complete flow from input to output:
    1. Parallel STT + context fetching
    2. System prompt enrichment
    3. LLM processing
    4. Response routing (text vs audio)
    """
    
    # Threshold for short vs long responses
    SHORT_RESPONSE_THRESHOLD = 100  # characters
    
    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:latest",
        rvc_service_url: Optional[str] = "http://localhost:5050",
        default_voice: str = "af_bella",
        asr_engine: str = "ctc",
        max_workers: int = 4,
    ):
        """
        Initialize the orchestrator.
        
        Args:
            ollama_url: URL of the Ollama API
            ollama_model: Default LLM model to use
            rvc_service_url: URL of the RVC service (optional)
            default_voice: Default TTS voice
            asr_engine: ASR engine type ("ctc" or "tdt")
            max_workers: Thread pool size for parallel processing
        """
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.rvc_service_url = rvc_service_url
        self.default_voice = default_voice
        
        # Thread pool for parallel processing
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Lazy-loaded models
        self._asr_model: Optional[TranscriberProtocol] = None
        self._tts_models: dict[str, SpeechSynthesizerProtocol] = {}
        self._asr_engine = asr_engine
        self._model_lock = threading.Lock()
        
        # Spoken text converter (e.g., "12" -> "twelve")
        self._stc = stc.SpokenTextConverter()
        
        logger.info(f"Orchestrator initialized: LLM={ollama_model}, ASR={asr_engine}")
    
    # -------------------------------------------------------------------------
    # Model Loading (Lazy)
    # -------------------------------------------------------------------------
    
    def get_asr_model(self) -> TranscriberProtocol:
        """Get or load the ASR model (thread-safe, lazy)."""
        if self._asr_model is None:
            with self._model_lock:
                if self._asr_model is None:
                    logger.info(f"Loading ASR model ({self._asr_engine})...")
                    self._asr_model = get_audio_transcriber(engine_type=self._asr_engine)
                    logger.info("ASR model loaded")
        return self._asr_model
    
    def get_tts_model(self, voice: str) -> SpeechSynthesizerProtocol:
        """Get or load a TTS model for the given voice (thread-safe, lazy)."""
        if voice not in self._tts_models:
            with self._model_lock:
                if voice not in self._tts_models:
                    logger.info(f"Loading TTS model for voice: {voice}...")
                    self._tts_models[voice] = get_speech_synthesizer(voice)
                    logger.info(f"TTS model loaded for voice: {voice}")
        return self._tts_models[voice]
    
    # -------------------------------------------------------------------------
    # STT Processing (Thread 1)
    # -------------------------------------------------------------------------
    
    def transcribe_audio(self, audio_base64: str) -> str:
        """
        Convert audio to text using ASR.
        
        Args:
            audio_base64: Base64-encoded audio (PCM int16, 16kHz, mono)
            
        Returns:
            Transcribed text
        """
        asr = self.get_asr_model()
        
        try:
            # Decode base64 audio
            audio_bytes = base64.b64decode(audio_base64)
            
            # Convert to float32 normalized array
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Transcribe
            text = asr.transcribe(audio_array)
            logger.info(f"ASR transcription: {text}")
            return text
            
        except Exception as e:
            logger.error(f"ASR error: {e}")
            return ""
    
    def process_stt_if_needed(
        self,
        message: str,
        communication_type: CommunicationType
    ) -> str:
        """
        Thread 1: Convert audio to text if needed.
        
        Args:
            message: Text message or base64 audio
            communication_type: Type of communication
            
        Returns:
            Text message (transcribed if was audio)
        """
        if communication_type in (CommunicationType.AUDIO, CommunicationType.PHONE):
            return self.transcribe_audio(message)
        return message
    
    # -------------------------------------------------------------------------
    # Context Fetching (Thread 2)
    # -------------------------------------------------------------------------
    
    def fetch_context(self, request: ProcessingRequest) -> ProcessingContext:
        """
        Thread 2: Assemble all context for processing.
        
        This is where you'd add:
        - Database lookups for user/model info
        - Conversation memory retrieval
        - Entity extraction results
        - Summarization of old messages
        
        For now, we use the pre-fetched data from the request.
        
        Args:
            request: The processing request with pre-fetched context
            
        Returns:
            Complete processing context
        """
        # Build user context
        user = UserContext(
            user_id=request.user_id,
            persona=request.user_persona,
        )
        
        # Build model context
        model = ModelContext(
            model_id=request.model_id,
            name=request.model_name,
            system_prompt=request.system_prompt,
            voice=request.voice,
            rvc_model_path=request.rvc_model_path,
            rvc_index_path=request.rvc_index_path,
            rvc_enabled=request.rvc_enabled,
        )
        
        # Build conversation context
        conversation = ConversationContext(
            conversation_history=request.conversation_history,
        )
        
        return ProcessingContext(
            user_message="",  # Will be filled by STT thread
            user=user,
            model=model,
            conversation=conversation,
            enriched_system_prompt=request.system_prompt,
        )
    
    # -------------------------------------------------------------------------
    # System Prompt Enrichment
    # -------------------------------------------------------------------------
    
    def enrich_system_prompt(self, context: ProcessingContext) -> str:
        """
        Enrich the system prompt with context.
        
        Adds:
        - User persona information
        - Conversation summary
        - Extracted entities
        - Current date/time
        
        Args:
            context: The processing context
            
        Returns:
            Enriched system prompt
        """
        prompt_parts = [context.model.system_prompt]
        
        # Add conversation summary if available
        if context.conversation.summary:
            prompt_parts.append(f"\n\n[Previous conversation summary: {context.conversation.summary}]")
        
        # Add extracted entities if available
        if context.conversation.entities:
            entities_str = ", ".join(
                f"{k}: {v}" for k, v in context.conversation.entities.items()
            )
            prompt_parts.append(f"\n\n[Known information about the user: {entities_str}]")
        
        # Add user persona if available
        if context.user.persona:
            prompt_parts.append(f"\n\n[User preferences: {context.user.persona}]")
        
        return "".join(prompt_parts)
    
    # -------------------------------------------------------------------------
    # LLM Processing
    # -------------------------------------------------------------------------
    
    async def stream_llm_response(
        self,
        messages: list[dict],
        system_prompt: str,
        temperature: float = 0.8,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        Stream response from Ollama.
        
        Args:
            messages: Conversation messages
            system_prompt: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Yields:
            Text chunks as they're generated
        """
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        
        payload = {
            "model": self.ollama_model,
            "messages": full_messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.ollama_url}/api/chat",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                content = data.get("message", {}).get("content", "")
                                if content:
                                    yield content
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
        except httpx.HTTPError as e:
            logger.error(f"LLM HTTP error: {e}")
            yield f"[Error communicating with LLM: {e}]"
        except Exception as e:
            logger.error(f"LLM error: {e}")
            yield f"[LLM error: {e}]"
    
    async def get_full_llm_response(
        self,
        messages: list[dict],
        system_prompt: str,
        temperature: float = 0.8,
        max_tokens: int = 2048,
    ) -> str:
        """
        Get complete response from Ollama (non-streaming).
        
        Args:
            messages: Conversation messages
            system_prompt: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            Complete response text
        """
        full_response = ""
        async for chunk in self.stream_llm_response(
            messages, system_prompt, temperature, max_tokens
        ):
            full_response += chunk
        return full_response
    
    # -------------------------------------------------------------------------
    # TTS Processing
    # -------------------------------------------------------------------------
    
    def _split_text_for_tts(self, text: str, max_chars: int = 300) -> list[str]:
        """
        Split text into chunks suitable for TTS (under phoneme limit).
        
        Splits by sentences first, then by max_chars if needed.
        
        Args:
            text: Text to split
            max_chars: Maximum characters per chunk (conservative for phoneme limit)
            
        Returns:
            List of text chunks
        """
        import re
        
        # First, split by sentence boundaries
        sentence_pattern = r'(?<=[.!?])\s+'
        sentences = re.split(sentence_pattern, text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # If sentence itself is too long, split by commas or just by length
            if len(sentence) > max_chars:
                # Try splitting by commas
                parts = re.split(r',\s*', sentence)
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if len(part) > max_chars:
                        # Force split by length
                        for i in range(0, len(part), max_chars):
                            sub_part = part[i:i+max_chars].strip()
                            if sub_part:
                                chunks.append(sub_part)
                    elif len(current_chunk) + len(part) + 2 <= max_chars:
                        current_chunk = f"{current_chunk}, {part}" if current_chunk else part
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = part
            elif len(current_chunk) + len(sentence) + 1 <= max_chars:
                current_chunk = f"{current_chunk} {sentence}" if current_chunk else sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks if chunks else [text[:max_chars]]
    
    def synthesize_speech(
        self,
        text: str,
        voice: str,
    ) -> tuple[bytes, int]:
        """
        Convert text to speech. Handles long text by splitting into chunks.
        
        Args:
            text: Text to synthesize
            voice: Voice to use
            
        Returns:
            Tuple of (audio_bytes, sample_rate)
        """
        tts = self.get_tts_model(voice)
        
        # Convert text to spoken format (e.g., "12" -> "twelve")
        spoken_text = self._stc.text_to_spoken(text)
        
        # Split into chunks if text is long
        chunks = self._split_text_for_tts(spoken_text)
        
        all_audio = []
        for chunk in chunks:
            if not chunk.strip():
                continue
            try:
                audio_float = tts.generate_speech_audio(chunk)
                all_audio.append(audio_float)
            except ValueError as e:
                # If still too long, try smaller chunks
                logger.warning(f"TTS chunk too long, splitting further: {e}")
                sub_chunks = self._split_text_for_tts(chunk, max_chars=150)
                for sub_chunk in sub_chunks:
                    if sub_chunk.strip():
                        try:
                            audio_float = tts.generate_speech_audio(sub_chunk)
                            all_audio.append(audio_float)
                        except ValueError as e2:
                            logger.error(f"TTS failed for sub-chunk: {e2}")
        
        if not all_audio:
            # Return silence if nothing could be synthesized
            logger.error("No audio generated, returning silence")
            return np.zeros(tts.sample_rate, dtype=np.int16).tobytes(), tts.sample_rate
        
        # Concatenate all audio chunks
        combined_audio = np.concatenate(all_audio)
        
        # Convert to int16 bytes
        audio_int16 = (combined_audio * 32767).clip(-32768, 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()
        
        return audio_bytes, tts.sample_rate
    
    async def apply_rvc(
        self,
        audio_bytes: bytes,
        model_name: str,
        sample_rate: int = 24000,
    ) -> bytes:
        """
        Apply RVC voice conversion via external service.
        
        Args:
            audio_bytes: Input audio bytes
            model_name: RVC model name
            sample_rate: Audio sample rate
            
        Returns:
            Voice-converted audio bytes
        """
        if not self.rvc_service_url or not model_name:
            return audio_bytes
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.rvc_service_url}/convert",
                    files={"audio": ("audio.wav", audio_bytes, "audio/wav")},
                    data={
                        "model_name": model_name,
                        "sample_rate": sample_rate,
                    }
                )
                if response.status_code == 200:
                    logger.info(f"RVC conversion successful for model: {model_name}")
                    return response.content
                else:
                    logger.warning(f"RVC conversion failed: {response.status_code}")
                    return audio_bytes
        except Exception as e:
            logger.warning(f"RVC service unavailable: {e}")
            return audio_bytes
    
    # -------------------------------------------------------------------------
    # Main Processing Flow
    # -------------------------------------------------------------------------
    
    async def process(self, request: ProcessingRequest) -> ProcessingResponse:
        """
        Process a single message through the complete pipeline.
        
        Flow:
        1. PARALLEL:
           - Thread 1: STT if audio
           - Thread 2: Fetch context
        2. Enrich system prompt
        3. LLM generation
        4. Route response (text vs TTS)
        
        Args:
            request: The processing request
            
        Returns:
            Processing response (text or audio)
        """
        start_time = time.time()
        loop = asyncio.get_event_loop()
        
        # PARALLEL PROCESSING
        # Thread 1: STT if needed
        stt_future = loop.run_in_executor(
            self.executor,
            self.process_stt_if_needed,
            request.message,
            request.communication_type,
        )
        
        # Thread 2: Fetch context
        context_future = loop.run_in_executor(
            self.executor,
            self.fetch_context,
            request,
        )
        
        # Wait for both
        user_message, context = await asyncio.gather(stt_future, context_future)
        context.user_message = user_message
        
        logger.info(f"Parallel processing done in {time.time() - start_time:.2f}s")
        
        # Enrich system prompt
        context.enriched_system_prompt = self.enrich_system_prompt(context)
        
        # Build messages for LLM
        messages = context.conversation.conversation_history + [
            {"role": "user", "content": context.user_message}
        ]
        
        # Get LLM response
        llm_start = time.time()
        llm_response = await self.get_full_llm_response(
            messages,
            context.enriched_system_prompt,
            request.temperature,
            request.max_tokens,
        )
        logger.info(f"LLM response in {time.time() - llm_start:.2f}s: {len(llm_response)} chars")
        
        # Decide whether to use TTS
        use_tts = False
        if request.communication_type == CommunicationType.PHONE:
            use_tts = True
            logger.info("Using TTS: phone call mode")
        elif len(llm_response) > self.SHORT_RESPONSE_THRESHOLD:
            use_tts = True
            logger.info(f"Using TTS: long response ({len(llm_response)} > {self.SHORT_RESPONSE_THRESHOLD})")
        
        if use_tts:
            # Generate speech
            tts_start = time.time()
            audio_bytes, sample_rate = await loop.run_in_executor(
                self.executor,
                self.synthesize_speech,
                llm_response,
                context.model.voice,
            )
            logger.info(f"TTS done in {time.time() - tts_start:.2f}s")
            
            # Apply RVC if enabled
            if context.model.rvc_enabled and context.model.rvc_model_path:
                rvc_start = time.time()
                audio_bytes = await self.apply_rvc(
                    audio_bytes,
                    context.model.rvc_model_path,
                    sample_rate,
                )
                logger.info(f"RVC done in {time.time() - rvc_start:.2f}s")
            
            total_time = time.time() - start_time
            logger.info(f"Total processing time: {total_time:.2f}s")
            
            return ProcessingResponse(
                type="audio",
                content=base64.b64encode(audio_bytes).decode("ascii"),
                text_content=llm_response,
                sample_rate=sample_rate,
            )
        else:
            total_time = time.time() - start_time
            logger.info(f"Total processing time: {total_time:.2f}s")
            
            return ProcessingResponse(
                type="text",
                content=llm_response,
                text_content=llm_response,
            )
    
    async def process_streaming(
        self,
        request: ProcessingRequest,
        on_text_chunk: Callable[[str], Any],
        on_complete: Callable[[str], Any],
    ) -> ProcessingResponse:
        """
        Process a message with streaming LLM response.
        
        Args:
            request: The processing request
            on_text_chunk: Callback for each text chunk
            on_complete: Callback when complete
            
        Returns:
            Processing response (text or audio)
        """
        start_time = time.time()
        loop = asyncio.get_event_loop()
        
        # PARALLEL PROCESSING
        stt_future = loop.run_in_executor(
            self.executor,
            self.process_stt_if_needed,
            request.message,
            request.communication_type,
        )
        context_future = loop.run_in_executor(
            self.executor,
            self.fetch_context,
            request,
        )
        user_message, context = await asyncio.gather(stt_future, context_future)
        context.user_message = user_message
        
        # Enrich system prompt
        context.enriched_system_prompt = self.enrich_system_prompt(context)
        
        # Build messages for LLM
        messages = context.conversation.conversation_history + [
            {"role": "user", "content": context.user_message}
        ]
        
        # Stream LLM response
        full_response = ""
        async for chunk in self.stream_llm_response(
            messages,
            context.enriched_system_prompt,
            request.temperature,
            request.max_tokens,
        ):
            full_response += chunk
            await on_text_chunk(chunk)
        
        await on_complete(full_response)
        
        # Decide whether to use TTS
        use_tts = (
            request.communication_type == CommunicationType.PHONE or
            len(full_response) > self.SHORT_RESPONSE_THRESHOLD
        )
        
        if use_tts:
            audio_bytes, sample_rate = await loop.run_in_executor(
                self.executor,
                self.synthesize_speech,
                full_response,
                context.model.voice,
            )
            
            if context.model.rvc_enabled and context.model.rvc_model_path:
                audio_bytes = await self.apply_rvc(
                    audio_bytes,
                    context.model.rvc_model_path,
                    sample_rate,
                )
            
            return ProcessingResponse(
                type="audio",
                content=base64.b64encode(audio_bytes).decode("ascii"),
                text_content=full_response,
                sample_rate=sample_rate,
            )
        else:
            return ProcessingResponse(
                type="text",
                content=full_response,
                text_content=full_response,
            )
    
    def shutdown(self):
        """Shutdown the orchestrator and release resources."""
        logger.info("Shutting down orchestrator...")
        self.executor.shutdown(wait=True)
        logger.info("Orchestrator shutdown complete")


# Global orchestrator instance
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Get or create the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        import os
        _orchestrator = Orchestrator(
            ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:latest"),
            rvc_service_url=os.getenv("RVC_URL", "http://localhost:5050"),
            default_voice=os.getenv("DEFAULT_VOICE", "af_bella"),
            asr_engine=os.getenv("ASR_ENGINE", "ctc"),
        )
    return _orchestrator
