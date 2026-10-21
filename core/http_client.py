"""HTTP engine on top of QtNetwork.

QNetworkAccessManager is asynchronous and runs on the Qt event loop, so the
UI never blocks, no worker threads or asyncio loops are needed, and the whole
network stack costs ~2 MB instead of ~20 MB for httpx. Cancel = ``abort()``.
"""
import os
from typing import List, Optional, Tuple

from PySide6.QtCore import QByteArray, QElapsedTimer, QFile, QIODevice, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (QHttpMultiPart, QHttpPart, QNetworkAccessManager, QNetworkProxy,
                               QNetworkProxyFactory, QNetworkReply, QNetworkRequest)

from core.logger import get_logger
from core.request_preparer import PreparedRequest

logger = get_logger()

E = QNetworkReply.NetworkError
_ERRORS = {
    E.ConnectionRefusedError: "Connection refused by {host}. Is the server running and is the port correct?",
    E.RemoteHostClosedError: "The server at {host} closed the connection unexpectedly.",
    E.HostNotFoundError: "Could not resolve host \"{host}\". Check the URL and your network/DNS.",
    E.TimeoutError: "The connection to {host} timed out.",
    E.SslHandshakeFailedError: "SSL/TLS handshake with {host} failed. The certificate may be invalid or "
                               "self-signed — you can turn off SSL verification in Settings.",
    E.TemporaryNetworkFailureError: "The network is temporarily unavailable.",
    E.NetworkSessionFailedError: "No network connection.",
    E.ProxyConnectionRefusedError: "The proxy server refused the connection. Check proxy settings.",
    E.ProxyConnectionClosedError: "The proxy server closed the connection unexpectedly.",
    E.ProxyNotFoundError: "Proxy host not found. Check proxy settings.",
    E.ProxyTimeoutError: "The connection to the proxy timed out.",
    E.ProxyAuthenticationRequiredError: "The proxy requires authentication.",
    E.ProtocolUnknownError: "Unsupported protocol in URL — use http:// or https://.",
    E.ProtocolInvalidOperationError: "The server rejected this kind of request.",
    E.TooManyRedirectsError: "Too many redirects.",
    E.InsecureRedirectError: "Refused to follow a redirect from HTTPS to HTTP.",
    E.UnknownNetworkError: "Network error while talking to {host}.",
}


def human_error(code, host: str, detail: str) -> str:
    template = _ERRORS.get(code)
    if template:
        message = template.format(host=host or "the server")
        if code in (E.UnknownNetworkError, E.ProtocolInvalidOperationError) and detail:
            message = message.rstrip(".") + f" ({detail.rsplit(' - ', 1)[-1]})."
        return message
    return detail or "Request failed."


def _pretty_header_name(name: str) -> str:
    if name.islower():
        return "-".join(p[:1].upper() + p[1:] for p in name.split("-"))
    return name


class ResponseData:
    __slots__ = ("status", "reason", "http_version", "headers", "body", "elapsed_ms", "ttfb_ms",
                 "url", "cache")

    def __init__(self):
        self.status = 0
        self.reason = ""
        self.http_version = "HTTP/1.1"
        self.headers: List[Tuple[str, str]] = []
        self.body = b""
        self.elapsed_ms = 0
        self.ttfb_ms = 0
        self.url = ""
        self.cache = {}  # per-response memo for formatted views

    @property
    def size(self) -> int:
        return len(self.body)

    def header(self, name: str) -> Optional[str]:
        name = name.lower()
        for k, v in self.headers:
            if k.lower() == name:
                return v
        return None

    @property
    def content_type(self) -> str:
        return (self.header("Content-Type") or "").split(";", 1)[0].strip().lower()


