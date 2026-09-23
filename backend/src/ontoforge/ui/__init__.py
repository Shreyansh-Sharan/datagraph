"""Serving the built interface.

The product has one interface: the React app in ``frontend/``. The API carries no copy of it.
A deployment that wants the API to serve it too (Databricks Apps, a single container) points
``ONTOFORGE_UI_DIR`` at a build; otherwise ``/ui/`` says where the app lives rather than
pretending to be it.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

NOT_BUILT = ("This API serves no interface. The app lives in frontend/: build it and set "
             "ONTOFORGE_UI_DIR to the build directory, or run the web image, which serves it "
             "and proxies this API.")


class _Build(StaticFiles):
    """A vite build: hashed assets cached for a year, the shell never cached, deep links served."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith("assets"):
                raise                                                       # a missing asset is missing
            response = await super().get_response("index.html", scope)      # a route inside the app
        if isinstance(response, FileResponse) and str(response.path).endswith("index.html"):
            response.headers["Cache-Control"] = "no-cache"                  # a deploy must be picked up
        elif response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount(app: FastAPI, ui_dir: str | None) -> None:
    """Mount the build at /ui, or a single handler that explains why there is nothing there."""
    directory = Path(ui_dir).expanduser() if ui_dir else None
    if directory and (directory / "index.html").is_file():
        app.mount("/ui", _Build(directory=directory, html=True), name="ui")
        return
    detail = NOT_BUILT if directory is None else f"{NOT_BUILT} ONTOFORGE_UI_DIR is {directory}, which holds no index.html."

    async def missing(_scope, _receive, send) -> None:
        await JSONResponse({"detail": detail}, status_code=503)(_scope, _receive, send)

    app.mount("/ui", missing, name="ui")
