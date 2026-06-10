import os
import sys
import re
import itertools
from dotenv import load_dotenv

# Load .env file
load_dotenv()

from groq import Groq
from tools import execute_linux_command_direct
from memory import SimpleChatMemory
from config import SYSTEM_PROMPT

REACT_INSTRUCTIONS = """
You have access to ONE tool to interact with the Linux system:

  Tool Name: execute_linux_command
  How to call it: Output a line in EXACTLY this format (plain text, no markdown):
    ACTION: <the shell command to run>

After you see the Observation (command output), keep reasoning. When done, write:
    FINAL ANSWER: <plain English summary of what happened>

RULES:
- Only one ACTION per message.
- Never fabricate command output — always wait for the real Observation.
- If a command fails, diagnose the error and try another approach.
- Always end with FINAL ANSWER when the task is complete.
"""


def run_agent_turn(client_iterator, user_input: str, history: list) -> str:
    """
    Full ReAct loop for one user turn.
    history is a list of {"role": ..., "content": ...} dicts (Groq format).
    Returns the final answer string.
    """
    # Build the message list for this turn
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + REACT_INSTRUCTIONS},
        *history,
        {"role": "user", "content": user_input}
    ]

    max_steps = 8
    for step in range(max_steps):
        client = next(client_iterator)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0,
            max_tokens=1024
        )
        reply = response.choices[0].message.content.strip()
        # print(f"\n[Agent Reasoning]\n{reply}")  # Uncomment to debug reasoning

        # Check for an ACTION to execute
        action_match = re.search(r"^ACTION:\s*(.+)$", reply, re.MULTILINE | re.IGNORECASE)
        if action_match:
            command = action_match.group(1).strip()
            # print(f"\n[Executing] {command}")  # Uncomment to debug execution
            observation = execute_linux_command_direct(command)
            # print(f"[Observation]\n{observation}")  # Uncomment to debug observation

            # Append assistant reply + observation back into the conversation
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": f"Observation from `{command}`:\n{observation}\n\nContinue."
            })
            continue

        # Check for a FINAL ANSWER
        final_match = re.search(r"FINAL ANSWER:\s*(.+)", reply, re.DOTALL | re.IGNORECASE)
        if final_match:
            return final_match.group(1).strip()

        # Treat the whole reply as the final answer if no pattern matched
        return reply

    return "I reached the maximum reasoning steps. Please try rephrasing your request."


def run_cli():
    print("=" * 50)
    print("  Linux Automation Agent  |  Groq + LLaMA3-70B")
    print("  Type 'exit' or 'quit' to stop.")
    print("=" * 50)

    api_keys_str = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY")
    if not api_keys_str:
        print("ERROR: GROQ_API_KEYS not found. Check your .env file.")
        sys.exit(1)

    # Split the keys, clean whitespace, and create a round-robin pool of Groq clients
    keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
    clients = [Groq(api_key=k) for k in keys]
    client_iterator = itertools.cycle(clients)
    print(f"[Info] Loaded {len(clients)} API key(s) for round-robin rotation.")

    memory = SimpleChatMemory()

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break

            final_answer = run_agent_turn(client_iterator, user_input, memory.to_groq_history())
            print(f"\nAgent: {final_answer}")
            memory.save_context(user_input, final_answer)

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n[Error] {type(e).__name__}: {e}")


if __name__ == "__main__":
    run_cli()
