from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from lanq.db import init_db
from lanq.paths import DEFAULT_DB_PATH, STATIC_DIR
from lanq.routers import admin, quizzes, sessions, students
from lanq.validation import VALIDATION_FAILED, field_path, validation_detail


def create_app(db_path: Path | None = None) -> FastAPI:
    resolved_db_path = db_path if db_path is not None else DEFAULT_DB_PATH
    init_db(resolved_db_path)

    app = FastAPI(title="LANQ")
    app.state.db_path = resolved_db_path
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(admin.router)
    app.include_router(quizzes.router)
    app.include_router(sessions.router)
    app.include_router(students.router)

    @app.get("/", include_in_schema=False)
    def student_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "student" / "index.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "admin" / "index.html")

    @app.exception_handler(RequestValidationError)
    async def malformed_payload(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"field": field_path(error["loc"]), "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": validation_detail(VALIDATION_FAILED, errors)},
        )

    return app


_default_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
