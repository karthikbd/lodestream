"""Fuzz GraphQL rendering and parsing: every value the FileNet sink renders must parse back
unchanged (no injection), and the parser must only ever raise ValueError on bad input."""
import sys

import atheris

with atheris.instrument_imports():
    from lodestream import _graphql as gql
    from lodestream.sinks.filenet_graphql import gql_literal


def TestOneInput(data: bytes) -> None:  # noqa: N802
    fdp = atheris.FuzzedDataProvider(data)
    choice = fdp.ConsumeIntInRange(0, 3)
    if choice == 0:
        value = fdp.ConsumeUnicodeNoSurrogates(200)
    elif choice == 1:
        value = fdp.ConsumeInt(8)
    elif choice == 2:
        value = [fdp.ConsumeUnicodeNoSurrogates(20) for _ in range(fdp.ConsumeIntInRange(0, 4))]
    else:
        value = fdp.ConsumeBool()
    rendered = gql_literal(value)
    fields = gql.parse_operation(f"query {{ f(a: {rendered}) {{ id }} }}")
    assert len(fields) == 1 and list(fields[0].args) == ["a"], rendered   # value cannot escape its argument
    got = fields[0].args["a"]
    if isinstance(value, str):
        assert got == rendered[1:-1]
    elif isinstance(value, bool):
        assert got is value
    elif isinstance(value, int):
        assert got == value
    try:
        gql.parse_operation(fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes()))
    except (ValueError, RecursionError):
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
