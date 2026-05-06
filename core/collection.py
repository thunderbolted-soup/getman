import os
import json
from typing import List, Dict, Any, Optional
from storage.store import load_json, save_json

COLLECTIONS_DIR = "data/collections"

def ensure_collections_dir():
    """Ensures the collections directory exists."""
    if not os.path.exists(COLLECTIONS_DIR):
        os.makedirs(COLLECTIONS_DIR)

def get_collections_list() -> List[str]:
    """Returns a list of collection filenames."""
    ensure_collections_dir()
    return [f for f in os.listdir(COLLECTIONS_DIR) if f.endswith('.json')]

def load_collection(filename: str) -> Optional[Dict[str, Any]]:
    """Loads a collection from the collections directory."""
    path = os.path.join(COLLECTIONS_DIR, filename)
    return load_json(path)

def save_collection(filename: str, data: Dict[str, Any]):
    """Saves a collection to the collections directory."""
    ensure_collections_dir()
    path = os.path.join(COLLECTIONS_DIR, filename)
    save_json(path, data)

def import_postman_collection(source_path: str) -> Optional[str]:
    """Imports a Postman v2.1 collection and saves it locally."""
    data = load_json(source_path)
    if not data or "info" not in data or "item" not in data:
        return None
    
    name = data["info"].get("name", "Imported Collection")
    # Basic filename sanitization
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
    filename = f"{safe_name}.json"
    
    # Avoid simple collisions
    base_filename = filename
    counter = 1
    while os.path.exists(os.path.join(COLLECTIONS_DIR, filename)):
        filename = f"{safe_name}_{counter}.json"
        counter += 1
    
    save_collection(filename, data)
    return filename

def delete_collection(filename: str):
    """Deletes a collection file."""
    path = os.path.join(COLLECTIONS_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
