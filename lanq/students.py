import json
import random
import secrets
import sqlite3
from datetime import datetime, timedelta

from pydantic import BaseModel

from lanq.clock import utcnow
from lanq.sessions import active_session, snapshot_of

JOIN_VALIDATION_FAILED = "Join validation failed"
ANSWER_VALIDATION_FAILED = "Answer validation failed"
NO_ACTIVE_QUIZ = "There is no active quiz"
NOT_JOINED = "Not joined"
NOT_IN_RUNNING_QUIZ = "You have not joined the running quiz"
SESSION_ENDED = "The session has ended"
ALREADY_SUBMITTED = "You have already submitted"


class JoinIn(BaseModel):
    student_id: str
    name: str


class AnswerIn(BaseModel):
    question_id: int
    position: int


def join_errors(body: JoinIn) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not body.student_id.strip():
        errors.append(
            {"field": "student_id", "message": "Student ID must not be empty"}
        )
    if not body.name.strip():
        errors.append({"field": "name", "message": "Name must not be empty"})
    return errors


def participant_by_token(
    conn: sqlite3.Connection, token: str | None
) -> sqlite3.Row | None:
    if not token:
        return None
    return conn.execute(
        "SELECT * FROM participants WHERE auth_token = ?", (token,)
    ).fetchone()


def derive_state(
    active: sqlite3.Row | None, participant: sqlite3.Row | None
) -> str:
    if participant is None:
        return "join" if active is not None else "no_quiz"
    finalized_by = (
        participant["finalized_by"] if "finalized_by" in participant.keys() else None
    )
    ended_by_stop = finalized_by in ("stop", "expiry")
    if active is None:
        if participant["submitted_at"] is None:
            return "ended"
        if ended_by_stop:
            return "ended"
        return "submitted"
    if int(participant["session_id"]) != int(active["id"]):
        return "join"
    if participant["submitted_at"] is None:
        return "quiz"
    if ended_by_stop:
        return "ended"
    return "submitted"


def deadline_of(
    participant: sqlite3.Row, time_limit_seconds: int | None
) -> datetime | None:
    if not time_limit_seconds:
        return None
    joined_at = str(participant["joined_at"]).replace("Z", "+00:00")
    return datetime.fromisoformat(joined_at) + timedelta(seconds=int(time_limit_seconds))


def expired(participant: sqlite3.Row, time_limit_seconds: int | None) -> bool:
    deadline = deadline_of(participant, time_limit_seconds)
    if deadline is None:
        return False
    return datetime.fromisoformat(utcnow()) >= deadline


def game_state(
    conn: sqlite3.Connection,
    active: sqlite3.Row | None,
    participant: sqlite3.Row | None,
) -> str:
    state = derive_state(active, participant)
    if state == "quiz":
        assert active is not None
        assert participant is not None
        snapshot = snapshot_of(active)
        if expired(participant, snapshot["time_limit_seconds"]):
            finalize_and_grade(conn, participant, snapshot, finalized_by="expiry")
            return "ended"
    return state


def student_state(conn: sqlite3.Connection, token: str | None) -> str:
    active = active_session(conn)
    participant = participant_by_token(conn, token)
    return game_state(conn, active, participant)


def build_orders(
    snapshot: dict, seed: str
) -> tuple[list[int], dict[str, list[int]]]:
    generator = random.Random(seed)
    question_order = [
        int(question["id"]) for question in snapshot["questions"]
    ]
    generator.shuffle(question_order)
    option_orders: dict[str, list[int]] = {}
    for question in snapshot["questions"]:
        positions = list(range(len(question["options"])))
        generator.shuffle(positions)
        option_orders[str(question["id"])] = positions
    return question_order, option_orders


def create_participant(
    conn: sqlite3.Connection,
    session_id: int,
    snapshot: dict,
    student_id: str,
    name: str,
) -> str:
    seed = secrets.token_hex(16)
    question_order, option_orders = build_orders(snapshot, seed)
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO participants (session_id, student_id, name, joined_at,"
        " shuffle_seed, question_order_json, option_orders_json, auth_token)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            student_id,
            name,
            utcnow(),
            seed,
            json.dumps(question_order),
            json.dumps(option_orders),
            token,
        ),
    )
    return token


def is_same_attempt(
    participant: sqlite3.Row,
    session_id: int,
    student_id: str,
    name: str,
) -> bool:
    return (
        int(participant["session_id"]) == session_id
        and str(participant["student_id"]) == student_id
        and str(participant["name"]) == name
    )


def participant_option_orders(
    participant: sqlite3.Row,
) -> dict[str, list[int]]:
    return json.loads(str(participant["option_orders_json"]))


