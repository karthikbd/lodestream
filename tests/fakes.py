"""In-process HTTP servers standing in for FileNet Content Services GraphQL and a CMIS 1.1
browser-binding repository. They speak real HTTP, so the sink's streamed (chunked) multipart
uploads and the CMIS source's requests are tested over the wire."""
from __future__ import annotations

import email.parser
import email.policy
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List
from urllib.parse import parse_qs, urlparse


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    if handler.headers.get("Transfer-Encoding", "").lower() == "chunked":
        out = bytearray()
        while True:
            size = int(handler.rfile.readline().strip().split(b";")[0], 16)
            if size == 0:
                handler.rfile.readline()
                return bytes(out)
            out += handler.rfile.read(size)
            handler.rfile.readline()
    return handler.rfile.read(int(handler.headers.get("Content-Length", 0)))


class _Server:
    handler_cls: type

    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_cls)
        self.httpd.app = self  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


# ----------------------------------------------------------------------------- FileNet
class _FileNetHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, payload, status=200, cookie=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        app: FakeFileNet = self.server.app  # type: ignore[attr-defined]
        body = _read_body(self)
        ctype = self.headers.get("Content-Type", "")
        with app.lock:
            app.requests.append({"auth": self.headers.get("Authorization"),
                                 "xsrf": self.headers.get("ECM-CS-XSRF-Token"),
                                 "chunked": self.headers.get("Transfer-Encoding", "").lower() == "chunked"})
        if ctype.startswith("multipart/form-data"):
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
            parts = {p.get_param("name", header="content-disposition"): p for p in msg.iter_parts()}
            ops = json.loads(parts["operations"].get_content())
            mapping = json.loads(parts["map"].get_content())
            files = {k: parts[k].get_payload(decode=True) for k in mapping}
            q = ops["query"]
            with app.lock:
                app.uploads.append({"query": q, "files": files, "map": mapping})
                out = {}
                for alias, frag in re.findall(r"(\w+): (?:createDocument|checkinDocument)\((.*?)\) \{ id \}", q, re.S):
                    if any(n in frag for n in app.fail_names):
                        continue
                    app.n += 1
                    out[alias] = {"id": f"{{DOC-{app.n}}}"}
            errors = [{"message": "simulated failure", "path": [a]}
                      for a in re.findall(r"(\w+): (?:createDocument|checkinDocument)\(", q) if a not in out]
            return self._send({"data": out, **({"errors": errors} if errors else {})})
        q = json.loads(body)["query"]
        with app.lock:
            app.queries.append(q)
        if "__typename" in q:
            return self._send({"data": {"__typename": "Query"}}, cookie="ECM-CS-XSRF-Token=tok123; Path=/")
        if "folder(" in q:
            path = re.search(r'identifier: "([^"]+)"', q).group(1)
            return self._send({"data": {"folder": {"id": "F"} if path in app.folders else None}})
        if "createFolder" in q:
            parent = re.search(r'parent: \{ identifier: "([^"]+)"', q).group(1)
            name = re.search(r'name: "([^"]+)"', q).group(1)
            with app.lock:
                app.folders.add(parent.rstrip("/") + "/" + name)
            return self._send({"data": {"createFolder": {"id": "F"}}})
        if "checkoutDocument" in q:
            aliases = re.findall(r"(\w+): checkoutDocument", q)
            return self._send({"data": {a: {"id": "x", "reservation": {"id": f"RES-{a}"}} for a in aliases}})
        if "document(" in q:
            return self._send({"data": {"document": {"id": "x", "contentSize": None}}})
        return self._send({"errors": [{"message": "unexpected query"}]}, 400)


class FakeFileNet(_Server):
    handler_cls = _FileNetHandler

    def __init__(self):
        self.lock = threading.Lock()
        self.requests: List[dict] = []
        self.uploads: List[dict] = []
        self.queries: List[str] = []
        self.folders = {"/"}
        self.fail_names: List[str] = []
        self.n = 0
        super().__init__()

    @property
    def endpoint(self) -> str:
        return self.url + "/content-services-graphql/graphql"


# ----------------------------------------------------------------------------- CMIS
class _CmisHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        app: FakeCmis = self.server.app  # type: ignore[attr-defined]
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        base = app.url
        if u.path == "/cmis/browser":
            return self._json({"repo1": {"repositoryId": "repo1", "rootFolderUrl": base + "/cmis/browser/root"}})
        sel = q.get("cmisselector")
        if sel == "object":
            path = u.path[len("/cmis/browser/root"):] or "/"
            fid = app.paths[path]
            return self._json({"succinctProperties": {"cmis:objectId": fid}})
        if sel == "children":
            return self._json({"objects": [{"object": {"succinctProperties": p}} for p in app.children[q["objectId"]]],
                               "hasMoreItems": False})
        if sel == "versions":
            return self._json([{"succinctProperties": p} for p in app.versions[q["objectId"]]])
        if sel == "content":
            body = app.content[q["objectId"]]
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return self._json({"exception": "notSupported"}, 400)


class FakeCmis(_Server):
    """/Docs (folder) -> report.pdf (2 versions), /Docs/2024 -> note.txt"""

    handler_cls = _CmisHandler

    def __init__(self):
        def doc(oid, name, series, label, content, ts):
            self.content[oid] = content
            return {"cmis:objectId": oid, "cmis:baseTypeId": "cmis:document", "cmis:name": name,
                    "cmis:versionSeriesId": series, "cmis:versionLabel": label, "cmis:objectTypeId": "D:acme:report",
                    "cmis:contentStreamLength": len(content), "cmis:lastModificationDate": ts,
                    "acme:region": "EMEA"}

        self.content: Dict[str, bytes] = {}
        v1 = doc("r-1.0", "report.pdf", "r", "1.0", b"REPORT v1", 1700000000000)
        v2 = doc("r-2.0", "report.pdf", "r", "2.0", b"REPORT v2 longer", 1710000000000)
        note = doc("n-1.0", "note.txt", "n", "1.0", b"a note", 1705000000000)
        self.paths = {"/": "root", "/Docs": "docs"}
        self.children = {
            "docs": [v2, {"cmis:objectId": "y2024", "cmis:baseTypeId": "cmis:folder", "cmis:name": "2024"}],
            "y2024": [note],
        }
        self.versions = {"r-2.0": [v2, v1], "n-1.0": [note]}
        super().__init__()
