"""Fuzz the mapper (classes, property conversion, folder templates) and date parsing."""
import sys

import atheris

with atheris.instrument_imports():
    from lodestream.config import ConfigError
    from lodestream.mapping import Mapper
    from lodestream.models import DocumentRecord
    from lodestream.utils import parse_dt, to_iso

TYPES = ["", "string", "int", "float", "bool", "datetime", "date"]


def TestOneInput(data: bytes) -> None:  # noqa: N802
    fdp = atheris.FuzzedDataProvider(data)
    template = fdp.ConsumeUnicodeNoSurrogates(40)
    value = fdp.ConsumeUnicodeNoSurrogates(40)
    kind = TYPES[fdp.ConsumeIntInRange(0, len(TYPES) - 1)]
    try:
        m = Mapper({"folder": template or None, "classes": {value: "C"},
                    "properties": {"P": {"target": "T", "type": kind, "max_length": fdp.ConsumeIntInRange(1, 50)}},
                    "strip_path_prefixes": [fdp.ConsumeUnicodeNoSurrogates(10)]})
    except ConfigError:
        return
    rec = DocumentRecord("s", "s", 1, name=fdp.ConsumeUnicodeNoSurrogates(20),
                         directory=fdp.ConsumeUnicodeNoSurrogates(30), content_type=value, properties={"P": value})
    try:
        cls, props, folder = m.map(rec)
    except (ValueError, OverflowError):
        return   # a value that does not convert to the property's type: reported per document
    assert cls in ("C", "Document")
    if folder is not None:
        assert folder.startswith("/") and "//" not in folder
    try:
        dt = parse_dt(value)
    except (ValueError, OverflowError):
        return
    if dt is not None:
        assert parse_dt(to_iso(dt)) == dt.replace(microsecond=0)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