def answer_errors(
    snapshot: dict,
    option_orders: dict[str, list[int]],
    question_id: int,
    position: int,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if question_id not in {
        int(question["id"]) for question in snapshot["questions"]
    }:
        errors.append({"field": "question_id", "message": "Unknown question"})
        return errors
    order = option_orders.get(str(question_id))
    if order is None or not (0 <= position < len(order)):
        errors.append({"field": "position", "message": "Invalid option position"})
    return errors


def save_answer(
    conn: sqlite3.Connection,
    participant: sqlite3.Row,
    option_orders: dict[str, list[int]],
    question_id: int,
    position: int,
) -> None:
    canonical = option_orders[str(question_id)][position]
    conn.execute(
        "INSERT INTO answers (participant_id, question_id, chosen_index,"
        " answered_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (participant_id, question_id)"
        " DO UPDATE SET chosen_index = excluded.chosen_index,"
        " answered_at = excluded.answered_at",
        (int(participant["id"]), question_id, canonical, utcnow()),
    )


def saved_answers(
    conn: sqlite3.Connection, participant_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT question_id, chosen_index FROM answers WHERE participant_id = ?",
        (participant_id,),
    ).fetchall()


def finalize_and_grade(
    conn: sqlite3.Connection,
    participant: sqlite3.Row,
    snapshot: dict,
    finalized_by: str = "submit",
) -> int:
    if participant["submitted_at"] is not None:
        return int(participant["score"] or 0)
    correct = {
        int(question["id"]): int(question["correct_index"])
        for question in snapshot["questions"]
    }
    score = sum(
        1
        for row in saved_answers(conn, int(participant["id"]))
        if correct.get(int(row["question_id"]), -1) == int(row["chosen_index"])
    )
    conn.execute(
        "UPDATE participants SET score = ?, submitted_at = ?, finalized_by = ? WHERE id = ?",
        (score, utcnow(), finalized_by, int(participant["id"])),
    )
    return score


def finalize_in_progress(
    conn: sqlite3.Connection,
    session_id: int,
    snapshot: dict,
    finalized_by: str = "stop",
) -> None:
    rows = conn.execute(
        "SELECT * FROM participants WHERE session_id = ? AND submitted_at IS NULL",
        (session_id,),
    ).fetchall()
    for participant in rows:
        finalize_and_grade(conn, participant, snapshot, finalized_by=finalized_by)


def preview_quiz_payload(snapshot: dict, *, seed: str | None = None) -> dict:
    question_order, option_orders = build_orders(snapshot, seed or secrets.token_hex(16))
    questions_by_id = {
        int(question["id"]): question for question in snapshot["questions"]
    }
    questions = []
    for question_id in question_order:
        question = questions_by_id[int(question_id)]
        displayed_order = option_orders[str(question_id)]
        questions.append(
            {
                "id": int(question_id),
                "text": str(question["text"]),
                "options": [
                    str(question["options"][position])
                    for position in displayed_order
                ],
            }
        )
    return {
        "title": str(snapshot["title"]),
        "time_limit_seconds": snapshot["time_limit_seconds"],
        "deadline": None,
        "server_time": utcnow(),
        "questions": questions,
        "answers": {},
    }


def quiz_payload(
    conn: sqlite3.Connection,
    active: sqlite3.Row,
    participant: sqlite3.Row,
) -> dict:
    snapshot = snapshot_of(active)
    questions_by_id = {
        int(question["id"]): question for question in snapshot["questions"]
    }
    question_order = json.loads(str(participant["question_order_json"]))
    option_orders = json.loads(str(participant["option_orders_json"]))
    questions = []
    for question_id in question_order:
        question = questions_by_id[int(question_id)]
        displayed_order = option_orders[str(question_id)]
        questions.append(
            {
                "id": int(question_id),
                "text": str(question["text"]),
                "options": [
                    str(question["options"][position])
                    for position in displayed_order
                ],
            }
        )
    answers: dict[str, int] = {}
    for row in saved_answers(conn, int(participant["id"])):
        question_id = int(row["question_id"])
        canonical = int(row["chosen_index"])
        displayed_order = option_orders.get(str(question_id))
        if displayed_order is not None and canonical in displayed_order:
            answers[str(question_id)] = displayed_order.index(canonical)
    time_limit = snapshot["time_limit_seconds"]
    deadline = deadline_of(participant, time_limit)
    return {
        "title": str(snapshot["title"]),
        "time_limit_seconds": time_limit,
        "deadline": deadline.isoformat() if deadline is not None else None,
        "server_time": utcnow(),
        "questions": questions,
        "answers": answers,
    }
