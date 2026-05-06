import asyncio
import time
import httpx
from PySide6.QtCore import QThread, Signal, QObject

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
            # Execute the async request in a new event loop for this thread
            result = asyncio.run(self._execute_request())
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    async def _execute_request(self) -> dict:
        start_time = time.perf_counter()
        
        # Use httpx.AsyncClient for the request
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.request(
                method=self.method,
                url=self.url,
                headers=self.headers,
                content=self.body,
                params=self.params
            )
            
            end_time = time.perf_counter()
            elapsed_ms = int((end_time - start_time) * 1000)
            
            return {
                "status_code": response.status_code,
                "reason_phrase": response.reason_phrase,
                "headers": dict(response.headers),
                "text": response.text,
                "content": response.content,
                "elapsed_ms": elapsed_ms,
                "size": len(response.content)
            }
