"""The only module in lodestream that speaks HTTP, built on the standard library (``urllib``).

It is used by exactly two plugins, and only towards the URL in their configuration:
the FileNet sink (``filenet_graphql``) and the CMIS source (``cmis``). There is no telemetry,
no update check and nothing is downloaded. ``tests/test_no_downloads.py`` fails the build if
any other module imports an HTTP client.

Uploads are streamed: a multipart body is generated part by part and sent with chunked
transfer encoding, so a batch of large files is never held in memory.
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, Tuple, Union

TRANSIENT_STATUS = (502, 503, 504)
_CHUNK = 1024 * 1024


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class Response:
    def __init__(self, status: int, body: bytes, headers: Dict[str, str]):
        self.status = status
        self.body = body
        self.headers = headers

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _ssl_context(verify: Union[bool, str]) -> ssl.SSLContext:
    if verify is False:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if isinstance(verify, str):
        return ssl.create_default_context(cafile=verify)
    return ssl.create_default_context()


class HttpClient:
    """Small urllib-based client: basic/bearer auth, cookies, TLS options, retries for
    idempotent calls, streaming multipart uploads."""

    def __init__(self, auth: Optional[Dict[str, Any]] = None, verify: Union[bool, str] = True,
                 timeout: float = 600, headers: Optional[Dict[str, str]] = None, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers: Dict[str, str] = dict(headers or {})
        self.cookies = http.cookiejar.CookieJar()
        auth = auth or {}
        if auth.get("type", "basic") == "basic" and auth.get("username"):
            token = base64.b64encode(f"{auth['username']}:{auth.get('password', '')}".encode()).decode()
            self.headers["Authorization"] = f"Basic {token}"
        elif auth.get("type") == "bearer":
            self.headers["Authorization"] = f"Bearer {auth['token']}"
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_ssl_context(verify)),
            urllib.request.HTTPCookieProcessor(self.cookies),
        )

    def cookie(self, name: str) -> Optional[str]:
        for c in self.cookies:
            if c.name == name:
                return c.value
        return None

    # ----------------------------------------------------------------- core
    def _open(self, req: urllib.request.Request) -> Response:
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return Response(resp.status, resp.read(), dict(resp.headers))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.read() or b"", dict(exc.headers or {}))

    def request(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None,
                json_body: Any = None, headers: Optional[Dict[str, str]] = None, retry: bool = True) -> Response:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        data = None
        hdrs = {**self.headers, **(headers or {})}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        attempt = 0
        while True:
            try:
                resp = self._open(urllib.request.Request(url, data=data, headers=hdrs, method=method))
                if resp.status in TRANSIENT_STATUS and retry and attempt < self.max_retries:
                    raise HttpError(resp.status, resp.text)
                return resp
            except (urllib.error.URLError, TimeoutError, ConnectionError, HttpError):
                if not retry or attempt >= self.max_retries:
                    raise
                time.sleep(min(2 ** attempt, 30))
                attempt += 1

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post_json(self, url: str, body: Any, headers: Optional[Dict[str, str]] = None) -> Response:
        return self.request("POST", url, json_body=body, headers=headers)

    def open_stream(self, url: str, params: Optional[Dict[str, Any]] = None) -> BinaryIO:
        """GET a (large) response body as a readable stream. Caller closes it."""
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers, method="GET")
        try:
            return self._opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise HttpError(exc.code, (exc.read() or b"").decode("utf-8", "replace")) from None

    def post_multipart(self, url: str, fields: List[Tuple[str, str]],
                       files: List[Tuple[str, str, BinaryIO, str]],
                       headers: Optional[Dict[str, str]] = None) -> Response:
        """Stream a multipart/form-data body: ``fields`` first (name, value), then ``files``
        (field name, file name, stream, content type). Never retried: the streams cannot be
        rewound, and a lost response may mean the server already processed the request."""
        boundary = f"lodestream-{uuid.uuid4().hex}"

        def body() -> Iterator[bytes]:
            for name, value in fields:
                yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n"
                       f"Content-Type: application/json\r\n\r\n").encode() + value.encode("utf-8") + b"\r\n"
            for name, filename, stream, ctype in files:
                safe = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
                yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                       f"filename=\"{safe}\"\r\nContent-Type: {ctype}\r\n\r\n").encode("utf-8")
                while True:
                    block = stream.read(_CHUNK)
                    if not block:
                        break
                    yield block
                yield b"\r\n"
            yield f"--{boundary}--\r\n".encode()

        hdrs = {**self.headers, **(headers or {}),
                "Content-Type": f"multipart/form-data; boundary={boundary}"}
        # An iterable body without Content-Length is sent with Transfer-Encoding: chunked.
        req = urllib.request.Request(url, data=body(), headers=hdrs, method="POST")
        return self._open(req)
