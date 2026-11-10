import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from lanq.deps import PARTICIPANT_COOKIE, get_db
from lanq.sessions import active_session, snapshot_of
from lanq.students import (
    ALREADY_SUBMITTED,
    ANSWER_VALIDATION_FAILED,
    JOIN_VALIDATION_FAILED,
    NOT_IN_RUNNING_QUIZ,
    NOT_JOINED,
    NO_ACTIVE_QUIZ,
    SESSION_ENDED,
    AnswerIn,
    JoinIn,
    answer_errors,
    create_participant,
    finalize_and_grade,
    game_state,
    is_same_attempt,
    join_errors,
    participant_by_token,
    participant_option_orders,
    quiz_payload,
    save_answer,
    student_state,
)
from lanq.validation import validation_detail

router = APIRouter(prefix="/api/student")


def game_state_error(state: str) -> None:
    if state == "submitted":
        raise HTTPException(status_code=409, detail=ALREADY_SUBMITTED)
    if state == "ended":
        raise HTTPException(status_code=409, detail=SESSION_ENDED)
    raise HTTPException(status_code=409, detail=NOT_IN_RUNNING_QUIZ)


def joined_game_state(
    request: Request, conn: sqlite3.Connection
) -> tuple[sqlite3.Row, sqlite3.Row | None, str]:
    token = request.cookies.get(PARTICIPANT_COOKIE)
    participant = participant_by_token(conn, token)
    if participant is None:
        raise HTTPException(status_code=401, detail=NOT_JOINED)
    active = active_session(conn)
    return participant, active, game_state(conn, active, participant)


@router.get("/state")
def get_state(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, str]:
    token = request.cookies.get(PARTICIPANT_COOKIE)
    return {"state": student_state(conn, token)}


@router.post("/join", status_code=201, response_model=None)
def post_join(
    body: JoinIn,
    request: Request,
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, str] | JSONResponse:
    errors = join_errors(body)
    if errors:
        raise HTTPException(
            status_code=422,
            detail=validation_detail(JOIN_VALIDATION_FAILED, errors),
        )
    active = active_session(conn)
    if active is None:
        raise HTTPException(status_code=409, detail=NO_ACTIVE_QUIZ)

    token = request.cookies.get(PARTICIPANT_COOKIE)
    student_id = body.student_id.strip()
    name = body.name.strip()
    session_id = int(active["id"])
    participant = participant_by_token(conn, token)
    if participant is not None and is_same_attempt(
        participant, session_id, student_id, name
    ):
        return JSONResponse(
            content={"state": game_state(conn, active, participant)}
        )

    new_token = create_participant(
        conn, session_id, snapshot_of(active), student_id, name
    )
    response.set_cookie(
        PARTICIPANT_COOKIE, new_token, httponly=True, samesite="lax", path="/"
    )
    return {"state": "quiz"}


@router.get("/quiz")
def get_quiz(
    request: Request, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    participant, active, state = joined_game_state(request, conn)
    if state != "quiz":
        game_state_error(state)
    assert active is not None
    return quiz_payload(conn, active, participant)


@router.post("/answer")
def post_answer(
    body: AnswerIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, bool]:
    participant, active, state = joined_game_state(request, conn)
    if state != "quiz":
        game_state_error(state)
    assert active is not None
    option_orders = participant_option_orders(participant)
    errors = answer_errors(
        snapshot_of(active), option_orders, body.question_id, body.position
    )
    if errors:
        raise HTTPException(
            status_code=422,
            detail=validation_detail(ANSWER_VALIDATION_FAILED, errors),
        )
    save_answer(
        conn, participant, option_orders, body.question_id, body.position
    )
    return {"saved": True}


@router.post("/submit")
def post_submit(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, str | int]:
    participant, active, state = joined_game_state(request, conn)
    if state == "submitted":
        return {
            "state": "submitted",
            "score": int(participant["score"] or 0),
        }
    if state != "quiz":
        game_state_error(state)
    assert active is not None
    score = finalize_and_grade(conn, participant, snapshot_of(active))
    return {"state": "submitted", "score": score}
