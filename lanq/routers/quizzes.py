import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from lanq.deps import get_db, require_admin
from lanq.quizzes import (
    QUIZ_VALIDATION_FAILED,
    QuizIn,
    QuizUpdate,
    create_quiz,
    fetch_quiz,
    list_quizzes,
    remove_quiz,
    replace_quiz,
    update_errors,
    validation_errors,
)
from lanq.sessions import QUIZ_LOCKED, quiz_is_locked
from lanq.students import preview_quiz_payload
from lanq.validation import validation_detail

router = APIRouter(
    prefix="/api/admin/quizzes", dependencies=[Depends(require_admin)]
)


def ensure_valid(errors: list[dict[str, str]]) -> None:
    if errors:
        raise HTTPException(
            status_code=422,
            detail=validation_detail(QUIZ_VALIDATION_FAILED, errors),
        )


def require_editable(conn: sqlite3.Connection, quiz_id: int) -> None:
    if fetch_quiz(conn, quiz_id) is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    if quiz_is_locked(conn, quiz_id):
        raise HTTPException(status_code=409, detail=QUIZ_LOCKED)


@router.get("")
def get_quizzes(conn: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    return list_quizzes(conn)


@router.post("", status_code=201)
def post_quiz(
    body: QuizIn, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    ensure_valid(validation_errors(body))
    quiz_id = create_quiz(conn, body)
    quiz = fetch_quiz(conn, quiz_id)
    assert quiz is not None
    return quiz


@router.get("/{quiz_id}")
def get_quiz(quiz_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    quiz = fetch_quiz(conn, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


@router.get("/{quiz_id}/preview")
def preview_quiz(quiz_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    quiz = fetch_quiz(conn, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    snapshot = {
        "title": quiz["title"],
        "time_limit_seconds": quiz["time_limit_seconds"],
        "questions": [
            {
                "id": int(question["id"]),
                "text": question["text"],
                "options": [option["text"] for option in question["options"]],
                "correct_index": next(
                    index
                    for index, option in enumerate(question["options"])
                    if option["correct"]
                ),
            }
            for question in quiz["questions"]
        ],
    }
    return preview_quiz_payload(snapshot)


@router.put("/{quiz_id}")
def put_quiz(
    quiz_id: int, body: QuizUpdate, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    require_editable(conn, quiz_id)
    ensure_valid(update_errors(conn, quiz_id, body))
    replace_quiz(conn, quiz_id, body)
    quiz = fetch_quiz(conn, quiz_id)
    assert quiz is not None
    return quiz


@router.delete("/{quiz_id}")
def delete_quiz(
    quiz_id: int, conn: sqlite3.Connection = Depends(get_db)
) -> dict:
    require_editable(conn, quiz_id)
    remove_quiz(conn, quiz_id)
    return {"ok": True}
