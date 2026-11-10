from collections.abc import Sequence
from typing import Any

VALIDATION_FAILED = "Validation failed"


def validation_detail(message: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    return {"message": message, "errors": errors}


def field_path(loc: Sequence[Any]) -> str:
    path = ""
    for part in loc:
        if part in ("body", "path", "query", "header", "cookie"):
            continue
        if isinstance(part, int):
            path += f"[{part}]"
        elif path:
            path += f".{part}"
        else:
            path = str(part)
    return path
