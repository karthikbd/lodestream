"""A small GraphQL document parser and schema validator, used by ``lodestream check``.

It parses the operations the FileNet sink will send (rendered from its templates, including any
the user overrides) and validates every field, argument, input-object field and enum value against
the schema the server reports through introspection. That turns "field names differ between
FileNet releases" from a failure halfway through a load into a precise message before it starts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

_TOKEN = re.compile(r'\$?[A-Za-z_][A-Za-z0-9_]*|"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|[{}\[\]():,!=@]')

TYPE_REF = "kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } }"
TYPE_QUERY = ("query { __type(name: %s) { kind name "
              "fields { name args { name type { " + TYPE_REF + " } } type { " + TYPE_REF + " } } "
              "inputFields { name type { " + TYPE_REF + " } } enumValues { name } } }")
ROOTS_QUERY = "query { __schema { queryType { name } mutationType { name } } }"


class Enum(str):
    """An unquoted GraphQL enum value (e.g. CONTENT_TRANSFER)."""


@dataclass
class Var:
    name: str


@dataclass
class Field:
    name: str
    alias: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    selection: List["Field"] = field(default_factory=list)


def _skip_ignored(text: str, pos: int) -> int:
    """Skip whitespace and ``#`` comments (linear; comments never start inside a string)."""
    n = len(text)
    while pos < n:
        c = text[pos]
        if c.isspace():
            pos += 1
        elif c == "#":
            newline = text.find("\n", pos)
            pos = n if newline == -1 else newline + 1
        else:
            break
    return pos


def tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    pos = _skip_ignored(text, 0)
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"cannot parse GraphQL near: {text[pos:pos + 30]!r}")
        tokens.append(m.group(0))
        pos = _skip_ignored(text, m.end())
    return tokens


class _Parser:
    def __init__(self, tokens: List[str]):
        self.t, self.i = tokens, 0

    def peek(self) -> Optional[str]:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, expected: Optional[str] = None) -> str:
        tok = self.peek()
        if tok is None or (expected is not None and tok != expected):
            raise ValueError(f"expected {expected or 'a token'}, found {tok!r}")
        self.i += 1
        return tok

    def value(self) -> Any:
        tok = self.peek()
        if tok == "{":
            self.take("{")
            obj: Dict[str, Any] = {}
            while self.peek() != "}":
                if self.peek() == ",":
                    self.take(",")
                    continue
                key = self.take()
                self.take(":")
                obj[key] = self.value()
            self.take("}")
            return obj
        if tok == "[":
            self.take("[")
            items = []
            while self.peek() != "]":
                if self.peek() == ",":
                    self.take(",")
                    continue
                items.append(self.value())
            self.take("]")
            return items
        tok = self.take()
        if tok.startswith("$"):
            return Var(tok[1:])
        if tok.startswith('"'):
            return tok[1:-1]
        if tok in ("true", "false"):
            return tok == "true"
        if tok == "null":
            return None
        if re.match(r"-?\d", tok):
            return float(tok) if "." in tok else int(tok)
        return Enum(tok)

    def field(self) -> Field:
        name = self.take()
        alias = None
        if self.peek() == ":":
            self.take(":")
            alias, name = name, self.take()
        f = Field(name, alias)
        if self.peek() == "(":
            self.take("(")
            while self.peek() != ")":
                if self.peek() == ",":
                    self.take(",")
                    continue
                key = self.take()
                self.take(":")
                f.args[key] = self.value()
            self.take(")")
        if self.peek() == "{":
            f.selection = self.selection()
        return f

    def selection(self) -> List[Field]:
        self.take("{")
        out = []
        while self.peek() != "}":
            if self.peek() == ",":
                self.take(",")
                continue
            out.append(self.field())
        self.take("}")
        return out


