"""
Minimal text-only Jarvis interface.

This file is intentionally simple: it only handles terminal input/output.

This can be used to test the OpenClaw integration without needing a microphone or speaker setup, 
and it also serves as a reference implementation for how to call OpenClaw from Python.

All OpenClaw-specific communication is delegated to openclaw_adapter.ask_openclaw().
That separation makes it easier to replace this terminal UI with voice or a GUI later.
"""

from openclaw_adapter import ask_openclaw
from config import bot_name


def main():
    """Run a basic terminal chat loop."""
    print(f"{bot_name} text mode initiated.\nType 'exit' to terminate.")

    while True:
        # Read one message from the user.
        # .strip() removes accidental leading/trailing whitespace.
        try:
            message = input("You: ").strip()
        except KeyboardInterrupt:
            # Lets Ctrl+C close the program cleanly instead of showing a traceback.
            print(f"\nExiting {bot_name}. Goodbye!")
            break

        # Ignore empty input rather than sending blank messages to OpenClaw.
        if not message:
            continue

        # Simple escape hatch for ending the loop.
        if message.lower() in ["exit", "quit"]:
            print(f"\nExiting {bot_name}. Goodbye!")
            break

        try:
            # Send the message to the OpenClaw adapter.
            # The adapter returns only the assistant's visible reply text.
            response = ask_openclaw(message)
        except Exception as e:
            # Keep the chat loop alive if OpenClaw fails, times out, or returns bad output.
            print(f"Error communicating with {bot_name}: {e}")
            continue

        print(f"{bot_name}: {response}\n")


if __name__ == "__main__":
    main()
