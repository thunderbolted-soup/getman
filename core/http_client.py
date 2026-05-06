import asyncio
import time
import httpx
from PySide6.QtCore import QThread, Signal, QObject
from core.logger import get_logger

logger = get_logger()

class HttpClientThread(QThread):
    """
    A thread that executes an HTTP request using httpx and asyncio.
    Emits signals upon success or failure.
    """
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, method: str, url: str, headers: dict = None, body: str = None, params: dict = None):
        super().__init__()
        self.method = method
        self.url = url
        self.headers = headers or {}
        self.body = body
        self.params = params

    def run(self):
        try:
            logger.info(f"Starting request: {self.method} {self.url}")
            # Execute the async request in a new event loop for this thread
            result = asyncio.run(self._execute_request())
            self.finished.emit(result)
        except httpx.ConnectError:
            msg = "Could not resolve hostname or connect to server."
            logger.error(msg)
            self.error.emit(msg)
        except httpx.ConnectTimeout:
            msg = "Connection timed out."
            logger.error(msg)
            self.error.emit(msg)
        except httpx.ReadTimeout:
            msg = "Server took too long to respond (Read Timeout)."
            logger.error(msg)
            self.error.emit(msg)
        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            self.error.emit(str(e))

    async def _execute_request(self) -> dict:
        start_time = time.perf_counter()
        
        # Use httpx.AsyncClient with a default User-Agent
        async with httpx.AsyncClient(
            timeout=60.0, 
            follow_redirects=True,
            headers={"User-Agent": "Postman/7.0.0"}
        ) as client:
            response = await client.request(
                method=self.method,
                url=self.url,
                headers=self.headers,
                content=self.body,
                params=self.params
            )
            
            end_time = time.perf_counter()
            elapsed_ms = int((end_time - start_time) * 1000)
            
            logger.info(f"Response received: {response.status_code} ({elapsed_ms}ms)")
            
            return {
                "status_code": response.status_code,
                "reason_phrase": response.reason_phrase,
                "headers": dict(response.headers),
                "text": response.text,
                "content": response.content,
                "elapsed_ms": elapsed_ms,
                "size": len(response.content)
            }