def parse_operation(text: str) -> List[Field]:
    """Parse ``mutation(...) { ... }`` / ``query { ... }`` or a bare list of root fields."""
    p = _Parser(tokenize(text))
    if p.peek() in ("query", "mutation"):
        p.take()
        if p.peek() not in ("{", None) and p.peek() != "(":
            p.take()  # operation name
        if p.peek() == "(":  # variable definitions
            depth = 0
            while True:
                tok = p.take()
                depth += tok == "("
                depth -= tok == ")"
                if depth == 0:
                    break
        return p.selection()
    fields = []
    while p.peek() is not None:
        fields.append(p.field())
    return fields


def named(type_ref: Dict[str, Any]) -> Dict[str, Any]:
    while type_ref.get("ofType"):
        type_ref = type_ref["ofType"]
    return type_ref


def is_list(type_ref: Dict[str, Any]) -> bool:
    while type_ref:
        if type_ref.get("kind") == "LIST":
            return True
        type_ref = type_ref.get("ofType") or {}
    return False


class SchemaValidator:
    """Validates parsed fields against a schema fetched lazily through ``fetch_type(name)``."""

    def __init__(self, fetch_type: Callable[[str], Optional[Dict[str, Any]]]):
        self._fetch = fetch_type
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def type(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self._cache:
            self._cache[name] = self._fetch(name)
        return self._cache[name]

    def validate(self, root_type: str, fields: List[Field]) -> List[str]:
        errors: List[str] = []
        t = self.type(root_type)
        if not t:
            return [f"type {root_type} not found in schema"]
        for f in fields:
            self._field(t, f, root_type, errors)
        return errors

    def _field(self, parent: Dict[str, Any], f: Field, path: str, errors: List[str]) -> None:
        fields = {x["name"]: x for x in parent.get("fields") or []}
        here = f"{path}.{f.name}"
        if f.name.startswith("__"):
            return
        if f.name not in fields:
            near = ", ".join(sorted(n for n in fields if n[:4].lower() == f.name[:4].lower())[:6])
            errors.append(f"{here}: no such field on {parent['name']}" + (f" (similar: {near})" if near else ""))
            return
        spec = fields[f.name]
        args = {a["name"]: a for a in spec.get("args") or []}
        for key, value in f.args.items():
            if key not in args:
                errors.append(f"{here}({key}:): no such argument (has: {', '.join(sorted(args))})")
                continue
            self._value(args[key]["type"], value, f"{here}({key}:)", errors)
        if f.selection:
            target = self.type(named(spec["type"])["name"])
            if target:
                for sub in f.selection:
                    self._field(target, sub, here, errors)

    def _value(self, type_ref: Dict[str, Any], value: Any, path: str, errors: List[str]) -> None:
        base = named(type_ref)
        if isinstance(value, Var) or value is None:
            return
        if isinstance(value, list):
            for v in value:
                self._value(_item_type(type_ref), v, f"{path}[]", errors)
            return
        if base.get("kind") == "INPUT_OBJECT":
            t = self.type(base["name"])
            if not t:
                return
            if not isinstance(value, dict):
                errors.append(f"{path}: expected an input object of type {base['name']}")
                return
            input_fields = {x["name"]: x for x in t.get("inputFields") or []}
            for key, v in value.items():
                if key not in input_fields:
                    errors.append(f"{path}.{key}: no such input field on {base['name']} "
                                  f"(has: {', '.join(sorted(input_fields))})")
                    continue
                self._value(input_fields[key]["type"], v, f"{path}.{key}", errors)
        elif base.get("kind") == "ENUM" and isinstance(value, Enum):
            t = self.type(base["name"])
            names = {e["name"] for e in (t or {}).get("enumValues") or []}
            if names and str(value) not in names:
                errors.append(f"{path}: {value} is not a value of {base['name']} (has: {', '.join(sorted(names))})")


def _item_type(type_ref: Dict[str, Any]) -> Dict[str, Any]:
    t: Union[Dict[str, Any], None] = type_ref
    while t and t.get("kind") == "NON_NULL":
        t = t.get("ofType")
    if t and t.get("kind") == "LIST":
        return t.get("ofType") or {}
    return type_ref
