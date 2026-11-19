"""IBM FileNet sink using the Content Services GraphQL API (CS GraphQL).

Each batch of new documents is sent as ONE multipart HTTP request containing N
aliased ``createDocument`` mutations (GraphQL multipart request spec), so 50
documents cost one round trip instead of 50. New versions use aliased
``checkoutDocument`` + ``checkinDocument`` batches.

IMPORTANT: GraphQL field/argument names below follow the CS GraphQL API docs,
but they differ slightly across FileNet / CP4BA releases. Every query is a
template you can override in the config (create_template, checkout_template,
checkin_template, verify_template, folder_get_template, folder_create_template).
Validate against your server (GraphiQL at <endpoint>) with a 10-document
pilot before the bulk run. For the very highest throughput (>500 docs/s), the
same Sink contract can be implemented over the CE Java API (EJB transport) via
a small Java loader or JPype.
"""
from __future__ import annotations

import functools
import json
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from .. import _graphql as gql
from .._http import HttpClient
from ..checks import CheckContext, CheckResult, run
from ..models import DocumentRecord
from ..registry import register_sink
from ..utils import log, to_iso
from .base import LoadItem, LoadResult, Sink

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

CREATE_TEMPLATE = """<<alias>>: createDocument(
    repositoryIdentifier: <<repository>>
    classIdentifier: <<class>>
    <<folder_clause>>
    documentProperties: {
      name: <<name>>
      contentElements: { replace: [ { type: CONTENT_TRANSFER, contentType: <<mime>>, subContentTransfer: { content: $<<var>> } } ] }
      properties: [<<properties>>]
    }
    checkinAction: {}
  ) { id }"""

CHECKOUT_TEMPLATE = """<<alias>>: checkoutDocument(repositoryIdentifier: <<repository>>, identifier: <<id>>, checkoutAction: {}) { id reservation { id } }"""

CHECKIN_TEMPLATE = """<<alias>>: checkinDocument(
    repositoryIdentifier: <<repository>>
    identifier: <<id>>
    documentProperties: {
      contentElements: { replace: [ { type: CONTENT_TRANSFER, contentType: <<mime>>, subContentTransfer: { content: $<<var>> } } ] }
      properties: [<<properties>>]
    }
    checkinAction: {}
  ) { id }"""

VERIFY_TEMPLATE = """query { document(repositoryIdentifier: <<repository>>, identifier: <<id>>) { id contentSize } }"""
FOLDER_GET_TEMPLATE = """query { folder(repositoryIdentifier: <<repository>>, identifier: <<path>>) { id } }"""
CLASS_TEMPLATE = """query { classDescription(repositoryIdentifier: <<repository>>, identifier: <<class>>) { symbolicName propertyDescriptions { symbolicName } } }"""
FOLDER_CREATE_TEMPLATE = """mutation { createFolder(repositoryIdentifier: <<repository>>, folderProperties: { name: <<name>>, parent: { identifier: <<parent>> } }) { id } }"""


