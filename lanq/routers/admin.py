import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from lanq.auth import hash_password, new_token, verify_password
from lanq.clock import utcnow
from lanq.deps import SESSION_COOKIE, get_db, require_admin

GENERIC_LOGIN_ERROR = "Invalid username or password"

router = APIRouter(prefix="/api/admin")


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def setup_complete(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


_dummy_hash: str | None = None


def dummy_hash() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_hex(16))
    return _dummy_hash


@router.get("/setup-state")
def get_setup_state(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, bool]:
    return {"setup_complete": setup_complete(conn)}


@router.post("/setup", status_code=201)
def post_setup(
    body: Credentials, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, bool]:
    cursor = conn.execute(
        "INSERT INTO users (username, password_hash, created_at)"
        " SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM users)",
        (body.username, hash_password(body.password), utcnow()),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=403, detail="Setup has already been completed")
    return {"setup_complete": True}


@router.post("/login")
def post_login(
    body: Credentials,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, str]:
    row = conn.execute(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (body.username,),
    ).fetchone()
    stored_hash = str(row["password_hash"]) if row is not None else dummy_hash()
    password_matches = verify_password(body.password, stored_hash)
    if row is None or not password_matches:
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)
    token = new_token()
    conn.execute(
        "INSERT INTO admin_tokens (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, int(row["id"]), utcnow()),
    )
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/")
    return {"username": str(row["username"])}


@router.get("/me")
def get_me(username: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": username}


@router.post("/logout")
def post_logout(
    response: Response,
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, bool]:
    conn.execute("DELETE FROM admin_tokens")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/change-password")
def post_change_password(
    body: PasswordChange,
    response: Response,
    username: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, bool]:
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    assert row is not None
    if not verify_password(body.current_password, str(row["password_hash"])):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(body.new_password), int(row["id"])),
    )
    conn.execute("DELETE FROM admin_tokens")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
