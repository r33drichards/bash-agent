import os
import json
from datetime import datetime
from flask import current_app

from .session_manager import sessions


def save_conversation_history(session_id):
    """Save conversation history to JSON file in metadata directory"""
    if not current_app.config.get("METADATA_DIR"):
        return

    if session_id not in sessions:
        return

    history = sessions[session_id]["conversation_history"]
    if not history:
        return

    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_{session_id[:8]}_{timestamp}.json"
    filepath = os.path.join(current_app.config["METADATA_DIR"], filename)

    # Save conversation data
    conversation_data = {
        "session_id": session_id,
        "started_at": sessions[session_id]["connected_at"].isoformat(),
        "ended_at": datetime.now().isoformat(),
        "history": history,
    }

    try:
        with open(filepath, "w") as f:
            json.dump(conversation_data, f, indent=2)
        print(f"Conversation history saved to: {filepath}")
    except Exception as e:
        print(f"Error saving conversation history: {e}")


def load_conversation_history():
    """Load all conversation history files from metadata directory"""
    if not current_app.config.get("METADATA_DIR"):
        return []

    if not os.path.exists(current_app.config["METADATA_DIR"]):
        return []

    conversations = []
    try:
        for filename in os.listdir(current_app.config["METADATA_DIR"]):
            if filename.startswith("conversation_") and filename.endswith(".json"):
                filepath = os.path.join(current_app.config["METADATA_DIR"], filename)
                with open(filepath, "r") as f:
                    conversation_data = json.load(f)
                    conversations.append(conversation_data)

        # Sort by started_at timestamp
        conversations.sort(key=lambda x: x["started_at"], reverse=True)

    except Exception as e:
        print(f"Error loading conversation history: {e}")

    return conversations