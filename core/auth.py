import uuid
from typing import List, Dict, Any, Optional
from storage.store import load_json, save_json

AUTH_STORE_FILE = "data/auth_store.json"

def get_auth_data() -> Dict[str, Any]:
    """Returns the full auth store data."""
    return load_json(AUTH_STORE_FILE, {"entries": [], "host_mapping": {}})

def get_auth_entries() -> List[Dict[str, Any]]:
    """Returns the list of saved auth profiles."""
    return get_auth_data().get("entries", [])

def save_auth_entry(name: str, auth_type: str, auth_data: Dict[str, Any], entry_id: Optional[str] = None) -> str:
    """Saves or updates an auth profile. Returns the entry ID."""
    store = get_auth_data()
    entries = store["entries"]
    
    if entry_id:
        for entry in entries:
            if entry["id"] == entry_id:
                entry.update({
                    "name": name,
                    "type": auth_type,
                    "data": auth_data
                })
                break
        else:
            # If ID not found, treat as new
            entry_id = str(uuid.uuid4())
            entries.append({
                "id": entry_id,
                "name": name,
                "type": auth_type,
                "data": auth_data
            })
    else:
        entry_id = str(uuid.uuid4())
        entries.append({
            "id": entry_id,
            "name": name,
            "type": auth_type,
            "data": auth_data
        })
    
    save_json(AUTH_STORE_FILE, store)
    return entry_id

def delete_auth_entry(entry_id: str):
    """Deletes an auth profile and its host mappings."""
    store = get_auth_data()
    store["entries"] = [e for e in store["entries"] if e["id"] != entry_id]
    
    # Clean up host mapping
    mapping = store.get("host_mapping", {})
    keys_to_delete = [host for host, aid in mapping.items() if aid == entry_id]
    for key in keys_to_delete:
        del mapping[key]
        
    save_json(AUTH_STORE_FILE, store)

def get_auth_by_id(entry_id: str) -> Optional[Dict[str, Any]]:
    """Returns an auth profile by its ID."""
    for entry in get_auth_entries():
        if entry["id"] == entry_id:
            return entry
    return None

def set_last_auth_for_host(host: str, auth_id: str):
    """Maps a host to the last used auth profile ID."""
    store = get_auth_data()
    if "host_mapping" not in store:
        store["host_mapping"] = {}
    store["host_mapping"][host] = auth_id
    save_json(AUTH_STORE_FILE, store)

def get_last_auth_for_host(host: str) -> Optional[str]:
    """Returns the last used auth profile ID for a given host."""
    store = get_auth_data()
    return store.get("host_mapping", {}).get(host)
