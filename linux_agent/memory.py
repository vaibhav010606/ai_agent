import json
import os
from datetime import datetime

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "chat_history.json")


class SimpleChatMemory:
    """
    Lightweight conversation memory — stores turns as Groq-compatible
    {"role": "user"/"assistant", "content": "..."} dicts.
    Persists history to disk (chat_history.json) across restarts.
    """

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self._history: list[dict] = []
        self._load()

    def _load(self):
        """Load history from disk if it exists."""
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f:
                    all_sessions = json.load(f)
                self._history = all_sessions.get(self.session_id, [])
            except (json.JSONDecodeError, IOError):
                self._history = []

    def _save(self):
        """Persist the current session history to disk."""
        all_sessions = {}
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f:
                    all_sessions = json.load(f)
            except (json.JSONDecodeError, IOError):
                all_sessions = {}

        all_sessions[self.session_id] = self._history
        with open(MEMORY_FILE, "w") as f:
            json.dump(all_sessions, f, indent=2)

    def save_context(self, human_input: str, ai_output: str):
        """Append one completed turn to history and persist."""
        self._history.append({
            "role": "user",
            "content": human_input,
            "timestamp": datetime.now().isoformat()
        })
        self._history.append({
            "role": "assistant",
            "content": ai_output,
            "timestamp": datetime.now().isoformat()
        })
        self._save()

    def to_groq_history(self) -> list[dict]:
        """Return history in the format Groq's API expects (no timestamps)."""
        return [{"role": m["role"], "content": m["content"]} for m in self._history]

    def to_export(self) -> list[dict]:
        """Return full history including timestamps (for export)."""
        return list(self._history)

    def format_history(self) -> str:
        """Plain-text representation (for debugging)."""
        lines = []
        for msg in self._history:
            prefix = "Human" if msg["role"] == "user" else "Assistant"
            lines.append(f"{prefix}: {msg['content']}")
        return "\n".join(lines)

    def clear(self):
        self._history.clear()
        self._save()
