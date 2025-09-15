# main.py
import asyncio
import logging
import argparse
import sys
from dotenv import load_dotenv
from pathlib import Path
from app.app import GeminiApp

sys.path.append(str(Path(__file__).resolve().parent))

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
    args = parser.parse_args()

    LOGGER = setup_logger(args.debug)

    load_dotenv()
    app = GeminiApp()

    LOGGER.info("Starting Application...")
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication terminated by user.")
