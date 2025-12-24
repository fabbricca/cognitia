"""RVC (Retrieval-based Voice Conversion) wrapper for TTS models.

This module provides a wrapper that applies RVC voice conversion to any TTS output,
allowing you to use your own cloned voice with any underlying TTS engine.

Typical latency: 100-300ms depending on GPU and audio length.
"""

import time
from pathlib import Path
from typing import Optional

import numpy as np
from numpy.typing import NDArray
from loguru import logger

try:
    from rvc_python.infer import RVCInference
    RVC_AVAILABLE = True
except ImportError:
    RVC_AVAILABLE = False
    RVCInference = None  # type: ignore

from . import SpeechSynthesizerProtocol


class RVCVoiceConverter:
    """
    RVC voice converter that applies voice cloning to audio.
    
    This is a standalone converter that can be used to process any audio.
    For latency optimization, the model is loaded once and reused.
    """
    
    def __init__(
        self,
        model_path: str | Path,
        index_path: Optional[str | Path] = None,
        device: str = "cuda:0",
        f0_method: str = "rmvpe",  # rmvpe is fastest with good quality
        f0_up_key: int = 0,  # Pitch shift in semitones
        index_rate: float = 0.5,  # How much to use the index file
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,  # Protect voiceless consonants
    ) -> None:
        """
        Initialize the RVC voice converter.
        
        Args:
            model_path: Path to the .pth RVC model file
            index_path: Optional path to the .index file for better quality
            device: Computation device ("cuda:0", "cuda:1", "cpu")
            f0_method: Pitch extraction method. Options:
                - "rmvpe": Recommended, good quality and speed
                - "harvest": Higher quality but slower
                - "crepe": Very high quality but slowest
                - "pm": Fastest but lower quality
            f0_up_key: Pitch shift in semitones (positive = higher, negative = lower)
            index_rate: How much to use the index file (0.0-1.0)
            filter_radius: Median filtering radius for pitch
            rms_mix_rate: Volume envelope mix rate
            protect: Protection for voiceless consonants (0.0-0.5)
        """
        if not RVC_AVAILABLE:
            raise ImportError(
                "rvc-python is not installed. Install with:\n"
                "pip install rvc-python\n"
                "pip install torch==2.1.1+cu118 torchaudio==2.1.1+cu118 "
                "--index-url https://download.pytorch.org/whl/cu118"
            )
        
        self.model_path = Path(model_path)
        self.index_path = Path(index_path) if index_path else None
        self.device = device
        self.f0_method = f0_method
        self.f0_up_key = f0_up_key
        self.index_rate = index_rate
        self.filter_radius = filter_radius
        self.rms_mix_rate = rms_mix_rate
        self.protect = protect
        
        # Initialize RVC
        logger.info(f"Loading RVC model from {self.model_path}")
        start = time.time()
        
        if RVCInference is None:
            raise ImportError("RVC not available")
        
        self.rvc = RVCInference(device=device)
        self.rvc.load_model(str(self.model_path), index_path=str(self.index_path) if self.index_path else None)
        
        # Set parameters
        self.rvc.set_params(
            f0method=f0_method,
            f0up_key=f0_up_key,
            index_rate=index_rate,
            filter_radius=filter_radius,
            rms_mix_rate=rms_mix_rate,
            protect=protect,
        )
        
        logger.success(f"RVC model loaded in {time.time() - start:.2f}s")
    
    def convert(
        self,
        audio: NDArray[np.float32],
        sample_rate: int,
    ) -> NDArray[np.float32]:
        """
        Convert audio using the loaded RVC model.
        
        Args:
            audio: Input audio as float32 numpy array (normalized -1 to 1)
            sample_rate: Sample rate of the input audio
            
        Returns:
            Converted audio as float32 numpy array at the same sample rate
        """
        import tempfile
        import soundfile as sf
        
        start = time.time()
        
        # RVC works with files, so we need to use temp files
        # This adds ~10-20ms overhead but is necessary for the library
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as in_file:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_file:
                in_path = in_file.name
                out_path = out_file.name
        
        try:
            # Write input audio to temp file
            sf.write(in_path, audio, sample_rate)
            
            # Run RVC inference
            self.rvc.infer_file(in_path, out_path)
            
            # Read output audio
            converted_audio, out_sr = sf.read(out_path, dtype='float32')
            
            # Resample if needed (RVC might change sample rate)
            if out_sr != sample_rate:
                try:
                    import soxr
                    converted_audio = soxr.resample(converted_audio, out_sr, sample_rate)
                except ImportError:
                    # Fallback to scipy
                    from scipy import signal
                    num_samples = int(len(converted_audio) * sample_rate / out_sr)
                    converted_audio = signal.resample(converted_audio, num_samples)
            
            elapsed = time.time() - start
            logger.debug(f"RVC conversion took {elapsed*1000:.1f}ms")
            
            return converted_audio.astype(np.float32)
            
        finally:
            # Clean up temp files
            import os
            try:
                os.unlink(in_path)
                os.unlink(out_path)
            except OSError:
                pass


