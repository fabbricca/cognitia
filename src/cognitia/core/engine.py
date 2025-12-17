"""
Core engine module for the Cognitia voice assistant.

This module provides the main orchestration classes including the Cognitia assistant,
configuration management, and component coordination.
"""

from pathlib import Path
import queue
import sys
import threading
import time

from loguru import logger
from pydantic import BaseModel, HttpUrl
import requests
import yaml

from ..ASR import TranscriberProtocol, get_audio_transcriber
from ..audio_io import AudioProtocol, get_audio_system
from ..TTS import SpeechSynthesizerProtocol, get_speech_synthesizer
from ..memory.conversation_memory import ConversationMemory
from ..memory.entity_memory import EntityMemory
from ..memory.combined_memory import CombinedMemory
from ..utils import spoken_text_converter as stc
from ..utils.resources import resource_path
from .audio_data import AudioMessage
from .llm_processor import LanguageModelProcessor
from .speech_listener import SpeechListener
from .speech_player import SpeechPlayer
from .tts_synthesizer import TextToSpeechSynthesizer
from .state import ThreadSafeConversationState

try:
    logger.remove(0)
except ValueError:
    pass  # Handler already removed
logger.add(sys.stderr, level="SUCCESS")


class PersonalityPrompt(BaseModel):
    """
    Represents a single personality prompt message for the assistant.

    Contains exactly one of: system, user, or assistant message content.
    Used to configure the assistant's personality and behavior.
    """

    system: str | None = None
    user: str | None = None
    assistant: str | None = None

    def to_chat_message(self) -> dict[str, str]:
        """Convert the prompt to a chat message format.

        Returns:
            dict[str, str]: A single chat message dictionary

        Raises:
            ValueError: If the prompt does not contain exactly one non-null field
        """
        fields = self.model_dump(exclude_none=True)
        if len(fields) != 1:
            raise ValueError("PersonalityPrompt must have exactly one non-null field")

        field, value = next(iter(fields.items()))
        return {"role": field, "content": value}


class MemoryConfig(BaseModel):
    """Configuration for conversation memory system."""

    enabled: bool = True
    max_turns: int = 50
    persist_path: str | None = None
    persist_interval_seconds: float = 30.0
    
    # Entity memory settings (async LLM extraction)
    entity_extraction_enabled: bool = True
    entity_persist_path: str | None = None

    class Config:
        extra = "ignore"


class RVCConfig(BaseModel):
    """Configuration for RVC voice cloning."""
    enabled: bool = False
    # Mode: "inline" (direct Python) or "service" (Docker API)
    mode: str = "service"  # service is recommended for stability
    # For inline mode:
    model_path: str | None = None
    index_path: str | None = None
    device: str = "cuda:0"
    # For service mode:
    service_url: str = "http://localhost:5050"
    model_name: str | None = None  # Model name in rvc_models directory
    # Common parameters:
    f0_method: str = "rmvpe"  # rmvpe, harvest, crepe, pm
    f0_up_key: int = 0  # Pitch shift in semitones
    index_rate: float = 0.5
    protect: float = 0.33


