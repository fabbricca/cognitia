"""Text-to-Speech (TTS) synthesis components.

This module provides a protocol-based interface for text-to-speech synthesis
and a factory function to create synthesizer instances for different voices.

Classes:
    SpeechSynthesizerProtocol: Protocol defining the TTS interface

Functions:
    get_speech_synthesizer: Factory function to create TTS instances
"""

from pathlib import Path
from typing import Optional, Protocol

import numpy as np
from numpy.typing import NDArray


class SpeechSynthesizerProtocol(Protocol):
    sample_rate: int

    def generate_speech_audio(self, text: str) -> NDArray[np.float32]: ...


# Factory function
def get_speech_synthesizer(
    voice: str = "cognitia",
    rvc_model_path: Optional[str | Path] = None,
    rvc_index_path: Optional[str | Path] = None,
    rvc_device: str = "cuda:0",
    rvc_f0_method: str = "rmvpe",
    rvc_f0_up_key: int = 0,
    **rvc_kwargs,
) -> SpeechSynthesizerProtocol:
    """
    Factory function to get an instance of an audio synthesizer based on the specified voice type.
    
    Parameters:
        voice (str): The type of TTS engine to use:
            - "cognitia": Cognitia voice synthesizer
            - <str>: Kokoro voice synthesizer using the specified voice
        rvc_model_path: Optional path to RVC model (.pth) for voice cloning
        rvc_index_path: Optional path to RVC index file (.index)
        rvc_device: Device for RVC inference ("cuda:0", "cpu")
        rvc_f0_method: Pitch extraction method ("rmvpe" is fastest, "harvest" is higher quality)
        rvc_f0_up_key: Pitch shift in semitones
        **rvc_kwargs: Additional RVC parameters (index_rate, protect, etc.)
        
    Returns:
        SpeechSynthesizerProtocol: An instance of the requested speech synthesizer,
            optionally wrapped with RVC voice conversion
            
    Raises:
        ValueError: If the specified TTS engine type is not supported
        
    Example with RVC voice cloning:
        tts = get_speech_synthesizer(
            voice="cognitia",
            rvc_model_path="/path/to/your/model.pth",
            rvc_index_path="/path/to/your/model.index",  # optional
        )
    """
    # Create base TTS
    if voice.lower() == "cognitia":
        from ..TTS import tts_cognitia
        base_tts = tts_cognitia.SpeechSynthesizer()
    else:
        from ..TTS import tts_kokoro
        available_voices = tts_kokoro.get_voices()
        if voice not in available_voices:
            raise ValueError(f"Voice '{voice}' not available. Available voices: {available_voices}")
        base_tts = tts_kokoro.SpeechSynthesizer(voice=voice)
    
    # Optionally wrap with RVC
    if rvc_model_path:
        from .rvc_wrapper import RVCWrappedSynthesizer
        return RVCWrappedSynthesizer(
            base_tts=base_tts,
            rvc_model_path=rvc_model_path,
            rvc_index_path=rvc_index_path,
            device=rvc_device,
            f0_method=rvc_f0_method,
            f0_up_key=rvc_f0_up_key,
            **rvc_kwargs,
        )
    
    return base_tts


__all__ = ["SpeechSynthesizerProtocol", "get_speech_synthesizer"]