class RVCWrappedSynthesizer:
    """
    A TTS synthesizer wrapper that applies RVC voice conversion.
    
    This wraps any SpeechSynthesizerProtocol-compatible TTS and applies
    RVC voice conversion to the output. The result sounds like your
    cloned voice speaking the synthesized text.
    
    Example:
        from cognitia.TTS import get_speech_synthesizer
        from cognitia.TTS.rvc_wrapper import RVCWrappedSynthesizer
        
        # Create base TTS
        base_tts = get_speech_synthesizer("cognitia")  # or kokoro voice
        
        # Wrap with RVC
        tts = RVCWrappedSynthesizer(
            base_tts=base_tts,
            rvc_model_path="/path/to/your/model.pth",
            rvc_index_path="/path/to/your/model.index",  # optional
        )
        
        # Use as normal
        audio = tts.generate_speech_audio("Hello, world!")
    """
    
    def __init__(
        self,
        base_tts: SpeechSynthesizerProtocol,
        rvc_model_path: str | Path,
        rvc_index_path: Optional[str | Path] = None,
        device: str = "cuda:0",
        f0_method: str = "rmvpe",
        f0_up_key: int = 0,
        index_rate: float = 0.5,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
    ) -> None:
        """
        Initialize the RVC-wrapped synthesizer.
        
        Args:
            base_tts: The underlying TTS model to wrap
            rvc_model_path: Path to the RVC .pth model file
            rvc_index_path: Optional path to the .index file
            device: Computation device
            f0_method: Pitch extraction method (rmvpe recommended)
            f0_up_key: Pitch shift in semitones
            index_rate: Index file influence (0.0-1.0)
            filter_radius: Median filter radius for pitch
            rms_mix_rate: Volume envelope mix rate
            protect: Voiceless consonant protection
        """
        self.base_tts = base_tts
        self.sample_rate = base_tts.sample_rate
        
        self.rvc_converter = RVCVoiceConverter(
            model_path=rvc_model_path,
            index_path=rvc_index_path,
            device=device,
            f0_method=f0_method,
            f0_up_key=f0_up_key,
            index_rate=index_rate,
            filter_radius=filter_radius,
            rms_mix_rate=rms_mix_rate,
            protect=protect,
        )
    
    def generate_speech_audio(self, text: str) -> NDArray[np.float32]:
        """
        Generate speech audio with RVC voice conversion.
        
        Args:
            text: Text to synthesize
            
        Returns:
            Audio as float32 numpy array with the cloned voice
        """
        start = time.time()
        
        # Generate base TTS audio
        base_audio = self.base_tts.generate_speech_audio(text)
        tts_time = time.time() - start
        
        if len(base_audio) == 0:
            return base_audio
        
        # Apply RVC voice conversion
        rvc_start = time.time()
        converted_audio = self.rvc_converter.convert(base_audio, self.sample_rate)
        rvc_time = time.time() - rvc_start
        
        total_time = time.time() - start
        logger.info(f"TTS+RVC: TTS={tts_time*1000:.0f}ms, RVC={rvc_time*1000:.0f}ms, Total={total_time*1000:.0f}ms")
        
        return converted_audio


def get_rvc_synthesizer(
    base_voice: str = "cognitia",
    rvc_model_path: str | Path = "",
    rvc_index_path: Optional[str | Path] = None,
    device: str = "cuda:0",
    f0_method: str = "rmvpe",
    f0_up_key: int = 0,
    **rvc_kwargs,
) -> RVCWrappedSynthesizer:
    """
    Factory function to create an RVC-wrapped TTS synthesizer.
    
    Args:
        base_voice: Base TTS voice ("cognitia" or a Kokoro voice name)
        rvc_model_path: Path to your RVC .pth model file
        rvc_index_path: Optional path to the .index file
        device: GPU device ("cuda:0") or "cpu"
        f0_method: Pitch extraction method (rmvpe is fastest with good quality)
        f0_up_key: Pitch shift in semitones
        **rvc_kwargs: Additional RVC parameters
        
    Returns:
        RVCWrappedSynthesizer instance
    """
    from . import get_speech_synthesizer
    
    if not rvc_model_path:
        raise ValueError("rvc_model_path is required")
    
    base_tts = get_speech_synthesizer(base_voice)
    
    return RVCWrappedSynthesizer(
        base_tts=base_tts,
        rvc_model_path=rvc_model_path,
        rvc_index_path=rvc_index_path,
        device=device,
        f0_method=f0_method,
        f0_up_key=f0_up_key,
        **rvc_kwargs,
    )