class RequestJob(QObject):
    finished = Signal(object)   # ResponseData — includes 4xx/5xx responses
    failed = Signal(str)        # human-readable network failure
    cancelled = Signal()

    def __init__(self, reply: QNetworkReply, timeout_s: float, max_bytes: int, host: str, parent=None):
        super().__init__(parent)
        self.reply = reply
        self.host = host
        self.max_bytes = max_bytes
        self._buffer = bytearray()
        self._done = False
        self._reason: Optional[str] = None
        self._ttfb = 0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = None
        if timeout_s > 0:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._on_timeout)
            self._timer.start(int(timeout_s * 1000))
        self.timeout_s = timeout_s
        reply.metaDataChanged.connect(self._on_meta)
        reply.readyRead.connect(self._on_ready_read)
        reply.finished.connect(self._on_finished)

    def elapsed_ms(self) -> int:
        return int(self._clock.elapsed())

    def is_running(self) -> bool:
        return not self._done

    def cancel(self):
        if not self._done:
            self._reason = "cancelled"
            self.reply.abort()

    def _on_timeout(self):
        if not self._done:
            self._reason = "timeout"
            self.reply.abort()

    def _on_meta(self):
        if not self._ttfb:
            self._ttfb = self.elapsed_ms()

    def _on_ready_read(self):
        self._buffer += self.reply.readAll().data()
        if self.max_bytes and len(self._buffer) > self.max_bytes and not self._done:
            self._reason = "too_large"
            self.reply.abort()

    def _on_finished(self):
        if self._done:
            return
        self._done = True
        if self._timer:
            self._timer.stop()
        reply = self.reply
        if self._reason is None:
            self._buffer += reply.readAll().data()
        elapsed = self.elapsed_ms()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            if self._reason == "cancelled":
                logger.info("Request cancelled")
                self.cancelled.emit()
            elif self._reason == "timeout":
                self.failed.emit(f"No response from {self.host} within {self.timeout_s:g} s (timeout). "
                                 "You can change the timeout in Settings.")
            elif self._reason == "too_large":
                self.failed.emit(f"Response is larger than {self.max_bytes // (1024 * 1024)} MB and was aborted. "
                                 "Raise the limit in Settings.")
            elif status is None:
                msg = human_error(reply.error(), self.host, reply.errorString())
                logger.warning("Request failed: %s (%s)", msg, reply.errorString())
                self.failed.emit(msg)
            else:
                resp = ResponseData()
                resp.status = int(status)
                resp.reason = str(reply.attribute(QNetworkRequest.Attribute.HttpReasonPhraseAttribute) or "")
                if reply.attribute(QNetworkRequest.Attribute.Http2WasUsedAttribute):
                    resp.http_version = "HTTP/2"
                resp.headers = [(_pretty_header_name(bytes(k).decode("latin-1")),
                                 bytes(v).decode("utf-8", errors="replace"))
                                for k, v in reply.rawHeaderPairs()]
                resp.body = bytes(self._buffer)
                resp.elapsed_ms = elapsed
                resp.ttfb_ms = self._ttfb or elapsed
                resp.url = reply.url().toString()
                logger.info("Response %s in %d ms (%d bytes)", resp.status, elapsed, resp.size)
                self.finished.emit(resp)
        finally:
            self._buffer = bytearray()
            reply.deleteLater()
            self.deleteLater()


