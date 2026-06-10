import os
import sys
import re
import itertools
import subprocess
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

from groq import Groq
from tools import execute_linux_command_direct
from memory import SimpleChatMemory
from config import SYSTEM_PROMPT

app = Flask(__name__, static_folder="ui")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

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

# --- Round-robin Groq client pool ---
api_keys_str = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY")
if not api_keys_str:
    print("ERROR: GROQ_API_KEYS not found in .env")
    sys.exit(1)

keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
clients = [Groq(api_key=k) for k in keys]
client_iterator = itertools.cycle(clients)
print(f"[Info] Loaded {len(clients)} API key(s) for round-robin rotation.")

# In-memory session storage (keyed by session_id)
sessions = {}


def get_memory(session_id: str) -> SimpleChatMemory:
    if session_id not in sessions:
        sessions[session_id] = SimpleChatMemory(session_id=session_id)
    return sessions[session_id]


def run_agent_turn(user_input: str, history: list) -> str:
    # Truncate conversation history to the last 8 messages (4 turns) to avoid Groq TPM limits
    max_history_messages = 8
    truncated_history = history[-max_history_messages:] if len(history) > max_history_messages else history

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + REACT_INSTRUCTIONS},
        *truncated_history,
        {"role": "user", "content": user_input}
    ]

    max_steps = 8
    for step in range(max_steps):
        client = next(client_iterator)
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0,
                max_tokens=1024
            )
        except Exception as e:
            # If rate limited, try to print the error or handle it
            if "rate_limit" in str(e).lower() or "413" in str(e):
                return f"API Limit Warning: The conversation context is too large or API limits were hit. Please use 'Clear Chat' to reset the history. Full Error: {e}"
            raise e

        reply = response.choices[0].message.content.strip()

        action_match = re.search(r"^ACTION:\s*(.+)$", reply, re.MULTILINE | re.IGNORECASE)
        if action_match:
            command = action_match.group(1).strip()
            # Stream the thought back to the UI!
            socketio.emit("agent_thought", {"thought": reply, "command": command})
            
            observation = execute_linux_command_direct(command)
            
            socketio.emit("agent_observation", {"observation": observation})
            
            # Truncate command output to avoid bloating context size / TPM limits
            if len(observation) > 2000:
                observation = observation[:2000] + "\n\n[WARNING: Command output was truncated to 2000 characters to prevent API rate limits.]"
                
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": f"Observation from `{command}`:\n{observation}\n\nContinue."
            })
            continue

        final_match = re.search(r"FINAL ANSWER:\s*(.+)", reply, re.DOTALL | re.IGNORECASE)
        if final_match:
            return final_match.group(1).strip()

        return reply

    return "I reached the maximum reasoning steps. Please try rephrasing your request."


@app.route("/")
def index():
    return send_from_directory("ui", "index.html")


@socketio.on("chat_message")
def handle_chat_message(data):
    user_input = data.get("message", "").strip()
    session_id = data.get("session_id", "default")

    if not user_input:
        emit("agent_reply", {"reply": "Error: Empty message"})
        return

    memory = get_memory(session_id)
    try:
        answer = run_agent_turn(user_input, memory.to_groq_history())
        memory.save_context(user_input, answer)
        emit("agent_reply", {"reply": answer})
    except Exception as e:
        emit("agent_reply", {"reply": f"Error: {type(e).__name__}: {e}"})

@app.route("/stats")
def stats():
    """Return live CPU, RAM, and Disk stats."""
    def run(cmd):
        try:
            return subprocess.check_output(cmd, shell=True, text=True, timeout=3).strip()
        except Exception:
            return "N/A"

    cpu = run("top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | tr -d '%us,'")
    ram_info = run("free -m | awk '/^Mem:/{print $2, $3}'")
    disk_info = run("df -h / | awk 'NR==2{print $2, $3, $5}'")
    uptime = run("uptime -p")

    ram_parts = ram_info.split() if ram_info != "N/A" else ["?", "?"]
    disk_parts = disk_info.split() if disk_info != "N/A" else ["?", "?", "?"]

    try:
        ram_pct = round(int(ram_parts[1]) / int(ram_parts[0]) * 100)
    except Exception:
        ram_pct = 0

    return jsonify({
        "cpu": f"{cpu}%" if cpu != "N/A" else "N/A",
        "ram_total": ram_parts[0] if len(ram_parts) > 0 else "?",
        "ram_used": ram_parts[1] if len(ram_parts) > 1 else "?",
        "ram_pct": ram_pct,
        "disk_total": disk_parts[0] if len(disk_parts) > 0 else "?",
        "disk_used": disk_parts[1] if len(disk_parts) > 1 else "?",
        "disk_pct": disk_parts[2].replace("%","") if len(disk_parts) > 2 else "0",
        "uptime": uptime
    })


@app.route("/history", methods=["GET"])
def export_history():
    """Export chat history as JSON for a session."""
    session_id = request.args.get("session_id", "default")
    memory = get_memory(session_id)
    return jsonify({"session_id": session_id, "history": memory.to_export()})


@app.route("/clear", methods=["POST"])
def clear_history():
    """Clear the chat history for a session."""
    data = request.get_json()
    session_id = data.get("session_id", "default")
    memory = get_memory(session_id)
    memory.clear()
    return jsonify({"status": "cleared"})


import threading
import time

def background_monitor():
    """Proactive background monitor running in a separate thread."""
    while True:
        try:
            # Quick check of ram and cpu
            cpu_cmd = "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | tr -d '%us,'"
            cpu_str = subprocess.check_output(cpu_cmd, shell=True, text=True).strip()
            ram_cmd = "free -m | awk '/^Mem:/{print int($3/$2 * 100)}'"
            ram_str = subprocess.check_output(ram_cmd, shell=True, text=True).strip()
            
            try:
                cpu_val = float(cpu_str)
                if cpu_val > 90.0:
                    socketio.emit("system_alert", {"msg": f"⚠️ ALERT: CPU usage is at {cpu_val}%!"})
            except: pass
            
            try:
                ram_val = float(ram_str)
                if ram_val > 90.0:
                    socketio.emit("system_alert", {"msg": f"⚠️ ALERT: RAM usage is at {ram_val}%!"})
            except: pass
            
        except Exception:
            pass
        time.sleep(15)

threading.Thread(target=background_monitor, daemon=True).start()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
