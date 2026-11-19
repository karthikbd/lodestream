"""End-to-end test of the ``s3`` source against a real S3-compatible server (MinIO).

    docker run -d -p 9000:9000 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \\
        minio/minio server /data{1...4}           # 4 drives: object versioning needs erasure coding
    LODESTREAM_E2E_S3=1 pytest tests/e2e/test_e2e_s3.py -v

boto3 must be installed (lodestream never installs it).
"""
import hashlib
import os
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("LODESTREAM_E2E_S3") != "1", reason="set LODESTREAM_E2E_S3=1 to run")

from fakes import FakeFileNet  # noqa: E402
from lodestream import Migration  # noqa: E402

ENDPOINT = os.environ.get("E2E_S3_ENDPOINT", "http://127.0.0.1:9000")
BIG = os.urandom(25 * 1024 * 1024)


@pytest.fixture(scope="module")
def bucket(monkeypatch_module):
    import boto3

    monkeypatch_module.setenv("AWS_ACCESS_KEY_ID", os.environ.get("E2E_S3_KEY", "minioadmin"))
    monkeypatch_module.setenv("AWS_SECRET_ACCESS_KEY", os.environ.get("E2E_S3_SECRET", "minioadmin"))
    monkeypatch_module.setenv("AWS_DEFAULT_REGION", "us-east-1")
    s3 = boto3.client("s3", endpoint_url=ENDPOINT)
    name = f"lodestream-e2e-{int(time.time())}"
    s3.create_bucket(Bucket=name)
    s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    s3.put_object(Bucket=name, Key="archive/readme.txt", Body=b"root of the archive")
    s3.put_object(Bucket=name, Key="archive/finance/2024/q1.pdf", Body=b"Q1 draft")
    time.sleep(1.1)
    s3.put_object(Bucket=name, Key="archive/finance/2024/q1.pdf", Body=b"Q1 final, longer")   # version 2
    s3.put_object(Bucket=name, Key="archive/hr/big-scan.tif", Body=BIG)
    s3.put_object(Bucket=name, Key="archive/hr/empty-folder/", Body=b"")                   # folder marker
    return s3, name


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def config(name, endpoint, versions):
    return {"manifest": "state/m.db",
            "source": {"type": "s3", "options": {"bucket": name, "prefix": "archive/", "endpoint_url": ENDPOINT,
                                                 "region": "us-east-1", "include_versions": versions}},
            "sink": {"type": "filenet_graphql", "options": {"endpoint": endpoint, "repository": "OS1"}},
            "mapping": {"properties": {"_path": "SourcePath"}, "folder": "/S3/{directory}"},
            "steps": ["inventory", "load", "verify"]}


@pytest.mark.parametrize("versions", [False, True])
def test_s3_to_filenet(bucket, tmp_path, versions):
    s3, name = bucket
    with FakeFileNet() as fn:
        fn.classes = {"Document": ["DocumentTitle", "SourcePath"]}
        cfg = config(name, fn.endpoint, versions)
        pre = Migration(cfg, str(tmp_path)).check(sample=5)
        assert all(r.status in ("ok", "skip") for r in pre), [(r.name, r.status, r.detail) for r in pre]
        Migration(cfg, str(tmp_path)).run()
        counts = {k: v[0] for k, v in Migration(cfg, str(tmp_path)).manifest.counts().items()}
        assert counts == {"VERIFIED": 4 if versions else 3}
        uploaded = [b for u in fn.uploads for b in u["files"].values()]
        assert hashlib.sha256(BIG).digest() in {hashlib.sha256(b).digest() for b in uploaded}
        assert b"Q1 final, longer" in uploaded
        assert (b"Q1 draft" in uploaded) is versions
        if versions:   # the older version was created first, the newer one checked in on top
            assert any("checkinDocument" in u["query"] for u in fn.uploads)
        queries = "\n".join(u["query"] for u in fn.uploads)
        assert 'fileInFolderIdentifier: "/S3/finance/2024"' in queries
