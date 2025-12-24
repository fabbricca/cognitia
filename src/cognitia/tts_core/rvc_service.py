"""RVC Voice Conversion Service Client.

This module provides a client for the RVC Docker microservice,
allowing GLaDOS to use voice cloning with parallel processing.

Architecture:
    GLaDOS TTS → RVC API (Docker) → Converted Audio
    
The RVC service runs in a separate Docker container with GPU access,
providing voice conversion via HTTP API.
"""

import io
import base64
import time
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, Future
import threading

import numpy as np
from numpy.typing import NDArray
import requests
from loguru import logger

# Try to import soundfile, fallback to scipy
try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    sf = None  # type: ignore
    SOUNDFILE_AVAILABLE = False


class RVCServiceClient:
    """
    Client for the RVC Docker microservice.
    
    Communicates with the RVC API running in Docker to perform
    voice conversion. Supports async/parallel processing.
    """
    
    def __init__(
        self,
        service_url: str = "http://localhost:5050",
        model_name: Optional[str] = None,
        timeout: float = 30.0,
        max_workers: int = 2,  # Parallel RVC conversions
    ) -> None:
        """
        Initialize the RVC service client.
        
        Args:
            service_url: URL of the RVC API service
            model_name: Name of the RVC model to use (must be in rvc_models dir)
            timeout: Request timeout in seconds
            max_workers: Max parallel conversion requests
        """
        self.service_url = service_url.rstrip('/')
        self.model_name = model_name
        self.timeout = timeout
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._session = requests.Session()
        self._initialized = False
        self._lock = threading.Lock()
        
    def initialize(self) -> bool:
        """
        Initialize connection and load model.
        
        Returns:
            True if initialization successful
        """
        with self._lock:
            if self._initialized:
                return True
            
            try:
                # Check if service is available
                response = self._session.get(
                    f"{self.service_url}/models",
                    timeout=5.0
                )
                response.raise_for_status()
                response_data = response.json()
                # API returns {"models": [...]} or just [...]
                if isinstance(response_data, dict) and "models" in response_data:
                    available_models = response_data["models"]
                else:
                    available_models = response_data
                logger.info(f"RVC service available. Models: {available_models}")
                
                # Load model if specified
                if self.model_name:
                    if self.model_name not in available_models:
                        logger.error(f"Model '{self.model_name}' not found. Available: {available_models}")
                        return False
                    
                    response = self._session.post(
                        f"{self.service_url}/models/{self.model_name}",
                        timeout=self.timeout
                    )
                    response.raise_for_status()
                    logger.success(f"RVC model '{self.model_name}' loaded")
                
                self._initialized = True
                return True
                
            except requests.RequestException as e:
                logger.error(f"Failed to connect to RVC service: {e}")
                return False
    
    def set_params(
        self,
        f0_method: str = "rmvpe",
        f0_up_key: int = 0,
        index_rate: float = 0.5,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
    ) -> bool:
        """
        Set RVC conversion parameters.
        
        Args:
            f0_method: Pitch extraction method (rmvpe, harvest, crepe, pm)
            f0_up_key: Pitch shift in semitones
            index_rate: Index file influence (0.0-1.0)
            filter_radius: Median filter radius for pitch
            rms_mix_rate: Volume envelope mix rate
            protect: Protection for voiceless consonants
            
        Returns:
            True if parameters set successfully
        """
        params = {
            "f0method": f0_method,
            "f0up_key": f0_up_key,
            "index_rate": index_rate,
            "filter_radius": filter_radius,
            "rms_mix_rate": rms_mix_rate,
            "protect": protect,
        }
        
        try:
            response = self._session.post(
                f"{self.service_url}/params",
                json={"params": params},
                timeout=5.0
            )
            response.raise_for_status()
            logger.debug(f"RVC params set: {params}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to set RVC params: {e}")
            return False
    
    def convert(
        self,
        audio: NDArray[np.float32],
        sample_rate: int,
    ) -> NDArray[np.float32]:
        """
        Convert audio using the RVC service (blocking).
        
        Args:
            audio: Input audio as float32 numpy array
            sample_rate: Sample rate of input audio
            
        Returns:
            Converted audio as float32 numpy array
        """
        if not self._initialized:
            if not self.initialize():
                logger.warning("RVC not initialized, returning original audio")
                return audio
        
        start = time.time()
        
        # Encode audio to base64 WAV
        audio_bytes = self._audio_to_bytes(audio, sample_rate)
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        try:
            response = self._session.post(
                f"{self.service_url}/convert",
                json={"audio_data": audio_b64},
                timeout=self.timeout
            )
            response.raise_for_status()
            
            # Decode response audio
            converted_audio = self._bytes_to_audio(response.content, sample_rate)
            
            elapsed = time.time() - start
            logger.debug(f"RVC conversion: {elapsed*1000:.1f}ms")
            
            return converted_audio
            
        except requests.RequestException as e:
            logger.error(f"RVC conversion failed: {e}")
            return audio  # Return original on failure
    
    def convert_async(
        self,
        audio: NDArray[np.float32],
        sample_rate: int,
    ) -> Future:
        """
        Convert audio asynchronously.
        
        Args:
            audio: Input audio as float32 numpy array
            sample_rate: Sample rate of input audio
            
        Returns:
            Future that will contain the converted audio
        """
        return self._executor.submit(self.convert, audio, sample_rate)
    
    def _audio_to_bytes(self, audio: NDArray[np.float32], sample_rate: int) -> bytes:
        """Convert numpy audio to WAV bytes."""
        buffer = io.BytesIO()
        
        if SOUNDFILE_AVAILABLE and sf is not None:
            sf.write(buffer, audio, sample_rate, format='WAV')
        else:
            # Fallback using scipy
            from scipy.io import wavfile  # type: ignore
            # Convert to int16 for scipy
            audio_int16 = (audio * 32767).astype(np.int16)
            wavfile.write(buffer, sample_rate, audio_int16)
        
        buffer.seek(0)
        return buffer.read()
    
    def _bytes_to_audio(self, data: bytes, target_sr: int) -> NDArray[np.float32]:
        """Convert WAV bytes to numpy audio."""
        buffer = io.BytesIO(data)
        
        if SOUNDFILE_AVAILABLE and sf is not None:
            audio, sr = sf.read(buffer, dtype='float32')
        else:
            from scipy.io import wavfile  # type: ignore
            sr, audio = wavfile.read(buffer)
            audio = audio.astype(np.float32) / 32767.0
        
        # Resample if needed
        if sr != target_sr:
            try:
                import soxr  # type: ignore
                audio = soxr.resample(audio, sr, target_sr)
            except ImportError:
                from scipy import signal  # type: ignore
                num_samples = int(len(audio) * target_sr / sr)
                audio = signal.resample(audio, num_samples)
        
        return audio.astype(np.float32)
    
    def shutdown(self):
        """Shutdown the executor."""
        self._executor.shutdown(wait=False)


