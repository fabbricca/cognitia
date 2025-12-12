# --- llm_processor.py ---
import json
import queue
import re
import threading
import time
from typing import Any, ClassVar, Optional

from loguru import logger
from pydantic import HttpUrl  # If HttpUrl is used by config
import requests

from ..memory.conversation_memory import ConversationMemory
from ..memory.combined_memory import CombinedMemory
from .exceptions import (
    LLMConnectionError,
    LLMTimeoutError,
    LLMResponseError,
    LLMStreamError,
)
from .state import ThreadSafeConversationState
from .resilience import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpen


class LanguageModelProcessor:
    """
    A thread that processes text input for a language model, streaming responses and sending them to TTS.
    This class is designed to run in a separate thread, continuously checking for new text to process
    until a shutdown event is set. It handles conversation history, manages streaming responses,
    and sends synthesized sentences to a TTS queue.
    """

    PUNCTUATION_SET: ClassVar[set[str]] = {".", "!", "?", ":", ";", "?!", "\n", "\n\n"}

    def __init__(
        self,
        llm_input_queue: queue.Queue[str],
        tts_input_queue: queue.Queue[str],
        conversation_history: ThreadSafeConversationState,
        completion_url: HttpUrl,
        model_name: str,  # Renamed from 'model' to avoid conflict
        api_key: str | None,
        processing_active_event: threading.Event,  # To check if we should stop streaming
        shutdown_event: threading.Event,
        pause_time: float = 0.05,
        conversation_memory: ConversationMemory | None = None,
        combined_memory: Optional[CombinedMemory] = None,
        temperature: float = 0.8,
        repeat_penalty: float = 1.15,
        top_p: float = 0.9,
        top_k: int = 40,
        audio_io: Optional[Any] = None,  # v2.1+: For getting connection context (user_id)
    ) -> None:
        self.llm_input_queue = llm_input_queue
        self.tts_input_queue = tts_input_queue
        self.conversation_history = conversation_history
        self.completion_url = completion_url
        self.model_name = model_name
        self.api_key = api_key
        self.processing_active_event = processing_active_event
        self.shutdown_event = shutdown_event
        self.pause_time = pause_time
        self.conversation_memory = conversation_memory
        self.combined_memory = combined_memory
        self.audio_io = audio_io  # v2.1+: For multi-user support

        # LLM sampling parameters to reduce repetition
        self.temperature = temperature
        self.repeat_penalty = repeat_penalty
        self.top_p = top_p
        self.top_k = top_k

        # Maximum conversation turns to send to LLM (excluding system/few-shot prompts)
        self.max_conversation_turns = 6  # 6 user+assistant pairs = 12 messages

        self.prompt_headers = {"Content-Type": "application/json"}
        if api_key:
            self.prompt_headers["Authorization"] = f"Bearer {api_key}"

        # Track last sent sentence to prevent duplicates
        self._last_sent_sentence: str = ""

        # Initialize circuit breaker for LLM calls
        self.llm_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="llm_service",
                failure_threshold=3,        # Open after 3 failures
                recovery_timeout=30.0,      # Try recovery after 30s
                success_threshold=2,        # Close after 2 successes
            )
        )

    def _clean_raw_bytes(self, line: bytes) -> dict[str, str] | None:
        """
        Clean and parse a raw byte line from the LLM response.
        Handles both OpenAI and Ollama formats, returning a dictionary or None if parsing fails.

        Args:
            line (bytes): The raw byte line from the LLM response.
        Returns:
            dict[str, str] | None: Parsed JSON dictionary or None if parsing fails.
        """
        try:
            # Handle OpenAI format
            if line.startswith(b"data: "):
                json_str = line.decode("utf-8")[6:]
                if json_str.strip() == "[DONE]":  # Handle OpenAI [DONE] marker
                    return {"done_marker": "True"}
                parsed_json: dict[str, Any] = json.loads(json_str)
                return parsed_json
            # Handle Ollama format
            else:
                parsed_json = json.loads(line.decode("utf-8"))
                if isinstance(parsed_json, dict):
                    return parsed_json
                return None
        except json.JSONDecodeError:
            # If it's not JSON, it might be Ollama's final summary object which isn't part of the stream
            # Or just noise.
            logger.trace(
                f"LLM Processor: Failed to parse non-JSON server response line: "
                f"{line[:100].decode('utf-8', errors='replace')}"
            )  # Log only a part
            return None
        except Exception as e:
            logger.warning(
                f"LLM Processor: Failed to parse server response: {e} for line: "
                f"{line[:100].decode('utf-8', errors='replace')}"
            )
            return None

    def _process_chunk(self, line: dict[str, Any]) -> str | None:
        # Copy from Cognitia._process_chunk
        if not line or not isinstance(line, dict):
            return None
        try:
            # Handle OpenAI format
            if line.get("done_marker"):  # Handle [DONE] marker
                return None
            elif "choices" in line:  # OpenAI format
                content = line.get("choices", [{}])[0].get("delta", {}).get("content")
                return str(content) if content else None
            # Handle Ollama format
            else:
                content = line.get("message", {}).get("content")
                return content if content else None
        except Exception as e:
            logger.error(f"LLM Processor: Error processing chunk: {e}, chunk: {line}")
            return None

    def _process_sentence_for_tts(self, current_sentence_parts: list[str]) -> None:
        """
        Process the current sentence parts and send the complete sentence to the TTS queue.
        Cleans up the sentence by removing unwanted characters and formatting it for TTS.
        Args:
            current_sentence_parts (list[str]): List of sentence parts to be processed.
        """
        sentence = "".join(current_sentence_parts)
        sentence = re.sub(r"\*.*?\*|\(.*?\)", "", sentence)
        sentence = sentence.replace("\n\n", ". ").replace("\n", ". ").replace("  ", " ").replace(":", " ")
        sentence = sentence.strip()

        if sentence and sentence != ".":  # Avoid sending just a period
            # Deduplicate: check if this sentence is essentially the same as the last one
            normalized_current = sentence.rstrip('.!?').lower()
            normalized_last = self._last_sent_sentence.rstrip('.!?').lower()
            
            if normalized_current and normalized_current != normalized_last:
                logger.info(f"LLM Processor: Sending to TTS queue: '{sentence}'")
                self.tts_input_queue.put(sentence)
                self._last_sent_sentence = sentence
            else:
                logger.debug(f"LLM Processor: Skipping duplicate sentence: '{sentence}'")

    def run(self) -> None:
        """
        Starts the main loop for the LanguageModelProcessor thread.

        This method continuously checks the LLM input queue for text to process.
        It processes the text, sends it to the LLM API, and streams the response.
        It handles conversation history, manages streaming responses, and sends synthesized sentences
        to a TTS queue. The thread will run until the shutdown event is set, at which point it will exit gracefully.
        """
        logger.info("LanguageModelProcessor thread started.")
        while not self.shutdown_event.is_set():
            try:
                detected_text = self.llm_input_queue.get(timeout=self.pause_time)
                if not self.processing_active_event.is_set():  # Check if we were interrupted before starting
                    logger.info("LLM Processor: Interruption signal active, discarding LLM request.")
                    # Ensure EOS is sent if a previous stream was cut short by this interruption
                    # This logic might need refinement based on state. For now, assume no prior stream.
                    continue

                # Signal that conversation is active (pause background extraction)
                if self.combined_memory:
                    self.combined_memory.on_conversation_start()

                import time as _time
                _start_time = _time.time()
                
                # Reset duplicate sentence tracker for new conversation turn
                self._last_sent_sentence = ""
                
                logger.success(f"LLM Processor: Received text for LLM: '{detected_text}'")
                self.conversation_history.add_message("user", detected_text)

                # Get thread-safe snapshot of conversation history
                all_messages = self.conversation_history.get_messages(as_dict=True)

                # Prepare messages for LLM with conversation context
                # Separate system/few-shot prompts from actual conversation turns
                system_fewshot = []
                conversation_turns = []

                for msg in all_messages:
                    # System messages and early assistant/user examples are kept as prompts
                    if msg["role"] == "system":
                        system_fewshot.append(msg)
                    elif len(conversation_turns) == 0 and len(system_fewshot) > 0:
                        # Few-shot examples following system prompt
                        # Check if this looks like a few-shot example (short, template-like)
                        content_len = len(msg.get("content", ""))
                        if content_len < 200 and any(
                            q in msg.get("content", "").lower() 
                            for q in ["how do i", "what should", "what game"]
                        ):
                            system_fewshot.append(msg)
                        else:
                            conversation_turns.append(msg)
                    else:
                        conversation_turns.append(msg)
                
                # Limit conversation turns (keep last N * 2 messages for N turns)
                max_messages = self.max_conversation_turns * 2
                if len(conversation_turns) > max_messages:
                    conversation_turns = conversation_turns[-max_messages:]
                    logger.debug(f"LLM Processor: Trimmed conversation to {max_messages} messages")
                
                messages_for_llm = system_fewshot + conversation_turns
                logger.debug(f"LLM Processor: {len(system_fewshot)} system/fewshot + {len(conversation_turns)} conversation messages")

                # Use combined memory if available (includes entity context + conversation history)
                if self.combined_memory:
                    try:
                        memory_context = self.combined_memory.build_context_messages(max_turns=10)
                        # Insert memory context after system prompt but before current conversation
                        system_messages = [msg for msg in messages_for_llm if msg["role"] == "system"]
                        other_messages = [msg for msg in messages_for_llm if msg["role"] != "system"]

                        # Reconstruct messages: system + memory context + current conversation
                        messages_for_llm = system_messages + memory_context + other_messages

                        logger.debug(f"LLM Processor: Added {len(memory_context)} memory context messages")
                    except Exception as e:
                        logger.warning(f"LLM Processor: Failed to retrieve memory context: {e}")
                # Fallback to basic conversation memory
                elif self.conversation_memory:
                    try:
                        memory_context = self.conversation_memory.get_context_as_messages(max_turns=10)
                        system_messages = [msg for msg in messages_for_llm if msg["role"] == "system"]
                        other_messages = [msg for msg in messages_for_llm if msg["role"] != "system"]
                        messages_for_llm = system_messages + memory_context + other_messages
                        logger.debug(f"LLM Processor: Added {len(memory_context)} memory context messages")
                    except Exception as e:
                        logger.warning(f"LLM Processor: Failed to retrieve memory context: {e}")

                data = {
                    "model": self.model_name,
                    "stream": True,
                    "messages": messages_for_llm,
                    "options": {
                        "repeat_penalty": 1.2,  # Discourage repetition
                        "temperature": 0.8,     # Increase creativity slightly
                        "top_k": 40,
                        "top_p": 0.9,
                    }
                }
                
                # Log the context being sent for debugging
                if len(messages_for_llm) > 0:
                    last_msg = messages_for_llm[-1]
                    logger.debug(f"LLM Context Last Msg: {last_msg.get('role')}: {last_msg.get('content')[:50]}...")
                
                logger.success(f"LLM Processor: Memory context built in {(_time.time() - _start_time)*1000:.0f}ms, sending {len(messages_for_llm)} messages to LLM")

                sentence_buffer: list[str] = []
                assistant_response_buffer: list[str] = []  # Accumulate full response for memory
                try:
                    # Execute with circuit breaker protection
                    def make_llm_request():
                        response = requests.post(
                            str(self.completion_url),
                            headers=self.prompt_headers,
                            json=data,
                            stream=True,
                            timeout=30,
                        )
                        response.raise_for_status()
                        return response

                    with self.llm_breaker.call(make_llm_request) as response:
                        _first_token_time = None
                        logger.debug("LLM Processor: Request to LLM successful, processing stream...")
                        for line in response.iter_lines():
                            if _first_token_time is None:
                                _first_token_time = _time.time()
                                logger.success(f"LLM Processor: First token in {(_first_token_time - _start_time)*1000:.0f}ms")
                            
                            if not self.processing_active_event.is_set() or self.shutdown_event.is_set():
                                logger.info("LLM Processor: Interruption or shutdown detected during LLM stream.")
                                break  # Stop processing stream

                            if line:
                                cleaned_line_data = self._clean_raw_bytes(line)
                                if cleaned_line_data:
                                    chunk = self._process_chunk(cleaned_line_data)
                                    if chunk:  # Chunk can be an empty string, but None means no actual content
                                        sentence_buffer.append(chunk)
                                        assistant_response_buffer.append(chunk)  # Accumulate for memory

                                        # Split on defined punctuation or if chunk itself is punctuation
                                        if chunk.strip() in self.PUNCTUATION_SET and (
                                            len(sentence_buffer) < 2 or not sentence_buffer[-2].strip().isdigit()
                                        ):
                                            self._process_sentence_for_tts(sentence_buffer)
                                            sentence_buffer = []
                                    # OpenAI [DONE]
                                    elif cleaned_line_data.get("done_marker"):  # OpenAI [DONE]
                                        break
                                    # Ollama end
                                    elif cleaned_line_data.get("done") and cleaned_line_data.get("response") == "":
                                        break

                        # After loop, process any remaining buffer content if not interrupted
                        if self.processing_active_event.is_set() and sentence_buffer:
                            self._process_sentence_for_tts(sentence_buffer)

                        # Store conversation turn in memory (only if successful response)
                        if assistant_response_buffer:
                            full_assistant_response = "".join(assistant_response_buffer).strip()
                            
                            # Note: conversation_history is updated by speech_player when EOS is processed
                            # to ensure it only includes actually spoken content
                            
                            # v2.1+: Get user_id from connection context if available
                            user_id = None
                            if self.audio_io and hasattr(self.audio_io, 'get_connection_context'):
                                try:
                                    conn_context = self.audio_io.get_connection_context()
                                    if conn_context:
                                        user_id = conn_context.user_id
                                except Exception:
                                    pass  # Connection context not available, continue without user_id

                            # Use combined memory if available (handles both conversation + entity extraction)
                            if self.combined_memory:
                                try:
                                    self.combined_memory.add_exchange(
                                        user_input=detected_text,
                                        assistant_response=full_assistant_response,
                                        user_id=user_id,  # v2.1+: Pass user_id for multi-user isolation
                                    )
                                    logger.debug("LLM Processor: Stored exchange in combined memory")
                                except Exception as e:
                                    logger.warning(f"LLM Processor: Failed to store in combined memory: {e}")
                            # Fallback to basic conversation memory
                            elif self.conversation_memory:
                                try:
                                    self.conversation_memory.add_turn(
                                        user_input=detected_text,
                                        assistant_response=full_assistant_response,
                                        conversation_id="default",
                                        user_id=user_id,  # v2.1+: Pass user_id for multi-user isolation
                                    )
                                    logger.debug("LLM Processor: Stored conversation turn in memory")
                                except Exception as e:
                                    logger.warning(f"LLM Processor: Failed to store conversation in memory: {e}")

                except CircuitBreakerOpen as e:
                    logger.error(str(e))
                    self.tts_input_queue.put(
                        f"My thinking module is temporarily unavailable. "
                        f"I'll try again in {int(e.retry_after)} seconds."
                    )
                except requests.exceptions.ConnectionError as e:
                    error = LLMConnectionError(str(self.completion_url), e)
                    logger.error(str(error))
                    self.tts_input_queue.put(
                        "I'm unable to connect to my thinking module. Please check the LLM service connection."
                    )
                except requests.exceptions.Timeout as e:
                    error = LLMTimeoutError(30.0, str(self.completion_url))
                    logger.error(str(error))
                    self.tts_input_queue.put("My brain seems to be taking too long to respond. It might be overloaded.")
                except requests.exceptions.HTTPError as e:
                    status_code = (
                        e.response.status_code
                        if hasattr(e, "response") and hasattr(e.response, "status_code")
                        else 500
                    )
                    response_text = (
                        e.response.text
                        if hasattr(e, "response") and hasattr(e.response, "text")
                        else str(e)
                    )
                    error = LLMResponseError(status_code, response_text, str(self.completion_url))
                    logger.error(str(error))
                    self.tts_input_queue.put(f"I received an error from my thinking module. HTTP status {status_code}.")
                except requests.exceptions.RequestException as e:
                    # Wrap in generic LLM exception
                    error = LLMConnectionError(str(self.completion_url), e)
                    logger.error(f"LLM Processor: Request to LLM failed: {error}")
                    self.tts_input_queue.put("Sorry, I encountered an error trying to reach my brain.")
                except Exception as e:
                    logger.exception(f"LLM Processor: Unexpected error during LLM request/streaming: {e}")
                    self.tts_input_queue.put("I'm having a little trouble thinking right now.")
                finally:
                    # Signal that conversation processing is done - resume background extraction
                    if self.combined_memory:
                        self.combined_memory.on_conversation_end()
                    
                    # Always send EOS if we started processing, unless interrupted early
                    if self.processing_active_event.is_set():  # Only send EOS if not interrupted
                        logger.debug("LLM Processor: Sending EOS token to TTS queue.")
                        self.tts_input_queue.put("<EOS>")
                    else:
                        logger.info("LLM Processor: Interrupted, not sending EOS from LLM processing.")
                        # The AudioPlayer will handle clearing its state.
                        # If an EOS was already sent by TTS from a *previous* partial sentence,
                        # this could lead to an early clear of currently_speaking.
                        # The `processing_active_event` is key to synchronize.

            except queue.Empty:
                # Idle time - trigger background summarization if available
                if self.conversation_memory and hasattr(self.conversation_memory, 'trigger_summary_update'):
                    self.conversation_memory.trigger_summary_update()
            except Exception as e:
                logger.exception(f"LLM Processor: Unexpected error in main run loop: {e}")
                time.sleep(0.1)
        logger.info("LanguageModelProcessor thread finished.")
