import os
import json
from typing import List, Dict, Any, Optional
from storage.store import load_json, save_json

from core.logger import get_logger

logger = get_logger()

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
    logger.debug(f"Loading collection: {filename}")
    return load_json(path)

def save_collection(filename: str, data: Dict[str, Any]):
    """Saves a collection to the collections directory."""
    ensure_collections_dir()
    path = os.path.join(COLLECTIONS_DIR, filename)
    logger.info(f"Saving collection: {filename}")
    save_json(path, data)

def import_external_collection(source_path: str) -> Optional[str]:
    """Imports a collection from an external JSON file and saves it locally."""
    logger.info(f"Importing collection from: {source_path}")
    data = load_json(source_path)
    
    # Basic validation for Postman v2.1
    if not data or "info" not in data or "item" not in data:
        logger.error(f"Failed to import collection: Invalid format in {source_path}")
        return None
    
    # We maintain the data structure as is, but we could sanitize it here if needed.
    # The current UI already handles the item recursion.
    
    name = data["info"].get("name", "Imported Collection")
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
    filename = f"{safe_name}.json"
    
    # Avoid simple collisions
    base_filename = filename
    counter = 1
    while os.path.exists(os.path.join(COLLECTIONS_DIR, filename)):
        filename = f"{safe_name}_{counter}.json"
        counter += 1
    
    save_collection(filename, data)
    logger.info(f"Collection imported and saved as: {filename}")
    return filename

def delete_collection(filename: str):
    """Deletes a collection file."""
    path = os.path.join(COLLECTIONS_DIR, filename)
    if os.path.exists(path):
        logger.warning(f"Deleting collection: {filename}")
        os.remove(path)

def create_new_collection(name: str) -> str:
    """Creates a new empty collection with the given name."""
    data = {
        "info": {
            "name": name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": []
    }
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(' ', '_')
    if not safe_name: safe_name = "new_collection"
    filename = f"{safe_name}.json"
    
    # Avoid collisions
    base_name = safe_name
    counter = 1
    while os.path.exists(os.path.join(COLLECTIONS_DIR, filename)):
        filename = f"{base_name}_{counter}.json"
        counter += 1
        
    save_collection(filename, data)
    return filename
