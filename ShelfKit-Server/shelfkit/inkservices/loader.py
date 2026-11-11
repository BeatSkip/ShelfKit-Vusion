"""Find and import the apps in inkapps/.

Each folder `inkapps/<id>/` with an `app.py` is one app; the folder name is its id
and app.py must define a module-level `app = InkApp("<id>", ...)`. A folder whose
name starts with `_` or `.` is ignored (templates, scratch).

Every load imports the files afresh (a new module object each time), which is what
makes "reload" in the UI pick up an edited app. Whatever goes wrong inside an app -
a syntax error, an exception at import, no `app` - is recorded against that app and
never stops the others or the server.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from .sdk import InkApp

INKAPPS_DIR = Path(__file__).resolve().parents[2] / "inkapps"


@dataclass
class LoadedApp:
    id: str
    path: Path                 # the app's folder
    app: InkApp | None
    error: str | None


def _where(exc: BaseException, source: Path) -> str:
    """'<Type>: <msg> (app.py line N)', the line taken from the app's own file."""
    line = None
    if isinstance(exc, SyntaxError):
        line = exc.lineno
    else:
        for frame in traceback.extract_tb(exc.__traceback__):
            if Path(frame.filename) == source:
                line = frame.lineno
    text = f"{type(exc).__name__}: {exc}"
    return f"{text} (app.py line {line})" if line else text


def load_app(folder: Path) -> LoadedApp:
    app_id = folder.name
    source = folder / "app.py"
    module_name = f"inkapps_{app_id.replace('-', '_')}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, source)
        if spec is None or spec.loader is None:
            return LoadedApp(app_id, folder, None, "cannot import app.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules.pop(module_name, None)
        spec.loader.exec_module(module)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - an app must not stop the server
        return LoadedApp(app_id, folder, None, _where(exc, source))

    app = getattr(module, "app", None)
    if not isinstance(app, InkApp):
        return LoadedApp(app_id, folder, None,
                         "app.py must define  app = InkApp(...)  at module level")
    if app.id != app_id:
        return LoadedApp(app_id, folder, None,
                         f"app id {app.id!r} does not match its folder {app_id!r}")
    app.folder = folder
    return LoadedApp(app_id, folder, app, None)


def load_apps(root: Path = INKAPPS_DIR) -> dict[str, LoadedApp]:
    root = Path(root)
    if not root.is_dir():
        return {}
    apps = {}
    for folder in sorted(root.iterdir()):
        if (not folder.is_dir() or folder.name[:1] in "_."
                or not (folder / "app.py").is_file()):
            continue
        apps[folder.name] = load_app(folder)
    return apps
