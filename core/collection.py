import os
import json
from typing import List, Dict, Any, Optional, Tuple
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

def save_openapi_collection(collection: dict, env_vars: dict = None,
                             auth_profiles: list = None,
                             collection_name: str = "",
                             create_env: bool = True,
                             import_auth: bool = True) -> Tuple[Optional[str], Optional[dict], int]:
    """Saves a converted OpenAPI collection with optional environment and auth profiles.

    Returns:
        Tuple of (collection_filename, environment_dict, endpoint_count)
    """
    if not collection:
        logger.error("No collection data provided")
        return None, None, 0

    if collection_name:
        collection["info"]["name"] = collection_name

    safe_name = "".join([c for c in collection["info"]["name"] if c.isalnum() or c in (' ', '_', '-')]).strip()
    if not safe_name:
        safe_name = "imported_openapi"

    filename = f"{safe_name}.json"
    counter = 1
    while os.path.exists(os.path.join(COLLECTIONS_DIR, filename)):
        filename = f"{safe_name}_{counter}.json"
        counter += 1

    endpoint_count = sum(len(f.get("item", [])) for f in collection.get("item", []))

    save_collection(filename, collection)
    logger.info(f"OpenAPI collection saved as: {filename} ({endpoint_count} endpoints)")

    result_env = None
    env_vars = env_vars or {}
    if create_env and env_vars:
        from core.environment import save_environments, get_all_environments
        env_name = f"{collection['info']['name']} Environment"
        new_env = {
            "name": env_name,
            "values": [{"key": k, "value": str(v), "enabled": True} for k, v in env_vars.items()],
        }
        envs = get_all_environments() or []
        envs.append(new_env)
        save_environments(envs)
        result_env = new_env
        logger.info(f"Created environment '{env_name}' with {len(env_vars)} variables")

    auth_profiles = auth_profiles or []
    if import_auth and auth_profiles:
        from core.auth import save_auth_entry
        for profile in auth_profiles:
            save_auth_entry(
                name=profile["name"],
                auth_type=profile["type"],
                auth_data=profile["data"],
            )
        logger.info(f"Imported {len(auth_profiles)} auth profiles")

    return filename, result_env, endpoint_count

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
