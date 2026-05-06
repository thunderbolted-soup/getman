import datetime
import uuid
import os
from typing import List, Dict, Any
from storage.store import load_json, save_json

HISTORY_FILE = "data/history.json"
MAX_HISTORY = 100

def get_history() -> List[Dict[str, Any]]:
    """Returns the list of request history entries."""
    return load_json(HISTORY_FILE, [])

def add_to_history(request_data: Dict[str, Any]):
    """Adds a new request to history, keeping only the last MAX_HISTORY entries."""
    from core.settings import get_settings
    settings = get_settings()
    max_size = settings.get("max_history_size", 100)
    
    history = get_history()
    
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.datetime.now().isoformat(),
        "method": request_data.get("method", "GET"),
        "url": request_data.get("url", ""),
        "headers": request_data.get("headers", {}),
        "body": request_data.get("body", ""),
        "auth_id": request_data.get("auth_id"),
        "response_status": request_data.get("response_status"),
        "response_time_ms": request_data.get("response_time_ms")
    }
    
    history.insert(0, entry)
    history = history[:max_size]
    
    save_json(HISTORY_FILE, history)

def clear_history():
    """Clears all history."""
    save_json(HISTORY_FILE, [])