class RVCServiceSynthesizer:
    """
    TTS synthesizer wrapper that uses RVC service for voice conversion.
    
    This wraps any TTS model and sends the output through the RVC
    Docker service for voice conversion.
    """
    
    def __init__(
        self,
        base_tts,  # SpeechSynthesizerProtocol
        rvc_client: RVCServiceClient,
    ) -> None:
        """
        Initialize the RVC service synthesizer.
        
        Args:
            base_tts: Base TTS model
            rvc_client: RVC service client instance
        """
        self.base_tts = base_tts
        self.sample_rate = base_tts.sample_rate
        self.rvc_client = rvc_client
        
        # Initialize RVC client
        if not self.rvc_client.initialize():
            logger.warning("RVC service not available, will use base TTS only")
    
    def generate_speech_audio(self, text: str) -> NDArray[np.float32]:
        """
        Generate speech with voice conversion.
        
        Args:
            text: Text to synthesize
            
        Returns:
            Converted audio as float32 numpy array
        """
        start = time.time()
        
        # Generate base TTS
        base_audio = self.base_tts.generate_speech_audio(text)
        tts_time = time.time() - start
        
        if len(base_audio) == 0:
            return base_audio
        
        # Convert through RVC service
        rvc_start = time.time()
        converted_audio = self.rvc_client.convert(base_audio, self.sample_rate)
        rvc_time = time.time() - rvc_start
        
        total = time.time() - start
        logger.info(f"TTS+RVC: TTS={tts_time*1000:.0f}ms, RVC={rvc_time*1000:.0f}ms, Total={total*1000:.0f}ms")
        
        return converted_audio
