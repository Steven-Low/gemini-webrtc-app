# main.py
import asyncio
from dotenv import load_dotenv
from app.application import Application

async def main():
    load_dotenv()
    app = Application()
    await app.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication terminated by user.")