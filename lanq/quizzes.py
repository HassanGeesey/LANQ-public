import json
import sqlite3

from pydantic import BaseModel

from lanq.clock import utcnow


class OptionIn(BaseModel):
    text: str
    correct: bool


class QuestionIn(BaseModel):
    text: str
    options: list[OptionIn]


class QuestionUpdate(QuestionIn):
    id: int | None = None


class QuizIn(BaseModel):
    title: str
    time_limit_seconds: int | None = None
    questions: list[QuestionIn]


class QuizUpdate(BaseModel):
    title: str
    time_limit_seconds: int | None = None
    questions: list[QuestionUpdate]


MIN_OPTIONS = 2
MAX_OPTIONS = 6
QUIZ_VALIDATION_FAILED = "Quiz validation failed"


def validation_errors(
    quiz: QuizIn | QuizUpdate,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not quiz.title.strip():
        errors.append({"field": "title", "message": "Title must not be empty"})
    if quiz.time_limit_seconds is not None and quiz.time_limit_seconds <= 0:
        errors.append(
            {
                "field": "time_limit_seconds",
                "message": "Time limit must be a positive number of seconds",
            }
        )
    for question_index, question in enumerate(quiz.questions):
        prefix = f"questions[{question_index}]"
        if not question.text.strip():
            errors.append(
                {
                    "field": f"{prefix}.text",
                    "message": "Question text must not be empty",
                }
            )
        if not MIN_OPTIONS <= len(question.options) <= MAX_OPTIONS:
            errors.append(
                {
                    "field": f"{prefix}.options",
                    "message": (
                        "A question must have between"
                        f" {MIN_OPTIONS} and {MAX_OPTIONS} options"
                    ),
                }
            )
        for option_index, option in enumerate(question.options):
            if not option.text.strip():
                errors.append(
                    {
                        "field": f"{prefix}.options[{option_index}].text",
                        "message": "Option text must not be empty",
                    }
                )
        correct_count = sum(1 for option in question.options if option.correct)
        if correct_count != 1:
            marked = (
                "none are"
                if correct_count == 0
                else f"{correct_count} are"
            )
            errors.append(
                {
                    "field": f"{prefix}.options",
                    "message": f"Exactly one option must be marked correct, but {marked}",
                }
            )
    return errors



def correct_index(question: QuestionIn | QuestionUpdate) -> int:
    return next(i for i, option in enumerate(question.options) if option.correct)


def question_values(
    question: QuestionIn | QuestionUpdate,
) -> tuple[str, str, int]:
    return (
        question.text.strip(),
        json.dumps([option.text.strip() for option in question.options]),
        correct_index(question),
    )


def insert_questions(
    conn: sqlite3.Connection, quiz_id: int, questions: list[QuestionIn]
) -> None:
    for position, question in enumerate(questions):
        insert_question(conn, quiz_id, position, question)


def insert_question(
    conn: sqlite3.Connection,
    quiz_id: int,
    position: int,
    question: QuestionIn | QuestionUpdate,
) -> None:
    text, options_json, correct = question_values(question)
    conn.execute(
        "INSERT INTO questions (quiz_id, position, text, options_json,"
        " correct_index) VALUES (?, ?, ?, ?, ?)",
        (quiz_id, position, text, options_json, correct),
    )


def create_quiz(conn: sqlite3.Connection, quiz: QuizIn) -> int:
    cursor = conn.execute(
        "INSERT INTO quizzes (title, time_limit_seconds, created_at) VALUES (?, ?, ?)",
        (quiz.title.strip(), quiz.time_limit_seconds, utcnow()),
    )
    quiz_id = cursor.lastrowid
    assert quiz_id is not None
    insert_questions(conn, quiz_id, quiz.questions)
    return quiz_id


def existing_question_ids(conn: sqlite3.Connection, quiz_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT id FROM questions WHERE quiz_id = ?", (quiz_id,)
    ).fetchall()
    return {int(row["id"]) for row in rows}


def update_errors(
    conn: sqlite3.Connection, quiz_id: int, quiz: QuizUpdate
) -> list[dict[str, str]]:
    errors = validation_errors(quiz)
    existing = existing_question_ids(conn, quiz_id)
    seen: set[int] = set()
    for index, question in enumerate(quiz.questions):
        if question.id is None:
            continue
        if question.id not in existing:
            errors.append(
                {
                    "field": f"questions[{index}].id",
                    "message": "Question does not belong to this quiz",
                }
            )
        elif question.id in seen:
            errors.append(
                {
                    "field": f"questions[{index}].id",
                    "message": "Question id is repeated",
                }
            )
        seen.add(question.id)
    return errors


def replace_quiz(
    conn: sqlite3.Connection, quiz_id: int, quiz: QuizUpdate
) -> None:
    conn.execute(
        "UPDATE quizzes SET title = ?, time_limit_seconds = ? WHERE id = ?",
        (quiz.title.strip(), quiz.time_limit_seconds, quiz_id),
    )
    desired_ids = {
        question.id for question in quiz.questions if question.id is not None
    }
    removed_ids = existing_question_ids(conn, quiz_id) - desired_ids
    if removed_ids:
        placeholders = ",".join("?" for _ in removed_ids)
        conn.execute(
            f"DELETE FROM questions WHERE quiz_id = ? AND id IN ({placeholders})",
            (quiz_id, *sorted(removed_ids)),
        )
    for position, question in enumerate(quiz.questions):
        if question.id is None:
            insert_question(conn, quiz_id, position, question)
        else:
            text, options_json, correct = question_values(question)
            conn.execute(
                "UPDATE questions SET position = ?, text = ?, options_json = ?,"
                " correct_index = ? WHERE id = ? AND quiz_id = ?",
                (
                    position,
                    text,
                    options_json,
                    correct,
                    question.id,
                    quiz_id,
                ),
            )


def question_rows(conn: sqlite3.Connection, quiz_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, text, options_json, correct_index FROM questions"
        " WHERE quiz_id = ? ORDER BY position",
        (quiz_id,),
    ).fetchall()
    questions = []
    for row in rows:
        options = json.loads(str(row["options_json"]))
        questions.append(
            {
                "id": int(row["id"]),
                "text": str(row["text"]),
                "options": [
                    {"text": text, "correct": index == int(row["correct_index"])}
                    for index, text in enumerate(options)
                ],
            }
        )
    return questions


def fetch_quiz(conn: sqlite3.Connection, quiz_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, title, time_limit_seconds, created_at FROM quizzes WHERE id = ?",
        (quiz_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "title": str(row["title"]),
        "time_limit_seconds": row["time_limit_seconds"],
        "created_at": str(row["created_at"]),
        "questions": question_rows(conn, quiz_id),
    }


def list_quizzes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, time_limit_seconds, created_at,"
        " (SELECT COUNT(*) FROM questions WHERE questions.quiz_id = quizzes.id)"
        " AS question_count FROM quizzes ORDER BY id"
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "title": str(row["title"]),
            "time_limit_seconds": row["time_limit_seconds"],
            "created_at": str(row["created_at"]),
            "question_count": int(row["question_count"]),
        }
        for row in rows
    ]


def remove_quiz(conn: sqlite3.Connection, quiz_id: int) -> bool:
    cursor = conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
    return cursor.rowcount > 0
