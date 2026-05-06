import re
from typing import List, Dict, Any, Optional
from storage.store import load_json, save_json

ENV_FILE = "data/environments.json"

def get_all_environments() -> List[Dict[str, Any]]:
    """Returns the full list of environment configurations."""
    return load_json(ENV_FILE, [])

def save_environments(envs: List[Dict[str, Any]]):
    """Saves the list of environment configurations."""
    save_json(ENV_FILE, envs)

def apply_env(text: str, env_vars: Dict[str, str]) -> str:
    """Replaces {{variable_name}} with values from the environment dictionary."""
    if not isinstance(text, str):
        return text
        
    def replace_match(match):
        var_name = match.group(1).strip()
        return env_vars.get(var_name, match.group(0))
        
    # Pattern to match {{variable}}
    pattern = r"\{\{(.+?)\}\}"
    return re.sub(pattern, replace_match, text)

def get_env_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Returns an environment by its name."""
    envs = get_all_environments()
    for env in envs:
        if env["name"] == name:
            return env
    return None
