# app/cli.py
import asyncio
from app.config.constants import MAX_SESSIONS 

class CLIHandler:
    def __init__(self, app):
        """
        Initializes the CLI Handler.

        Args:
            app: The main Application instance, which manages active sessions.
        """
        self.app = app

    def show_menu(self):
        """Prints the command menu to the console."""
        print("\n--- Multi-Session Call Manager ---")
        print(f"Listening for calls at Main ID: {self.app.main_caller_id}")
        print("------------------------------------")
        print("Available Commands:")
        print("  status    - List all active call sessions.")
        print("  call      - Start a new call to a remote user.") 
        print("  hangup    - Hang up a specific call session.")
        print("  menu      - Show this menu again.")
        print("  exit      - Shut down all sessions and exit.")
        print("------------------------------------")

    async def loop(self):
        """The main input loop for handling user commands."""
        self.show_menu()
        while True:
            try:
                command = await asyncio.to_thread(input, "> ")
                command = command.strip().lower()

                if command == 'status':
                    self.show_status()
                
                elif command == 'call':
                    await self.handle_start_call()

                elif command == 'hangup':
                    await self.handle_hangup()

                elif command == 'menu':
                    self.show_menu()

                elif command == 'exit':
                    print("Initiating shutdown...")
                    await self.app.shutdown()
                    print("Shutdown complete. Exiting CLI.")
                    break
                
                # The 'call' command is removed as the server is now inbound-only.
                elif command == 'call':
                    print("This server is designed to receive calls, not initiate them.")
                    print("Please have a client call the main ID:", self.app.main_caller_id)

                elif not command: # Handle empty input
                    continue

                else:
                    print(f"Unknown command: '{command}'. Type 'menu' for options.")

            except (EOFError, KeyboardInterrupt):
                print("\nShutdown signal received.")
                await self.app.shutdown()
                print("Shutdown complete. Exiting CLI.")
                break
            except Exception as e:
                print(f"An error occurred in the CLI loop: {e}")
                # Decide if you want to break the loop on other exceptions
                break
    
    def show_status(self):
        """Displays the current status of active call sessions."""
        print("\n--- Active Call Status ---")
        active_sessions = self.app.active_sessions
        
        if not active_sessions:
            print("No active calls.")
        else:
            print(f"Total active calls: {len(active_sessions)} / {MAX_SESSIONS}")
            for i, session_id in enumerate(active_sessions.keys()):
                print(f"  {i+1}. Session with Remote User: {session_id}")
        
        print("--------------------------")

    async def handle_start_call(self):
        """Handles the logic for initiating an outbound call."""
        try:
            target_id = await asyncio.to_thread(input, "Enter the Remote User ID to call: ")
            target_id = target_id.strip()
            if target_id:
                # Delegate the call initiation to the main application
                await self.app.start_call(target_id)
            else:
                print("Call cancelled. No ID entered.")
        except (EOFError, KeyboardInterrupt):
            print("\nCall cancelled.")
            return


    async def handle_hangup(self):
        """Handles the logic for hanging up a specific session."""
        self.show_status()
        active_sessions = self.app.active_sessions

        if not active_sessions:
            print("There are no active calls to hang up.")
            return

        try:
            target_id = await asyncio.to_thread(input, "Enter the full Remote User ID to hang up (or press Enter to cancel): ")
            target_id = target_id.strip()

            if not target_id:
                print("Hangup cancelled.")
                return

            await self.app.hang_up(target_id)

        except (EOFError, KeyboardInterrupt):
            print("\nHangup cancelled.")
            return