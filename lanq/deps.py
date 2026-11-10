import sqlite3
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request

from lanq.db import connect

SESSION_COOKIE = "lanq_session"
PARTICIPANT_COOKIE = "lanq_participant"


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with connect(request.app.state.db_path) as conn:
        yield conn


def require_admin(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = conn.execute(
        "SELECT u.username FROM admin_tokens t"
        " JOIN users u ON u.id = t.user_id WHERE t.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(row["username"])
