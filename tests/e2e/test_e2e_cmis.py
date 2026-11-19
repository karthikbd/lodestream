"""End-to-end test of the ``cmis`` source against a real CMIS 1.1 repository (Alfresco Community).

    docker compose -f tests/e2e/alfresco-compose.yml up -d    # takes 2-4 minutes to start
    LODESTREAM_E2E_CMIS=1 pytest tests/e2e/test_e2e_cmis.py -v

The test seeds the repository through the CMIS browser binding itself (folders, documents, a
second major version) and then migrates it with ``include_versions = true``.
"""
import base64
import json
import os
import time
import urllib.parse
import urllib.request
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("LODESTREAM_E2E_CMIS") != "1",
                                reason="set LODESTREAM_E2E_CMIS=1 to run")

from fakes import FakeFileNet  # noqa: E402
from lodestream import Migration  # noqa: E402

URL = os.environ.get("E2E_CMIS_URL", "http://127.0.0.1:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser")
USER, PASSWORD = os.environ.get("E2E_CMIS_USER", "admin"), os.environ.get("E2E_CMIS_PASSWORD", "admin")
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()


def _call(url, fields=None, content=None, filename="file.bin"):
    if fields is None:
        req = urllib.request.Request(url, headers={"Authorization": AUTH})
    else:
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields.items()]
        if content is not None:
            parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="content"; filename="{filename}"\r\n'
                          f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={
            "Authorization": AUTH, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read() or b"null")


def _props(**props):
    out = {}
    for i, (k, v) in enumerate(props.items()):
        out[f"propertyId[{i}]"] = k
        out[f"propertyValue[{i}]"] = v
    return out


@pytest.fixture(scope="module")
def tree():
    repos = _call(URL)
    root_url = next(iter(repos.values()))["rootFolderUrl"]
    root = _call(root_url + "?cmisselector=object&succinct=true")["succinctProperties"]["cmis:objectId"]
    name = f"lodestream-e2e-{int(time.time())}"

    def folder(parent, fname):
        obj = _call(f"{root_url}?objectId={urllib.parse.quote(parent)}&succinct=true",
                    {"cmisaction": "createFolder", **_props(**{"cmis:objectTypeId": "cmis:folder", "cmis:name": fname})})
        return obj["succinctProperties"]["cmis:objectId"]

    def document(parent, fname, content):
        obj = _call(f"{root_url}?objectId={urllib.parse.quote(parent)}&succinct=true",
                    {"cmisaction": "createDocument", "versioningState": "major",
                     **_props(**{"cmis:objectTypeId": "cmis:document", "cmis:name": fname})}, content, fname)
        return obj["succinctProperties"]["cmis:objectId"]

    top = folder(root, name)
    sub = folder(top, "2024")
    report = document(top, "report.pdf", b"REPORT v1")
    document(sub, "note.txt", b"a note")
    pwc = _call(f"{root_url}?objectId={urllib.parse.quote(report)}&succinct=true", {"cmisaction": "checkOut"})
    _call(f"{root_url}?objectId={urllib.parse.quote(pwc['succinctProperties']['cmis:objectId'])}&succinct=true",
          {"cmisaction": "checkIn", "major": "true", "checkinComment": "v2"}, b"REPORT v2 is longer", "report.pdf")
    return name


def test_cmis_to_filenet(tree, tmp_path):
    with FakeFileNet() as fn:
        fn.classes = {"Document": ["DocumentTitle", "SourceVersion"]}
        cfg = {"manifest": "state/m.db",
               "source": {"type": "cmis", "options": {"url": URL, "username": USER, "password": PASSWORD,
                                                      "folders": [f"/{tree}"], "include_versions": True}},
               "sink": {"type": "filenet_graphql", "options": {"endpoint": fn.endpoint, "repository": "OS1"}},
               "mapping": {"folder": "/CMIS/{directory}", "properties": {"_version_label": "SourceVersion"}},
               "steps": ["inventory", "load", "verify"]}
        pre = Migration(cfg, str(tmp_path)).check(sample=5)
        assert all(r.status in ("ok", "skip") for r in pre), [(r.name, r.status, r.detail) for r in pre]
        Migration(cfg, str(tmp_path)).run()
        counts = {k: v[0] for k, v in Migration(cfg, str(tmp_path)).manifest.counts().items()}
        assert counts == {"VERIFIED": 3}, counts           # report.pdf v1.0 + v2.0, note.txt
        uploaded = [b for u in fn.uploads for b in u["files"].values()]
        assert b"REPORT v1" in uploaded and b"REPORT v2 is longer" in uploaded and b"a note" in uploaded
        first = next(u["query"] for u in fn.uploads if b"REPORT v1" in u["files"].values())
        assert "createDocument" in first and '{SourceVersion: "1.0"}' in first
        assert any("checkinDocument" in u["query"] and '{SourceVersion: "2.0"}' in u["query"] for u in fn.uploads)
        assert any(f'fileInFolderIdentifier: "/CMIS/{tree}/2024"' in u["query"] for u in fn.uploads)