class CognitiaConfig(BaseModel):
    """
    Configuration model for the Cognitia voice assistant.

    Defines all necessary parameters for initializing the assistant including
    LLM settings, audio I/O backend, ASR/TTS engines, personality configuration,
    and memory settings.
    Supports loading from YAML files with nested key navigation.
    """

    llm_model: str
    completion_url: HttpUrl
    api_key: str | None
    interruptible: bool
    audio_io: str
    asr_engine: str
    wake_word: str | None
    voice: str
    announcement: str | None
    personality_preprompt: list[PersonalityPrompt]
    memory: MemoryConfig = MemoryConfig()
    # Network audio settings
    network_host: str = "0.0.0.0"
    network_port: int = 5555
    # RVC voice cloning settings
    rvc: RVCConfig = RVCConfig()
    # LLM sampling parameters to reduce repetition
    temperature: float = 0.8
    repeat_penalty: float = 1.15
    top_p: float = 0.9
    top_k: int = 40

    @classmethod
    def from_yaml(cls, path: str | Path, key_to_config: tuple[str, ...] = ("Glados",)) -> "CognitiaConfig":
        """
        Load a CognitiaConfig instance from a YAML configuration file.

        Parameters:
            path: Path to the YAML configuration file
            key_to_config: Tuple of keys to navigate nested configuration

        Returns:
            CognitiaConfig: Configuration object with validated settings

        Raises:
            ValueError: If the YAML content is invalid
            OSError: If the file cannot be read
            pydantic.ValidationError: If the configuration is invalid
        """
        path = Path(path)

        # Try different encodings
        for encoding in ["utf-8", "utf-8-sig"]:
            try:
                data = yaml.safe_load(path.read_text(encoding=encoding))
                break
            except UnicodeDecodeError:
                if encoding == "utf-8-sig":
                    raise ValueError(f"Could not decode YAML file {path} with any supported encoding")

        # Navigate through nested keys
        config = data
        for key in key_to_config:
            config = config[key]

        return cls.model_validate(config)

    def to_chat_messages(self) -> list[dict[str, str]]:
        """Convert personality preprompt to chat message format."""
        return [prompt.to_chat_message() for prompt in self.personality_preprompt]