class HttpClient(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self.verify_ssl = True
        self.follow_redirects = True
        self.timeout_s = 60.0
        self.max_bytes = 50 * 1024 * 1024
        self.send_cookies = True

    def apply_settings(self, settings):
        self.verify_ssl = bool(settings["verify_ssl"])
        self.follow_redirects = bool(settings["follow_redirects"])
        self.timeout_s = float(settings["request_timeout"] or 0)
        self.max_bytes = int(settings["max_response_mb"] or 0) * 1024 * 1024
        self.send_cookies = bool(settings["send_cookies"])
        mode = settings["proxy_mode"]
        if mode == "none":
            self.nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        elif mode == "custom" and settings["proxy_url"]:
            self.nam.setProxy(self._parse_proxy(settings["proxy_url"]))
        else:
            QNetworkProxyFactory.setUseSystemConfiguration(True)
            self.nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy))

    @staticmethod
    def _parse_proxy(url: str) -> QNetworkProxy:
        if "://" not in url:
            url = "http://" + url
        q = QUrl(url)
        ptype = (QNetworkProxy.ProxyType.Socks5Proxy if q.scheme().startswith("socks")
                 else QNetworkProxy.ProxyType.HttpProxy)
        return QNetworkProxy(ptype, q.host(), q.port(1080 if ptype == QNetworkProxy.ProxyType.Socks5Proxy else 8080),
                             q.userName(), q.password())

    def clear_cookies(self):
        from PySide6.QtNetwork import QNetworkCookieJar
        self.nam.setCookieJar(QNetworkCookieJar())

    def send(self, prep: PreparedRequest) -> RequestJob:
        """Starts the request. Raises ValueError for problems detected before
        anything is sent (invalid URL, unreadable file)."""
        url = QUrl(prep.url, QUrl.ParsingMode.TolerantMode)
        if not url.isValid() or not url.host():
            raise ValueError(f"Invalid URL: {prep.url}")
        if url.scheme().lower() not in ("http", "https"):
            raise ValueError(f"Unsupported protocol \"{url.scheme()}\" — use http:// or https://")

        req = QNetworkRequest(url)
        merged = {}
        for k, v in prep.headers:
            key = k.lower()
            if key in merged:
                sep = "; " if key == "cookie" else ", "
                merged[key] = (merged[key][0], merged[key][1] + sep + v)
            else:
                merged[key] = (k, v)
        for name, value in merged.values():
            req.setRawHeader(QByteArray(name.encode("latin-1", errors="replace")),
                             QByteArray(value.encode("utf-8")))
        A = QNetworkRequest.Attribute
        req.setAttribute(A.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy if self.follow_redirects
                         else QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        if not self.send_cookies:
            req.setAttribute(A.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual)
            req.setAttribute(A.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual)
        if url.scheme().lower() == "https" and not self.verify_ssl:
            from PySide6.QtNetwork import QSslSocket
            conf = req.sslConfiguration()
            conf.setPeerVerifyMode(QSslSocket.PeerVerifyMode.VerifyNone)
            req.setSslConfiguration(conf)

        verb = prep.method.encode("ascii", errors="replace")
        owned = []
        if prep.multipart is not None:
            multipart = self._build_multipart(prep.multipart)
            reply = self.nam.sendCustomRequest(req, verb, multipart)
            owned.append(multipart)
        elif prep.body_file:
            f = QFile(prep.body_file)
            if not f.open(QIODevice.OpenModeFlag.ReadOnly):
                raise ValueError(f"Cannot read body file: {prep.body_file}")
            reply = self.nam.sendCustomRequest(req, verb, f)
            owned.append(f)
        elif prep.method == "HEAD":
            reply = self.nam.head(req)
        elif prep.body is not None:
            reply = self.nam.sendCustomRequest(req, verb, QByteArray(prep.body))
        else:
            reply = self.nam.sendCustomRequest(req, verb)
        for obj in owned:
            obj.setParent(reply)
        if not self.verify_ssl:
            reply.sslErrors.connect(lambda _errors, r=reply: r.ignoreSslErrors())
        logger.info("%s %s", prep.method, prep.url)
        return RequestJob(reply, self.timeout_s, self.max_bytes, url.host(), self)

    @staticmethod
    def _build_multipart(parts) -> QHttpMultiPart:
        multipart = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType)
        for part in parts:
            hp = QHttpPart()
            name = part["name"].replace('"', "%22")
            if "file" in part:
                path = part["file"]
                f = QFile(path)
                if not f.open(QIODevice.OpenModeFlag.ReadOnly):
                    raise ValueError(f"Cannot read file for form field '{part['name']}': {path}")
                import mimetypes
                mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
                filename = os.path.basename(path).replace('"', "%22")
                hp.setHeader(QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                             f'form-data; name="{name}"; filename="{filename}"')
                hp.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, mime)
                hp.setBodyDevice(f)
                f.setParent(multipart)
            else:
                hp.setHeader(QNetworkRequest.KnownHeaders.ContentDispositionHeader, f'form-data; name="{name}"')
                hp.setBody(QByteArray(part["value"].encode("utf-8")))
            multipart.append(hp)
        return multipart
