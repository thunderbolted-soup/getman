import os
import copy
import base64
import hashlib
import time
from typing import Dict, Any, List, Optional
from PySide6.QtCore import QUrl
from core.environment import apply_env
from core.logger import get_logger

logger = get_logger()

def apply_env_recursive(data: Any, env_vars: Dict[str, str]) -> Any:
    """Recursively applies environment variables to strings, dicts, and lists."""
    if isinstance(data, str):
        return apply_env(data, env_vars)
    elif isinstance(data, dict):
        return {apply_env_recursive(k, env_vars): apply_env_recursive(v, env_vars) for k, v in data.items()}
    elif isinstance(data, list):
        return [apply_env_recursive(i, env_vars) for i in data]
    return data

class PreparedRequest:
    def __init__(self):
        self.method = "GET"
        self.url = ""
        self.headers = {}
        self.params = {}
        self.body = None
        self.files = {} # For multipart
        self.env_vars = {}

def prepare_request(
    method: str, 
    url: str, 
    headers: dict, 
    body: Any, 
    params: dict, 
    env_vars: dict, 
    pre_script: str = "",
    default_headers: dict = None,
    auth_entry: dict = None
) -> PreparedRequest:
    """
    Centrally prepares a request by executing scripts, applying environments, 
    merging headers, and handling auth.
    """
    prep = PreparedRequest()
    prep.env_vars = env_vars.copy()
    
    # 1. Execute Pre-request Script
    if pre_script and pre_script.strip():
        try:
            # Context for script
            exec_globals = {
                "env": prep.env_vars,
                "hashlib": hashlib,
                "time": time,
                "os": os
            }
            exec(pre_script, exec_globals)
            prep.env_vars = exec_globals.get("env", prep.env_vars)
            logger.info("Pre-request script executed in Preparer")
        except Exception as e:
            logger.error(f"Pre-request script failed in Preparer: {e}")
            # We continue with original env if script fails
    
    # 2. Merge Default Headers
    final_headers = (default_headers or {}).copy()
    final_headers.update(headers)
    
    # 3. Apply Auth
    if auth_entry:
        _apply_auth(final_headers, auth_entry)
        
    # 4. Recursively apply environment variables to everything
    prep.method = apply_env_recursive(method, prep.env_vars)
    prep.url = apply_env_recursive(url, prep.env_vars)
    prep.headers = apply_env_recursive(final_headers, prep.env_vars)
    prep.params = apply_env_recursive(params, prep.env_vars)
    prep.body = apply_env_recursive(body, prep.env_vars)
    
    return prep

def _apply_auth(headers: dict, auth_entry: dict):
    a_type = auth_entry.get("type")
    data = auth_entry.get("data", {})
    if a_type == "bearer":
        headers["Authorization"] = f"Bearer {data.get('token', '')}"
    elif a_type == "basic":
        user = data.get("username", "")
        pw = data.get("password", "")
        auth_str = base64.b64encode(f"{user}:{pw}".encode()).decode()
        headers["Authorization"] = f"Basic {auth_str}"
    elif a_type == "apikey":
        key = data.get("key", "X-Api-Key")
        val = data.get("value", "")
        headers[key] = val

def generate_curl(prep: PreparedRequest) -> str:
    """Generates a cURL command from a PreparedRequest object."""
    url = prep.url
    if prep.params:
        from PySide6.QtCore import QUrlQuery
        q_url = QUrl(url)
        query = QUrlQuery(q_url.query())
        for k, v in prep.params.items():
            query.addQueryItem(str(k), str(v))
        q_url.setQuery(query)
        url = q_url.toString()

    curl = f"curl -X {prep.method} '{url}'"
    
    for k, v in prep.headers.items():
        curl += f" \\\n  -H '{k}: {v}'"
    
    if prep.body:
        if isinstance(prep.body, list): # form-data
            for item in prep.body:
                key = item.get("key")
                val = item.get("value")
                if item.get("type") == "File":
                    curl += f" \\\n  -F '{key}=@{val}'"
                else:
                    safe_val = str(val).replace("'", "'\\''")
                    curl += f" \\\n  -F '{key}={safe_val}'"
        else:
            safe_body = str(prep.body).replace("'", "'\\''")
            curl += f" \\\n  -d '{safe_body}'"
            
    return curl