class Cognitia:
    """
    Cognitia voice assistant orchestrator.
    This class manages the components of the Cognitia voice assistant, including speech recognition,
    language model processing, text-to-speech synthesis, and audio playback.
    It initializes the necessary components, starts background threads for processing, and provides
    methods for interaction with the assistant.
    """

    PAUSE_TIME: float = 0.05  # Time to wait between processing loops
    NEUROTOXIN_RELEASE_ALLOWED: bool = False  # preparation for function calling, see issue #13
    DEFAULT_PERSONALITY_PREPROMPT: tuple[dict[str, str], ...] = (
        {
            "role": "system",
            "content": "You are a helpful AI assistant. You are here to assist the user in their tasks.",
        },
    )

    def __init__(
        self,
        asr_model: TranscriberProtocol,
        tts_model: SpeechSynthesizerProtocol,
        audio_io: AudioProtocol,
        completion_url: HttpUrl,
        llm_model: str,
        api_key: str | None = None,
        interruptible: bool = True,
        wake_word: str | None = None,
        announcement: str | None = None,
        personality_preprompt: tuple[dict[str, str], ...] = DEFAULT_PERSONALITY_PREPROMPT,
        config: CognitiaConfig | None = None,
    ) -> None:
        """
        Initialize the Cognitia voice assistant with configuration parameters.

        This method sets up the voice recognition system, including voice activity detection (VAD),
        automatic speech recognition (ASR), text-to-speech (TTS), and language model processing.
        The initialization configures various components and starts background threads for
        processing LLM responses and TTS output.

        Args:
            asr_model (TranscriberProtocol): The ASR model for transcribing audio input.
            tts_model (SpeechSynthesizerProtocol): The TTS model for synthesizing spoken output.
            audio_io (AudioProtocol): The audio input/output system to use.
            completion_url (HttpUrl): The URL for the LLM completion endpoint.
            llm_model (str): The name of the LLM model to use.
            api_key (str | None): API key for accessing the LLM service, if required.
            interruptible (bool): Whether the assistant can be interrupted while speaking.
            wake_word (str | None): Optional wake word to trigger the assistant.
            announcement (str | None): Optional announcement to play on startup.
            personality_preprompt (tuple[dict[str, str], ...]): Initial personality preprompt messages.
            config (CognitiaConfig | None): Configuration object for memory and other settings.
        """
        self._asr_model = asr_model
        self._tts = tts_model
        self.completion_url = completion_url
        self.llm_model = llm_model
        self.api_key = api_key
        self.interruptible = interruptible
        self.wake_word = wake_word
        self.announcement = announcement

        # Convert personality preprompt to initial messages
        initial_messages = [msg for msg in personality_preprompt]
        self._messages = ThreadSafeConversationState(initial_messages)

        # Initialize spoken text converter, that converts text to spoken text. eg. 12 -> "twelve"
        self._stc = stc.SpokenTextConverter()

        # warm up onnx ASR model, this is needed to avoid long pauses on first request
        self._asr_model.transcribe_file(resource_path("data/0.wav"))

        # Initialize events for thread synchronization
        self.processing_active_event = threading.Event()  # Indicates if input processing is active (ASR + LLM + TTS)
        self.currently_speaking_event = threading.Event()  # Indicates if the assistant is currently speaking
        self.shutdown_event = threading.Event()  # Event to signal shutdown of all threads
        
        # Store config for LLM caller creation
        self._config = config

        # Initialize queues for inter-thread communication
        self.llm_queue: queue.Queue[str] = queue.Queue()  # Text from SpeechListener to LLMProcessor
        self.tts_queue: queue.Queue[str] = queue.Queue()  # Text from LLMProcessor to TTSynthesizer
        self.audio_queue: queue.Queue[AudioMessage] = queue.Queue()  # AudioMessages from TTSSynthesizer to AudioPlayer

        # Initialize audio input/output system
        self.audio_io: AudioProtocol = audio_io
        logger.info("Audio input started successfully.")

        # Initialize memory systems
        self.conversation_memory: ConversationMemory | None = None
        self.entity_memory: EntityMemory | None = None
        self.combined_memory: CombinedMemory | None = None

        if config and config.memory.enabled:
            # Set up persistence paths
            conv_persist_path = Path(config.memory.persist_path) if config.memory.persist_path else Path("data/conversation_memory.json")
            entity_persist_path = Path(config.memory.entity_persist_path) if config.memory.entity_persist_path else Path("data/entity_memory.json")

            # Create LLM caller for async extraction (uses same endpoint as main LLM)
            llm_caller = self._create_llm_caller() if config.memory.entity_extraction_enabled else None

            # v2.1+: Get user_id from connection context if using network audio with auth
            user_id = None
            if hasattr(self.audio_io, 'get_connection_context'):
                conn_context = self.audio_io.get_connection_context()
                if conn_context:
                    user_id = conn_context.user_id
                    logger.info(f"Multi-user memory enabled for user: {user_id}")

            # Initialize conversation memory
            self.conversation_memory = ConversationMemory(
                max_turns=config.memory.max_turns,
                persist_path=conv_persist_path,
                persist_interval=config.memory.persist_interval_seconds,
                llm_summarizer=llm_caller,  # For async summarization
                user_id=user_id,  # v2.1+: Multi-user isolation
            )

            # Initialize entity memory if enabled
            if config.memory.entity_extraction_enabled:
                self.entity_memory = EntityMemory(
                    persist_path=entity_persist_path,
                    llm_caller=llm_caller,
                    user_id=user_id,  # v2.1+: Multi-user isolation
                )
                logger.info("Entity memory initialized with async LLM extraction")

            # Create combined memory interface
            self.combined_memory = CombinedMemory(
                conversation_memory=self.conversation_memory,
                entity_memory=self.entity_memory,
            )

            logger.info(f"Memory system initialized: {config.memory.max_turns} max turns, entity extraction: {config.memory.entity_extraction_enabled}")

        # Initialize threads for each component
        self.component_threads: list[threading.Thread] = []

        self.speech_listener = SpeechListener(
            audio_io=self.audio_io,
            llm_queue=self.llm_queue,
            asr_model=self._asr_model,
            wake_word=self.wake_word,
            interruptible=self.interruptible,
            shutdown_event=self.shutdown_event,
            currently_speaking_event=self.currently_speaking_event,
            processing_active_event=self.processing_active_event,
            pause_time=self.PAUSE_TIME,
        )

        self.llm_processor = LanguageModelProcessor(
            llm_input_queue=self.llm_queue,
            tts_input_queue=self.tts_queue,
            conversation_history=self._messages,  # Shared, to be refactored
            completion_url=self.completion_url,
            model_name=self.llm_model,
            api_key=self.api_key,
            processing_active_event=self.processing_active_event,
            shutdown_event=self.shutdown_event,
            pause_time=self.PAUSE_TIME,
            conversation_memory=self.conversation_memory,
            combined_memory=self.combined_memory,
            temperature=config.temperature if config else 0.8,
            repeat_penalty=config.repeat_penalty if config else 1.15,
            top_p=config.top_p if config else 0.9,
            top_k=config.top_k if config else 40,
            audio_io=self.audio_io,  # v2.1+: For getting connection context (user_id)
        )

        self.tts_synthesizer = TextToSpeechSynthesizer(
            tts_input_queue=self.tts_queue,
            audio_output_queue=self.audio_queue,
            tts_model=self._tts,
            stc_instance=self._stc,
            shutdown_event=self.shutdown_event,
            pause_time=self.PAUSE_TIME,
        )

        self.speech_player = SpeechPlayer(
            audio_io=self.audio_io,
            audio_output_queue=self.audio_queue,
            conversation_history=self._messages,  # Shared, to be refactored
            tts_sample_rate=self._tts.sample_rate,
            shutdown_event=self.shutdown_event,
            currently_speaking_event=self.currently_speaking_event,
            processing_active_event=self.processing_active_event,
            pause_time=self.PAUSE_TIME,
        )

        thread_targets = {
            "SpeechListener": self.speech_listener.run,
            "LLMProcessor": self.llm_processor.run,
            "TTSSynthesizer": self.tts_synthesizer.run,
            "AudioPlayer": self.speech_player.run,
        }

        for name, target_func in thread_targets.items():
            thread = threading.Thread(target=target_func, name=name, daemon=True)
            self.component_threads.append(thread)
            thread.start()
            logger.info(f"Orchestrator: {name} thread started.")
        
        # Start text message handler for network mode
        if hasattr(self.audio_io, 'get_text_message_queue'):
            text_thread = threading.Thread(
                target=self._text_message_handler,
                name="TextMessageHandler",
                daemon=True
            )
            self.component_threads.append(text_thread)
            text_thread.start()
            logger.info("Orchestrator: TextMessageHandler thread started.")
    
    def _create_llm_caller(self) -> callable:
        """
        Create a synchronous LLM caller function for background tasks.
        
        This is used by entity extraction and summarization which run
        in background threads during idle time. Uses the same LLM endpoint
        as the main conversation.
        
        Returns:
            A callable that takes a prompt string and returns the LLM response.
        """
        completion_url = str(self.completion_url)
        model_name = self.llm_model
        api_key = self.api_key
        
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        def llm_caller(prompt: str) -> str:
            """Call LLM synchronously for background extraction tasks."""
            try:
                data = {
                    "model": model_name,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that extracts information accurately. Respond only with the requested format."},
                        {"role": "user", "content": prompt}
                    ],
                }
                
                response = requests.post(
                    completion_url,
                    headers=headers,
                    json=data,
                    timeout=10,  # Short timeout for background tasks
                )
                response.raise_for_status()
                
                result = response.json()
                
                # Handle Ollama format
                if "message" in result:
                    return result["message"].get("content", "")
                # Handle OpenAI format  
                elif "choices" in result:
                    return result["choices"][0].get("message", {}).get("content", "")
                
                return ""
                
            except Exception as e:
                logger.debug(f"Background LLM call failed: {e}")
                return ""
        
        return llm_caller

    def _text_message_handler(self) -> None:
        """Handle text messages from network client.
        
        Monitors the text message queue from NetworkAudioIO and forwards
        messages to the LLM queue for processing. Also sends response text
        back to the client.
        """
        text_queue = self.audio_io.get_text_message_queue()
        
        while not self.shutdown_event.is_set():
            try:
                # Wait for text message with timeout
                text = text_queue.get(timeout=self.PAUSE_TIME)
                
                logger.success(f"TextMessageHandler: Processing text: '{text}'")
                
                # Set processing active so LLM will respond
                self.processing_active_event.set()
                
                # Put text in LLM queue (same as ASR output)
                self.llm_queue.put(text)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"TextMessageHandler error: {e}")

    def play_announcement(self, interruptible: bool | None = None) -> None:
        """
        Play the announcement using text-to-speech (TTS) synthesis.

        This method checks if an announcement is set and, if so, places it in the TTS queue for processing.
        If the `interruptible` parameter is set to `True`, it allows the announcement to be interrupted by other
        audio playback. If `interruptible` is `None`, it defaults to the instance's `interruptible` setting.

        Args:
            interruptible (bool | None): Whether the announcement can be interrupted by other audio playback.
                If `None`, it defaults to the instance's `interruptible` setting.
        """

        if interruptible is None:
            interruptible = self.interruptible
        logger.success("Playing announcement...")
        if self.announcement:
            self.tts_queue.put(self.announcement)
            self.processing_active_event.set()

    @property
    def messages(self) -> list[dict[str, str]]:
        """
        Retrieve the current list of conversation messages.

        Returns:
            list[dict[str, str]]: A list of message dictionaries representing the conversation history.
        """
        return self._messages

    def get_memory_stats(self) -> dict[str, any]:
        """
        Get statistics about the conversation memory system.

        Returns:
            dict: Memory statistics including turn count, memory usage, etc.
        """
        if not self.conversation_memory:
            return {"enabled": False}

        stats = self.conversation_memory.get_stats()
        return {
            "enabled": True,
            "turns_stored": stats["total_turns"],
            "max_turns": stats["max_turns"],
            "memory_usage_mb": stats["memory_usage_mb"],
            "persist_path": str(self.conversation_memory.persist_path) if self.conversation_memory.persist_path else None,
        }

    def clear_memory(self) -> bool:
        """
        Clear all conversation memory.

        Returns:
            bool: True if memory was cleared successfully, False if memory is disabled.
        """
        if not self.conversation_memory:
            return False

        self.conversation_memory.clear_memory()
        logger.info("Conversation memory cleared")
        return True

    def export_memory(self, filepath: str | Path) -> bool:
        """
        Export conversation memory to a file.

        Args:
            filepath: Path to export memory to

        Returns:
            bool: True if export was successful
        """
        if not self.conversation_memory:
            return False

        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Get all conversation turns
            turns = list(self.conversation_memory._turns)

            # Export as JSON
            data = {
                "exported_at": time.time(),
                "turns": [turn.to_dict() for turn in turns],
                "metadata": {
                    "total_turns": len(turns),
                    "max_turns": self.conversation_memory.max_turns,
                }
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Memory exported to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to export memory: {e}")
            return False

    @classmethod
    def from_config(cls, config: CognitiaConfig) -> "Cognitia":
        """
        Create a Cognitia instance from a CognitiaConfig configuration object.

        Parameters:
            config (CognitiaConfig): Configuration object containing Cognitia initialization parameters

        Returns:
            Glados: A new Cognitia instance configured with the provided settings
        """

        asr_model = get_audio_transcriber(
            engine_type=config.asr_engine,
        )

        tts_model: SpeechSynthesizerProtocol
        if config.rvc.enabled:
            if config.rvc.mode == "service":
                # Use RVC Docker service
                logger.info(f"RVC service mode enabled: {config.rvc.service_url}")
                from ..TTS.rvc_service import RVCServiceClient, RVCServiceSynthesizer
                
                base_tts = get_speech_synthesizer(config.voice)
                rvc_client = RVCServiceClient(
                    service_url=config.rvc.service_url,
                    model_name=config.rvc.model_name,
                )
                rvc_client.set_params(
                    f0_method=config.rvc.f0_method,
                    f0_up_key=config.rvc.f0_up_key,
                    index_rate=config.rvc.index_rate,
                    protect=config.rvc.protect,
                )
                tts_model = RVCServiceSynthesizer(base_tts, rvc_client)
                
            elif config.rvc.mode == "inline" and config.rvc.model_path:
                # Use inline RVC (requires rvc-python installed locally)
                logger.info(f"RVC inline mode enabled: {config.rvc.model_path}")
                tts_model = get_speech_synthesizer(
                    voice=config.voice,
                    rvc_model_path=config.rvc.model_path,
                    rvc_index_path=config.rvc.index_path,
                    rvc_device=config.rvc.device,
                    rvc_f0_method=config.rvc.f0_method,
                    rvc_f0_up_key=config.rvc.f0_up_key,
                    index_rate=config.rvc.index_rate,
                    protect=config.rvc.protect,
                )
            else:
                logger.warning("RVC enabled but no model configured, using base TTS")
                tts_model = get_speech_synthesizer(config.voice)
        else:
            tts_model = get_speech_synthesizer(config.voice)

        audio_io = get_audio_system(
            backend_type=config.audio_io,
            network_host=config.network_host,
            network_port=config.network_port,
        )

        return cls(
            asr_model=asr_model,
            tts_model=tts_model,
            audio_io=audio_io,
            completion_url=config.completion_url,
            llm_model=config.llm_model,
            api_key=config.api_key,
            interruptible=config.interruptible,
            wake_word=config.wake_word,
            announcement=config.announcement,
            personality_preprompt=tuple(config.to_chat_messages()),
            config=config,
        )

    @classmethod
    def from_yaml(cls, path: str) -> "Cognitia":
        """
        Create a Cognitia instance from a configuration file.

        Parameters:
            path (str): Path to the YAML configuration file containing Glados settings.

        Returns:
            Glados: A new Cognitia instance configured with settings from the specified YAML file.

        Example:
            cognitia = Cognitia.from_yaml('config/default.yaml')
        """
        return cls.from_config(CognitiaConfig.from_yaml(path))

    def run(self) -> None:
        """
        Start the voice assistant's listening event loop, continuously processing audio input.
        This method initializes the audio input system, starts listening for audio samples,
        and enters a loop that waits for audio input until a shutdown event is triggered.
        It handles keyboard interrupts gracefully and ensures that all components are properly shut down.

        This method is the main entry point for running the Cognitia voice assistant.
        """
        try:
            self.audio_io.start_listening()
            logger.success("Audio Modules Operational")
            logger.success("Listening...")
        except Exception as e:
            logger.error(f"Failed to start audio input: {e}")
            import traceback
            logger.error(f"Audio startup traceback: {traceback.format_exc()}")
            return

        # Loop forever, but is 'paused' when new samples are not available
        try:
            loop_count = 0
            while not self.shutdown_event.is_set():  # Check event BEFORE blocking get
                time.sleep(self.PAUSE_TIME)
                loop_count += 1
                if loop_count % 20 == 0:  # Check every 1 second (20 * 0.05)
                    # Check if component threads are still alive
                    alive_threads = [t.name for t in self.component_threads if t.is_alive()]
                    dead_threads = [t.name for t in self.component_threads if not t.is_alive()]
                    if dead_threads:
                        logger.error(f"Component threads died: {dead_threads}")
                        logger.error(f"Alive threads: {alive_threads}")
                        logger.error("Shutting down due to dead threads")
                        self.shutdown_event.set()  # Shutdown if threads died
                        break  # Exit the loop immediately
            logger.info("Shutdown event detected in listen loop, exiting loop.")

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt in main run loop.")
            # Make sure any ongoing audio playback is stopped
            if self.currently_speaking_event.is_set():
                for component in self.component_threads:
                    if component.name == "AudioPlayer":
                        self.audio_io.stop_speaking()
                        self.currently_speaking_event.clear()
                        break
            self.shutdown_event.set()
            # Give threads a moment to notice the shutdown event
            time.sleep(self.PAUSE_TIME)
        finally:
            logger.info("Listen event loop is stopping/exiting.")
            sys.exit(0)


if __name__ == "__main__":
    cognitia_config = CognitiaConfig.from_yaml("cognitia_config.yaml")
    cognitia = Cognitia.from_config(cognitia_config)
    cognitia.run()
