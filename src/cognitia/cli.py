import argparse
import asyncio
from hashlib import sha256
from pathlib import Path
import sys

import httpx
from rich import print as rprint
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn
import sounddevice as sd  # type: ignore

from .core.engine import Cognitia, CognitiaConfig
from .TTS import get_speech_synthesizer
from .utils import spoken_text_converter as stc
from .utils.resources import resource_path

# Type aliases for clarity
FileHash = str
FileURL = str
FileName = str

DEFAULT_CONFIG = resource_path("configs/cognitia_config.yaml")

# Details of all the models.  Each key is the file path where the model should be saved
MODEL_DETAILS: dict[FileName, dict[FileURL, FileHash]] = {
    "models/ASR/nemo-parakeet_tdt_ctc_110m.onnx": {
        "url": "https://github.com/dnhkng/GlaDOS/releases/download/0.1/nemo-parakeet_tdt_ctc_110m.onnx",
        "checksum": "313705ff6f897696ddbe0d92b5ffadad7429a47d2ddeef370e6f59248b1e8fb5",
    },
    "models/ASR/parakeet-tdt-0.6b-v2_encoder.onnx": {
        "url": "https://github.com/dnhkng/GlaDOS/releases/download/0.1/parakeet-tdt-0.6b-v2_encoder.onnx",
        "checksum": "f133a92186e63c7d4ab5b395a8e45d49f4a7a84a1d80b66f494e8205dfd57b63",
    },
    "models/ASR/parakeet-tdt-0.6b-v2_decoder.onnx": {
        "url": "https://github.com/dnhkng/GlaDOS/releases/download/0.1/parakeet-tdt-0.6b-v2_decoder.onnx",
        "checksum": "415b14f965b2eb9d4b0b8517f0a1bf44a014351dd43a09c3a04d26a41c877951",
    },
    "models/ASR/parakeet-tdt-0.6b-v2_joiner.onnx": {
        "url": "https://github.com/dnhkng/GlaDOS/releases/download/0.1/parakeet-tdt-0.6b-v2_joiner.onnx",
        "checksum": "846929b668a94462f21be25c7b5a2d83526e0b92a8306f21d8e336fc98177976",
    },
    "models/ASR/silero_vad_v5.onnx": {
        "url": "https://github.com/dnhkng/GlaDOS/releases/download/0.1/silero_vad_v5.onnx",
        "checksum": "6b99cbfd39246b6706f98ec13c7c50c6b299181f2474fa05cbc8046acc274396",
    },
    "models/TTS/glados.onnx": {
        "url": "https://github.com/dnhkng/GlaDOS/releases/download/0.1/glados.onnx",
        "checksum": "17ea16dd18e1bac343090b8589042b4052f1e5456d42cad8842a4f110de25095",
    },
    "models/TTS/kokoro-v1.0.fp16.onnx": {
        "url": "https://github.com/dnhkng/GLaDOS/releases/download/0.1/kokoro-v1.0.fp16.onnx",
        "checksum": "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204",
    },
    "models/TTS/kokoro-voices-v1.0.bin": {
        "url": "https://github.com/dnhkng/GLaDOS/releases/download/0.1/kokoro-voices-v1.0.bin",
        "checksum": "c5adf5cc911e03b76fa5025c1c225b141310d0c4a721d6ed6e96e73309d0fd88",
    },
    "models/TTS/phomenizer_en.onnx": {
        "url": "https://github.com/dnhkng/GlaDOS/releases/download/0.1/phomenizer_en.onnx",
        "checksum": "b64dbbeca8b350927a0b6ca5c4642e0230173034abd0b5bb72c07680d700c5a0",
    },
}


