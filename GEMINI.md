# Project Getman

Getman is a minimalistic, local-only desktop HTTP client built with Python and PySide6. It is designed for fast, simple API interaction without cloud dependencies.

## Tech Stack
- **Language:** Python 3.11+
- **UI Framework:** PySide6
- **HTTP Client:** `httpx` (async)
- **Highlighting:** `pygments`
- **Storage:** Local JSON files in `data/`

## Critical Commands
- **Run App:** `python main.py`
- **Install Deps:** `pip install -r requirements.txt`
- **View Logs:** Click "System Logs" in UI or `cat data/app.log`

## Project Structure
- `main.py`: Entry point and application initialization.
- `core/`: Core logic and non-UI components.
    - `http_client.py`: Asynchronous request execution using `QThread`.
    - `auth.py`: Management of authentication profiles and host mappings.
    - `collection.py`: Import/Export and handling of external collections.
    - `logger.py`: Centralized logging system with UI signals.
- `storage/`: Data persistence layers.
    - `store.py`: Atomic JSON read/write operations.
    - `history.py`: Request history management.
- `ui/`: UI components and panels.
    - `main_window.py`: Application layout and orchestration.
    - `request_panel.py`: Request builder (Params, Headers, Body, Auth).
    - `response_panel.py`: Response viewer with syntax highlighting.
    - `log_viewer.py`: Real-time system log monitor.
- `data/`: Local storage directory (ignored by git, except `.gitkeep` in collections).

## Coding Conventions
- **Async Handling:** Always use `core.http_client.HttpClientThread` (which uses `QThread`) to perform network requests. Never block the main UI thread.
- **Logging:** Use `core.logger.get_logger()` for all logging. Avoid `print()` statements.
- **Styling:** Follow PEP 8. Use type hints where possible.
- **UI Design:** Prefer `QSplitter` for resizable layouts. Use `QTableWidget` for key-value inputs.
- **Data Safety:** Use `storage.store` functions to ensure directory creation and consistent JSON formatting.

## Non-Negotiables
- No cloud synchronization or external account requirements.
- Maintain compatibility with Postman Collection v2.1 format for imports.
- Every major feature should log its start and completion/result.
