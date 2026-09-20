"""Make every ``src/<layer>`` directory importable by bare module name.

The pipeline is organised into layer packages (``core``, ``ingest``,
``model``, ``squad``) but modules still import each other flatly
(``from common import ...``, ``import team_model``) rather than by layer
path. Each runnable script imports this module for its side effect — it
puts every layer directory on ``sys.path`` — so those bare imports resolve
no matter which layer folder the script lives in.

Entry-point scripts start with::

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import _bootstrap  # noqa: F401,E402

Pure library modules (common, loaders, team_model, simulator,
squad_quality) don't need it: whatever imports them has already run the
bootstrap.
"""
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parent
for _layer in sorted(_SRC.iterdir()):
    if _layer.is_dir() and not _layer.name.startswith((".", "_")):
        _p = str(_layer)
        if _p not in sys.path:
            sys.path.insert(0, _p)
