import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from lanq.dashboard import (
    PARTICIPANT_NOT_FOUND,
    dashboard_payload,
    drilldown_payload,
)
from lanq.deps import get_db, require_admin
from lanq.export import csv_text, export_filename
from lanq.network import join_url
from lanq.qr import qr_svg
from lanq.sessions import (
    NO_ACTIVE_SESSION,
    SESSION_ALREADY_ACTIVE,
    SESSION_NOT_FOUND,
    StartSessionIn,
    active_session,
    create_session,
    delete_session,
    fetch_session,
    history_entries,
    session_payload,
    snapshot_of,
    stop_active_session,
)
from lanq.students import finalize_in_progress

router = APIRouter(
    prefix="/api/admin/sessions", dependencies=[Depends(require_admin)]
)


@router.post("", status_code=201)
def post_session(
    body: StartSessionIn, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    if active_session(conn) is not None:
        raise HTTPException(status_code=409, detail=SESSION_ALREADY_ACTIVE)
    try:
        session_id = create_session(conn, body.quiz_id)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409, detail=SESSION_ALREADY_ACTIVE
        ) from None
    if session_id is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    row = fetch_session(conn, session_id)
    assert row is not None
    return session_payload(row)


@router.post("/stop")
def stop_session(conn: sqlite3.Connection = Depends(get_db)) -> dict:
    stopped = stop_active_session(conn)
    if stopped is None:
        raise HTTPException(status_code=409, detail=NO_ACTIVE_SESSION)
    finalize_in_progress(conn, int(stopped["id"]), snapshot_of(stopped))
    return session_payload(stopped)


@router.get("/current")
def get_current_session(
    conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    row = active_session(conn)
    url = join_url()
    return {
        "session": session_payload(row) if row is not None else None,
        "join_url": url,
        "qr_svg": qr_svg(url),
    }


@router.get("/live")
def get_live_dashboard(conn: sqlite3.Connection = Depends(get_db)) -> dict:
    row = active_session(conn)
    if row is None:
        return {
            "session": None,
            "roster": [],
            "accuracy": [],
            "leaderboard": [],
        }
    return dashboard_payload(conn, row)


@router.get("/participants/{participant_id}")
def get_participant_drilldown(
    participant_id: int, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    session = active_session(conn)
    payload = (
        drilldown_payload(conn, session, participant_id)
        if session is not None
        else None
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=PARTICIPANT_NOT_FOUND)
    return payload


def _require_session(
    conn: sqlite3.Connection, session_id: int
) -> sqlite3.Row:
    row = fetch_session(conn, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    return row


@router.get("/history")
def get_session_history(
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    return history_entries(conn)


@router.get("/{session_id}/dashboard")
def get_session_dashboard(
    session_id: int, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    return dashboard_payload(conn, _require_session(conn, session_id))


@router.get("/{session_id}/participants/{participant_id}")
def get_session_participant_drilldown(
    session_id: int,
    participant_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    payload = drilldown_payload(
        conn, _require_session(conn, session_id), participant_id
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=PARTICIPANT_NOT_FOUND)
    return payload


@router.get("/{session_id}/export.csv")
def export_session_csv(
    session_id: int, conn: sqlite3.Connection = Depends(get_db)
) -> Response:
    session = _require_session(conn, session_id)
    filename = export_filename(session)
    return Response(
        content=csv_text(conn, session),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.delete("/{session_id}")
def delete_session_by_id(
    session_id: int, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    row = fetch_session(conn, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    if str(row["status"]) == "active":
        raise HTTPException(
            status_code=409,
            detail="Stop the session before deleting it",
        )
    delete_session(conn, session_id)
    return {"ok": True}
