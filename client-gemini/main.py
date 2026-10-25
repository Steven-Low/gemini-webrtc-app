# main.py
import asyncio
import logging
import argparse
import os
import sys
from dotenv import load_dotenv
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
load_dotenv(Path(__file__).resolve().with_name(".env"))

from app.app import GeminiApp

def setup_logger(debug: bool):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    return app_logger


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Enable debug logging for app only")
    parser.add_argument(
        "--debug-audio",
        action="store_true",
        help="Save each captured user utterance as a WAV in client-gemini/debug_audio",
    )
    args = parser.parse_args()

    if args.debug_audio:
        os.environ["GEMINI_DEBUG_AUDIO_DIR"] = str(Path(__file__).resolve().parent / "debug_audio")

    LOGGER = setup_logger(args.debug)

    app = GeminiApp()

    LOGGER.info("Starting Application...")
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication terminated by user.")
