# app/cli.py
import asyncio

class CLIHandler:
    def __init__(self, app):
        self.app = app

    async def show_menu(self):
        print("\n--- Main Menu ---")
        print(f"Your Caller ID: {self.app.caller_id}")
        print("1. Call (type 'call')")
        print("2. Hang up (type 'hangup')")
        print("3. Exit (type 'exit')")
        print("-----------------")

    async def loop(self):
        await self.show_menu()
        while True:
            try:
                command = await asyncio.to_thread(input, "> ")
                command = command.strip().lower()

                if command == 'call':
                    target_id = await asyncio.to_thread(input, "Enter Caller ID to call: ")
                    await self.app.start_call(target_id.strip())
                elif command == 'hangup':
                    await self.app.hang_up()
                elif command == 'exit':
                    await self.app.shutdown()
                    break
                else:
                    print("Unknown command.")
                    await self.show_menu()
            except (EOFError, KeyboardInterrupt):
                await self.app.shutdown()
                break