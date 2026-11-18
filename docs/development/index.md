# Development

```{toctree}
:maxdepth: 2

architecture
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
