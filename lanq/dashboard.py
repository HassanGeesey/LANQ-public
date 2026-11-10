import sqlite3

from lanq.sessions import session_payload, snapshot_of
from lanq.students import saved_answers

PARTICIPANT_NOT_FOUND = "Participant not found"


def correct_index_map(snapshot: dict) -> dict[int, int]:
    return {
        int(question["id"]): int(question["correct_index"])
        for question in snapshot["questions"]
    }


def graded_score(snapshot: dict, answers: list[tuple[int, int]]) -> int:
    correct = correct_index_map(snapshot)
    return sum(
        1
        for question_id, chosen_index in answers
        if correct.get(question_id, -1) == chosen_index
    )


def accuracy_stats(
    snapshot: dict, answers: dict[int, list[tuple[int, int]]], total: int
) -> list[dict]:
    correct = correct_index_map(snapshot)
    answered: dict[int, int] = {}
    right: dict[int, int] = {}
    for saved in answers.values():
        for question_id, chosen_index in saved:
            answered[question_id] = answered.get(question_id, 0) + 1
            if correct.get(question_id, -1) == chosen_index:
                right[question_id] = right.get(question_id, 0) + 1
    stats: list[dict] = []
    for question in snapshot["questions"]:
        question_id = int(question["id"])
        count = answered.get(question_id, 0)
        stats.append(
            {
                "question_id": question_id,
                "text": str(question["text"]),
                "answered_count": count,
                "correct_count": right.get(question_id, 0),
                "participant_count": total,
                "unanswered": count == 0,
            }
        )
    return stats


def participant_status(
    participant: sqlite3.Row, saved: list[tuple[int, int]], snapshot: dict
) -> tuple[str, int | None]:
    if participant["submitted_at"] is not None:
        return "submitted", int(participant["score"] or 0)
    if saved:
        return "in_progress", graded_score(snapshot, saved)
    return "joined", None


def answers_by_participant(
    conn: sqlite3.Connection, session_id: int
) -> dict[int, list[tuple[int, int]]]:
    answers: dict[int, list[tuple[int, int]]] = {}
    for row in conn.execute(
        "SELECT a.participant_id, a.question_id, a.chosen_index"
        " FROM answers a JOIN participants p ON p.id = a.participant_id"
        " WHERE p.session_id = ?",
        (session_id,),
    ):
        answers.setdefault(int(row["participant_id"]), []).append(
            (int(row["question_id"]), int(row["chosen_index"]))
        )
    return answers


def roster_entries(
    conn: sqlite3.Connection,
    session: sqlite3.Row,
    answers: dict[int, list[tuple[int, int]]],
) -> list[dict]:
    snapshot = snapshot_of(session)
    roster: list[dict] = []
    for participant in conn.execute(
        "SELECT id, student_id, name, joined_at, submitted_at, score"
        " FROM participants WHERE session_id = ? ORDER BY joined_at, id",
        (int(session["id"]),),
    ):
        saved = answers.get(int(participant["id"]), [])
        status, score = participant_status(participant, saved, snapshot)
        roster.append(
            {
                "id": int(participant["id"]),
                "student_id": str(participant["student_id"]),
                "name": str(participant["name"]),
                "joined_at": str(participant["joined_at"]),
                "submitted_at": participant["submitted_at"],
                "status": status,
                "score": score,
            }
        )
    return roster


def dashboard_payload(conn: sqlite3.Connection, session: sqlite3.Row) -> dict:
    snapshot = snapshot_of(session)
    session_id = int(session["id"])
    answers = answers_by_participant(conn, session_id)
    roster = roster_entries(conn, session, answers)

    submitted: list[tuple[int, str, dict]] = [
        (int(entry["score"] or 0), str(entry["submitted_at"]), entry)
        for entry in roster
        if entry["status"] == "submitted"
    ]
    submitted.sort(key=lambda entry: (-entry[0], entry[1]))
    leaderboard = [
        {
            "rank": rank,
            "id": int(entry["id"]),
            "student_id": entry["student_id"],
            "name": entry["name"],
            "score": score,
            "submitted_at": submitted_at,
        }
        for rank, (score, submitted_at, entry) in enumerate(
            submitted, start=1
        )
    ]

    return {
        "session": session_payload(session),
        "roster": roster,
        "accuracy": accuracy_stats(snapshot, answers, len(roster)),
        "leaderboard": leaderboard,
    }


def drilldown_payload(
    conn: sqlite3.Connection, session: sqlite3.Row, participant_id: int
) -> dict | None:
    participant = conn.execute(
        "SELECT id, student_id, name, joined_at, submitted_at, score"
        " FROM participants WHERE id = ? AND session_id = ?",
        (participant_id, int(session["id"])),
    ).fetchone()
    if participant is None:
        return None
    snapshot = snapshot_of(session)
    saved = [
        (int(row["question_id"]), int(row["chosen_index"]))
        for row in saved_answers(conn, participant_id)
    ]
    status, score = participant_status(participant, saved, snapshot)
    chosen_by_question = dict(saved)
    questions: list[dict] = []
    for question in snapshot["questions"]:
        question_id = int(question["id"])
        correct_index = int(question["correct_index"])
        options = [str(option) for option in question["options"]]
        chosen = chosen_by_question.get(question_id)
        chosen_option = None
        if chosen is not None and 0 <= chosen < len(options):
            chosen_option = options[chosen]
        if chosen is None:
            result = "unanswered"
        elif chosen == correct_index:
            result = "correct"
        else:
            result = "wrong"
        questions.append(
            {
                "question_id": question_id,
                "text": str(question["text"]),
                "options": options,
                "chosen_index": chosen,
                "chosen_option": chosen_option,
                "correct_index": correct_index,
                "correct_option": options[correct_index],
                "result": result,
            }
        )
    return {
        "participant": {
            "id": int(participant["id"]),
            "student_id": str(participant["student_id"]),
            "name": str(participant["name"]),
            "joined_at": str(participant["joined_at"]),
            "submitted_at": participant["submitted_at"],
            "status": status,
            "score": score,
        },
        "questions": questions,
    }
