"""Open tabs and window layout, restored on the next start (unsaved edits
survive a restart, so closing the app never asks questions)."""
from core.paths import data_path
from core.storage import load_json, save_json


def load_session() -> dict:
    data = load_json(data_path("session.json"), {})
    return data if isinstance(data, dict) else {}


def save_session(data: dict):
    save_json(data_path("session.json"), data, compact=True)
