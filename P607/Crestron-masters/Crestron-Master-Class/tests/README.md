# tests

From the class folder, with the environment active:

```sh
python tests/run.py
```

It passed if the last line says `OK` (176 tests, about a minute on Python 3.10). The
`test_*.py` files test the library and the demos against fake devices, never `config/` or a
real device. `test_dmnax_server.py` drives the real clients against an in-process
[dmnax-server](../dmnax-server/README.md).

## Manual check

```sh
python -u tests/verify_live.py --route
```

`verify_live.py` runs every MCP server and the direct demo on a real device,
checks each change over a separate connection, then restores the zone. `--route`
allows it to route the player to the zone. It writes `verification_*.log`.
