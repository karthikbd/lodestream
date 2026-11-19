# Development

```{toctree}
:maxdepth: 2

architecture
security-assurance
dependencies
testing
releasing
```

```console
$ git clone https://github.com/karthikbd/lodestream && cd lodestream
$ python -m venv .venv && . .venv/bin/activate
$ pip install -e ".[test,docs]"
$ pytest -q                                   # unit + pipeline + over-the-wire HTTP tests, no server needed
$ python -m sphinx -W -b html docs docs/_build/html   # this documentation, warnings are errors
```

## Project

- [Governance](https://github.com/karthikbd/lodestream/blob/main/GOVERNANCE.md): roles, decisions, who holds which keys, continuity.
- [Roadmap](https://github.com/karthikbd/lodestream/blob/main/ROADMAP.md): plans for the next 12 months.
- [Contributing](https://github.com/karthikbd/lodestream/blob/main/CONTRIBUTING.md): how to propose a change, review standards, DCO.
- [Code of Conduct](https://github.com/karthikbd/lodestream/blob/main/CODE_OF_CONDUCT.md).
- [Security policy](https://github.com/karthikbd/lodestream/blob/main/SECURITY.md): reporting, response, supported versions.
