import json
import os
from typing import Any

def ensure_dir(file_path: str):
    """Ensures the directory for the given file path exists."""
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

def save_json(file_path: str, data: Any):
    """Saves data to a JSON file with pretty printing."""
    ensure_dir(file_path)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_json(file_path: str, default: Any = None) -> Any:
    """Loads data from a JSON file. Returns default if file doesn't exist or is invalid."""
    if not os.path.exists(file_path):
        return default
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default