async def download_with_progress(
    client: httpx.AsyncClient,
    url: str,
    file_path: Path,
    expected_checksum: str,
    progress: Progress,
) -> bool:
    """
    Download a single file with progress tracking and SHA-256 checksum verification.

    Returns:
        bool: True if download and verification succeeded, False otherwise
    """
    task_id = progress.add_task(f"Downloading {file_path}", status="")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    hash_sha256 = sha256()

    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()

            # Set total size for progress bar
            total_size = int(response.headers.get("Content-Length", 0))
            if total_size:
                progress.update(task_id, total=total_size)

            with file_path.open(mode="wb") as f:
                async for chunk in response.aiter_bytes(32768):  # 32KB chunks
                    f.write(chunk)
                    # Update the hash as we go along, for speed
                    hash_sha256.update(chunk)
                    progress.advance(task_id, len(chunk))

        # Verify checksum, and delete failed files
        actual_checksum = hash_sha256.hexdigest()
        if actual_checksum != expected_checksum:
            progress.update(task_id, status="[bold red]Checksum failed")
            Path.unlink(file_path)
            return False
        else:
            progress.update(task_id, status="[bold green]OK")
            return True

    except Exception as e:
        progress.update(task_id, status=f"[bold red]Error: {str(e)}")
        return False


async def download_models() -> int:
    """
    Main async controller for downloading all the specified models.

    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    with Progress(
        TextColumn("[grey50][progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TextColumn("  {task.fields[status]}"),
    ) as progress:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Create a download task for each file
            tasks = [
                asyncio.create_task(
                    download_with_progress(client, model_info["url"], Path(path), model_info["checksum"], progress)
                )
                for path, model_info in MODEL_DETAILS.items()
            ]
            results: list[bool] = await asyncio.gather(*tasks)

    if not all(results):
        rprint("\n[bold red]Some files were not downloaded successfully")
        return 1
    rprint("\n[bold green]All files downloaded and verified successfully")
    return 0


def models_valid() -> bool:
    """
    Check the validity of all model files.

    Returns:
        bool: True if all model files are valid and present, False otherwise.
    """
    for path, model_info in MODEL_DETAILS.items():
        file_path = Path(path)
        if not (file_path.exists() and sha256(file_path.read_bytes()).hexdigest() == model_info["checksum"]):
            return False
    return True


def say(text: str, config_path: str | Path = "cognitia_config.yaml") -> None:
    """
    Converts text to speech using the Cognitia TTS system and plays the generated audio.
    """
    cognitia_tts = get_speech_synthesizer(voice="cognitia")
    converter = stc.SpokenTextConverter()
    converted_text = converter.text_to_spoken(text)
    # Generate the audio from the text
    audio = cognitia_tts.generate_speech_audio(converted_text)

    # Play the audio
    sd.play(audio, cognitia_tts.sample_rate)
    sd.wait()


def start(config_path: str | Path = "cognitia_config.yaml") -> None:
    """
    Start the Cognitia voice assistant and initialize its listening event loop.
    """
    cognitia_config = CognitiaConfig.from_yaml(str(config_path))
    cognitia = Cognitia.from_config(cognitia_config)
    if cognitia.announcement:
        cognitia.play_announcement()
    cognitia.run()


def main() -> int:
    """
    Command-line interface (CLI) entry point for the Cognitia voice assistant.
    """
    parser = argparse.ArgumentParser(description="Cognitia Voice Assistant")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Download command
    subparsers.add_parser("download", help="Download model files")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start Cognitia voice assistant")
    start_parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG,
        help=f"Path to configuration file (default: {DEFAULT_CONFIG})",
    )

    # Say command
    say_parser = subparsers.add_parser("say", help="Make Cognitia speak text")
    say_parser.add_argument("text", type=str, help="Text for Cognitia to speak")
    say_parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG,
        help=f"Path to configuration file (default: {DEFAULT_CONFIG})",
    )

    args = parser.parse_args()

    if args.command == "download":
        return asyncio.run(download_models())
    else:
        if not models_valid():
            print("Some model files are invalid or missing. Please run 'cognitia download'")
            return 1
        if args.command == "say":
            say(args.text, args.config)
        elif args.command == "start":
            start(args.config)
        else:
            # Default to start if no command specified
            start(DEFAULT_CONFIG)
        return 0


if __name__ == "__main__":
    sys.exit(main())