def gql_literal(value: Any) -> str:
    """Render a Python value as a GraphQL literal (strings are JSON-escaped)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(gql_literal(v) for v in value) + "]"
    if hasattr(value, "isoformat"):
        return json.dumps(to_iso(value) + "Z")
    return json.dumps(str(value), ensure_ascii=False)


def render(template: str, **values: str) -> str:
    for k, v in values.items():
        template = template.replace(f"<<{k}>>", v)
    return template


@register_sink("filenet_graphql")
class FileNetGraphQLSink(Sink):
    """Creates documents, versions and folders in FileNet through the Content Services GraphQL API.
    Uses only the Python standard library (urllib); uploads are streamed with chunked encoding.

        [sink]
        type = "filenet_graphql"

        [sink.options]
        endpoint = "https://cpe.example.com/content-services-graphql/graphql"
        repository = "OS1"                  # object store symbolic name or id
        auth = { type = "basic", username = "${FN_USER}", password = "${FN_PASSWORD}" }
        # auth = { type = "bearer", token = "${FN_TOKEN}" }
        file_in_folder = true               # file documents into mapping.folder (false = unfiled, fastest)
        create_folders = true
        name_property = "DocumentTitle"     # sent as `name`, removed from the properties list
        verify_tls = true                   # or the path of a PEM CA bundle
        timeout = 600
        max_retries = 3                     # non-upload calls (verify, folders, checkout)
        headers = {}                        # extra HTTP headers
        upload_scalar = "String"            # GraphQL type of the upload variables
        # create_template / checkout_template / checkin_template / verify_template /
        # folder_get_template / folder_create_template override each GraphQL query
    """

    def __init__(self, options: Optional[Dict[str, Any]] = None, base_dir: str = ".") -> None:
        super().__init__(options, base_dir)
        o = self.options
        self.endpoint = o["endpoint"]
        self.repository = gql_literal(o["repository"])
        self.file_in_folder = o.get("file_in_folder", True)
        self.create_folders = o.get("create_folders", True)
        self.name_property = o.get("name_property", "DocumentTitle")
        self.timeout = o.get("timeout", 600)
        self.max_retries = int(o.get("max_retries", 3))
        self.upload_scalar = o.get("upload_scalar", "String")
        self.t_create = o.get("create_template", CREATE_TEMPLATE)
        self.t_checkout = o.get("checkout_template", CHECKOUT_TEMPLATE)
        self.t_checkin = o.get("checkin_template", CHECKIN_TEMPLATE)
        self.t_verify = o.get("verify_template", VERIFY_TEMPLATE)
        self.t_folder_get = o.get("folder_get_template", FOLDER_GET_TEMPLATE)
        self.t_folder_create = o.get("folder_create_template", FOLDER_CREATE_TEMPLATE)
        self.t_class = o.get("class_template", CLASS_TEMPLATE)
        self.client: Optional[HttpClient] = None
        self._folders: Set[str] = {"/"}
        self._folder_lock = threading.Lock()

    # ------------------------------------------------------------- transport
    def open(self) -> None:
        if self.client is None:
            self.client = HttpClient(auth=self.options.get("auth"), verify=self.options.get("verify_tls", True),
                                     timeout=self.timeout, headers=self.options.get("headers"),
                                     max_retries=self.max_retries)
        # Probe: checks connectivity/auth and picks up the XSRF cookie if the server uses one.
        self._post("query { __typename }")

    @property
    def http(self) -> HttpClient:
        if self.client is None:
            raise RuntimeError("FileNet sink used before open()")
        return self.client

    def _headers(self) -> Dict[str, str]:
        token = self.client.cookie("ECM-CS-XSRF-Token") if self.client else None
        return {"ECM-CS-XSRF-Token": token} if token else {}

    @staticmethod
    def _parse(resp: Any) -> Dict[str, Any]:
        try:
            payload = resp.json()
        except ValueError:
            raise RuntimeError(f"HTTP {resp.status}: {resp.text[:300]}") from None
        if resp.status >= 400 and not payload.get("errors"):
            raise RuntimeError(f"HTTP {resp.status}: {str(payload)[:300]}")
        out: Dict[str, Any] = payload
        return out

    def _post(self, query: str) -> Dict[str, Any]:
        """JSON POST without uploads; the client retries transient failures (502/503/504, network)."""
        return self._parse(self.http.post_json(self.endpoint, {"query": query, "variables": {}},
                                                 headers=self._headers()))

    def _post_multipart(self, query: str, variables: Dict[str, Any], mapping: Dict[str, List[str]],
                        files: Dict[str, Tuple[str, Any, str]]) -> Dict[str, Any]:
        """GraphQL multipart request, streamed. Not retried: streams cannot be rewound and a
        lost response might mean the documents were created. Failures go back to the
        manifest as FAILED and are retried by a later run."""
        fields = [("operations", json.dumps({"query": query, "variables": variables})),
                  ("map", json.dumps(mapping))]
        parts = [(name, fname, stream, ctype) for name, (fname, stream, ctype) in files.items()]
        return self._parse(self.http.post_multipart(self.endpoint, fields, parts, headers=self._headers()))

    @staticmethod
    def _errors_by_alias(payload: Dict[str, Any]) -> Dict[Optional[str], str]:
        out: Dict[Optional[str], str] = {}
        for err in payload.get("errors") or []:
            path = err.get("path") or [None]
            key = path[0] if isinstance(path[0], str) else None
            out.setdefault(key, err.get("message", str(err))[:500])
        return out

    # ------------------------------------------------------------- folders
    def _ensure_folder(self, path: str) -> None:
        path = "/" + path.strip("/")
        if path in self._folders:
            return
        with self._folder_lock:
            parent = "/"
            for seg in [s for s in path.split("/") if s]:
                current = parent.rstrip("/") + "/" + seg
                if current not in self._folders:
                    got = self._post(render(self.t_folder_get, repository=self.repository,
                                            path=gql_literal(current)))
                    if not (got.get("data") or {}).get("folder"):
                        if not self.create_folders:
                            raise RuntimeError(f"Folder {current} does not exist")
                        made = self._post(render(self.t_folder_create, repository=self.repository,
                                                 name=gql_literal(seg), parent=gql_literal(parent)))
                        if not ((made.get("data") or {}).get("createFolder") or {}).get("id"):
                            raise RuntimeError(f"Could not create folder {current}: "
                                               f"{self._errors_by_alias(made)}")
                    self._folders.add(current)
                parent = current

    # ------------------------------------------------------------- loading
    def _props_literal(self, props: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        props = dict(props)
        name = props.pop(self.name_property, None)
        parts = []
        for k, v in props.items():
            if not _IDENT.match(k):
                raise ValueError(f"Invalid FileNet property name {k!r}")
            parts.append(f"{{{k}: {gql_literal(v)}}}")
        return ", ".join(parts), name

    def load_batch(self, items: List[LoadItem]) -> List[LoadResult]:
        results: Dict[str, LoadResult] = {}
        creates = [i for i in items if not i.previous_target_id]
        versions = [i for i in items if i.previous_target_id]
        if creates:
            self._create(creates, results)
        if versions:
            self._add_versions(versions, results)
        return [results.get(i.record.source_id) or LoadResult(i.record.source_id, error="no result")
                for i in items]

    def _upload(self, items: List[LoadItem], fragments: List[str], var_names: List[str],
                aliases: List[str], results: Dict[str, LoadResult], field: str) -> None:
        decls = ", ".join(f"${v}: {self.upload_scalar}" for v in var_names)
        query = f"mutation({decls}) {{\n  " + "\n  ".join(fragments) + "\n}"
        files, mapping = {}, {}
        try:
            for n, item in enumerate(items):
                files[f"f{n}"] = (item.record.name, item.open(), item.mime)
                mapping[f"f{n}"] = [f"variables.{var_names[n]}"]
            payload = self._post_multipart(query, dict.fromkeys(var_names), mapping, files)
        except Exception as exc:
            for item in items:
                results[item.record.source_id] = LoadResult(item.record.source_id,
                                                            error=f"{type(exc).__name__}: {exc}")
            return
        finally:
            for item in items:
                item.close()
        errors = self._errors_by_alias(payload)
        data = payload.get("data") or {}
        for alias, item in zip(aliases, items, strict=False):
            node = data.get(alias) or {}
            if node.get("id"):
                results[item.record.source_id] = LoadResult(item.record.source_id, target_id=node["id"])
            else:
                results[item.record.source_id] = LoadResult(
                    item.record.source_id, error=errors.get(alias) or errors.get(None) or f"no id from {field}")

    def _create(self, items: List[LoadItem], results: Dict[str, LoadResult]) -> None:
        ready: List[LoadItem] = []
        for item in items:
            try:
                if self.file_in_folder and item.folder:
                    self._ensure_folder(item.folder)
                ready.append(item)
            except Exception as exc:
                results[item.record.source_id] = LoadResult(item.record.source_id, error=f"folder: {exc}")
        if not ready:
            return
        fragments, var_names, aliases = [], [], []
        for n, item in enumerate(ready):
            props, name = self._props_literal(item.properties)
            folder_clause = (f"fileInFolderIdentifier: {gql_literal(item.folder)}"
                             if self.file_in_folder and item.folder else "")
            fragments.append(render(
                self.t_create, alias=f"d{n}", repository=self.repository,
                **{"class": gql_literal(item.target_class)}, folder_clause=folder_clause,
                name=gql_literal(name or item.record.name), mime=gql_literal(item.mime),
                var=f"c{n}", properties=props))
            var_names.append(f"c{n}")
            aliases.append(f"d{n}")
        self._upload(ready, fragments, var_names, aliases, results, "createDocument")

    def _add_versions(self, items: List[LoadItem], results: Dict[str, LoadResult]) -> None:
        checkout = " ".join(render(self.t_checkout, alias=f"k{n}", repository=self.repository,
                                   id=gql_literal(i.previous_target_id)) for n, i in enumerate(items))
        try:
            payload = self._post("mutation { " + checkout + " }")
        except Exception as exc:
            for i in items:
                results[i.record.source_id] = LoadResult(i.record.source_id, error=f"checkout: {exc}")
            return
        errors = self._errors_by_alias(payload)
        data = payload.get("data") or {}
        ready, reservations = [], []
        for n, item in enumerate(items):
            res = ((data.get(f"k{n}") or {}).get("reservation") or {}).get("id")
            if res:
                ready.append(item)
                reservations.append(res)
            else:
                results[item.record.source_id] = LoadResult(
                    item.record.source_id,
                    error="checkout: " + (errors.get(f"k{n}") or errors.get(None) or "no reservation"))
        if not ready:
            return
        fragments, var_names, aliases = [], [], []
        for n, (item, res) in enumerate(zip(ready, reservations, strict=False)):
            props, _ = self._props_literal(item.properties)
            fragments.append(render(self.t_checkin, alias=f"v{n}", repository=self.repository,
                                    id=gql_literal(res), mime=gql_literal(item.mime),
                                    var=f"c{n}", properties=props))
            var_names.append(f"c{n}")
            aliases.append(f"v{n}")
        self._upload(ready, fragments, var_names, aliases, results, "checkinDocument")
        for item, res in zip(ready, reservations, strict=False):
            r = results.get(item.record.source_id)
            if r and r.error:
                r.error += f" (document left checked out; reservation {res})"
                log.warning("Checkin failed for %s; reservation %s left checked out",
                            item.record.source_id, res)

    # ------------------------------------------------------------- verify
    def verify(self, record: DocumentRecord) -> Tuple[bool, str]:
        payload = self._post(render(self.t_verify, repository=self.repository,
                                    id=gql_literal(record.target_id)))
        node = (payload.get("data") or {}).get("document")
        if not node:
            return False, "not found: " + str(self._errors_by_alias(payload) or "")
        size = node.get("contentSize")
        if size is not None and record.size and int(size) != int(record.size):
            return False, f"size {size} != expected {record.size}"
        return True, "ok"

    # ------------------------------------------------------------- pre-flight
    def _sample_operations(self) -> Dict[str, str]:
        """Every operation this sink sends, rendered with sample values (as ``lodestream check``
        validates them)."""
        lit = gql_literal
        folder_clause = f"fileInFolderIdentifier: {lit('/lodestream-check')}" if self.file_in_folder else ""
        def mutation(body: str) -> str:
            return "mutation($c0: " + str(self.upload_scalar) + ") { " + body + " }"
        return {
            "create document (createDocument)": mutation(render(
                self.t_create, alias="d0", repository=self.repository, **{"class": lit("Document")},
                folder_clause=folder_clause, name=lit("check.pdf"), mime=lit("application/pdf"), var="c0",
                properties="{DocumentTitle: " + lit("check") + "}")),
            "check out (checkoutDocument)": "mutation { " + render(
                self.t_checkout, alias="k0", repository=self.repository, id=lit("{0}")) + " }",
            "check in (checkinDocument)": mutation(render(
                self.t_checkin, alias="v0", repository=self.repository, id=lit("{0}"), mime=lit("application/pdf"),
                var="c0", properties="")),
            "verify (document)": render(self.t_verify, repository=self.repository, id=lit("{0}")),
            "find folder (folder)": render(self.t_folder_get, repository=self.repository, path=lit("/")),
            "create folder (createFolder)": render(self.t_folder_create, repository=self.repository,
                                                   name=lit("x"), parent=lit("/")),
        }

    def check(self, cc: CheckContext) -> List[CheckResult]:
        results = [run("sink", f"connect and authenticate ({self.endpoint})", self.open)]
        if results[0].status == "fail":
            return results
        roots: Dict[str, str] = {}

        def introspect() -> Any:
            data = self._post(gql.ROOTS_QUERY).get("data") or {}
            schema = data.get("__schema") or {}
            if not schema:
                return "fail", "the server did not answer the introspection query (is introspection disabled?)"
            roots["query"] = (schema.get("queryType") or {}).get("name") or "Query"
            roots["mutation"] = (schema.get("mutationType") or {}).get("name") or "Mutation"
            return f"query type {roots['query']}, mutation type {roots['mutation']}"

        results.append(run("sink", "read the GraphQL schema", introspect))
        if not roots:
            return results

        def fetch_type(name: str) -> Any:
            return (self._post(gql.TYPE_QUERY % gql_literal(name)).get("data") or {}).get("__type")

        validator = gql.SchemaValidator(fetch_type)
        for label, op in self._sample_operations().items():
            def validate(op: str = op) -> Any:
                root = roots["mutation"] if op.lstrip().startswith("mutation") else roots["query"]
                errors = validator.validate(root, gql.parse_operation(op))
                if errors:
                    return "fail", "; ".join(errors[:4]) + (" ..." if len(errors) > 4 else "") + \
                        " -- override the template in [sink.options]"
                return None

            results.append(run("sink", f"GraphQL {label} matches this server", validate))

        def object_store() -> Any:
            got = self._post(render(self.t_folder_get, repository=self.repository, path=gql_literal("/")))
            if not (got.get("data") or {}).get("folder"):
                return "fail", f"repository {self.options['repository']!r}: root folder not found " \
                               f"{self._errors_by_alias(got) or ''}"
            return f"repository {self.options['repository']!r} answers"

        results.append(run("sink", "object store reachable", object_store))
        for cls, props in sorted(cc.classes.items()):
            results.append(run("mapping", f"class {cls} and its mapped properties exist",
                               functools.partial(self._check_class, validator, roots["query"], cls, props)))
        return results

    def _check_class(self, validator: gql.SchemaValidator, query_root: str, cls: str, props: List[str]) -> Any:
        q = render(self.t_class, repository=self.repository, **{"class": gql_literal(cls)})
        if validator.validate(query_root, gql.parse_operation(q)):
            return "skip", "this server's schema has no classDescription query; check classes in ACCE " \
                           "(or set class_template)"
        got = self._post(q)
        desc = (got.get("data") or {}).get("classDescription")
        if not desc:
            return "fail", f"class {cls!r} not found: {self._errors_by_alias(got) or 'no result'}"
        have = {p.get("symbolicName") for p in desc.get("propertyDescriptions") or []}
        missing = [p for p in props if p not in have and p != self.name_property]
        if missing:
            return "warn", f"properties not on {cls}: {', '.join(missing)} (fine if they are mapped only for other classes)"
        return f"{len(props)} mapped propert{'y' if len(props) == 1 else 'ies'} present"
