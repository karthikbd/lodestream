"""Fuzz config parsing: TOML / JSON documents, ${VAR} expansion, step lists and key validation."""
import json
import sys

import atheris

with atheris.instrument_imports():
    from lodestream.config import (DEFAULT_STEPS, MAPPING_KEYS, TOP_LEVEL_KEYS, ConfigError, _expand,
                                   check_keys, normalize_steps)

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def TestOneInput(data: bytes) -> None:  # noqa: N802 (atheris naming)
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    for parse in ([tomllib.loads] if tomllib else []) + [json.loads]:
        try:
            doc = parse(text)
        except (ValueError, TypeError, RecursionError):
            continue
        doc = _expand(doc)                         # must never fail on parsed data
        if isinstance(doc, dict):
            for keys, where in ((TOP_LEVEL_KEYS, "top"), (MAPPING_KEYS, "mapping")):
                try:
                    check_keys(doc, keys, where)
                except ConfigError:
                    pass
            try:
                steps = normalize_steps(doc.get("steps") or DEFAULT_STEPS)
                assert all(isinstance(n, str) and isinstance(o, dict) for n, o in steps)
            except (ValueError, TypeError, AttributeError):
                pass
    assert _expand("${LODESTREAM_FUZZ_UNSET:-" + text.replace("}", "") + "}") == text.replace("}", "")


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
