import csv
import io
from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

from tests.helpers import (
    answer,
    answer_every,
    correct_position,
    correct_texts,
    create_quiz,
    joined_student,
    make_question,
    start_session,
    submit,
    wrong_position,
)

TRICKY = [
    make_question('Q1, "the first"?', ["1a, comma", "1b; semi", "1c"], [0]),
    make_question('Q2 "quoted"', ["2a", '2b, "x"', "2c"], [1]),
    make_question("Q3", ["3a", "3b", '3c, tea'], [2]),
]


def csv_export(client: TestClient, session_id: int) -> httpx.Response:
    return client.get(f"/api/admin/sessions/{session_id}/export.csv")


def parse_csv(
    response: httpx.Response, session_id: int
) -> tuple[list[list[str]], str]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert f'session-{session_id}-' in disposition
    assert ".csv" in disposition
    return list(csv.reader(io.StringIO(response.text))), disposition


def test_csv_export_requires_authentication(client: TestClient) -> None:
    assert csv_export(client, 1).status_code == 401
    client.cookies.set("lanq_session", "not-a-real-token")
    assert csv_export(client, 1).status_code == 401


def test_csv_export_is_404_for_an_unknown_session(
    admin_client: TestClient,
) -> None:
    assert csv_export(admin_client, 999999).status_code == 404


def test_csv_header_and_rows_for_a_mixed_result_session(
    admin_client: TestClient,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    session = start_session(admin_client, capitals_quiz["id"])
    canonical = capitals_quiz["questions"]

    perfect = joined_student(student, student_id="s-perfect", name="Perfect")
    answer_every(perfect, lambda q: correct_position(q, texts))
    assert submit(perfect).status_code == 200

    mixed = joined_student(student, student_id="s-mixed", name="Mixed")
    questions = {
        question["id"]: question
        for question in mixed.get("/api/student/quiz").json()["questions"]
    }
    for index, question in enumerate(canonical):
        if index == 0:
            position = correct_position(questions[question["id"]], texts)
        elif index == 1:
            position = wrong_position(questions[question["id"]], texts)
        else:
            continue
        assert answer(mixed, question["id"], position).status_code == 200
    assert submit(mixed).status_code == 200

    joined_student(student, student_id="s-none", name="None")
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    rows, _ = parse_csv(csv_export(admin_client, session["id"]), session["id"])

    expected_header = ["ID", "Name", "Score", "Submitted"] + [
        question["text"] for question in canonical
    ]
    assert rows[0] == expected_header
    assert len(rows) == 4
    assert [row[0] for row in rows[1:]] == ["s-perfect", "s-mixed", "s-none"]

    perfect_row, mixed_row, none_row = rows[1:]
    assert perfect_row[1] == "Perfect"
    assert perfect_row[2] == "5"
    assert perfect_row[3]
    assert perfect_row[4:] == [
        texts[canonical[0]["text"]],
        texts[canonical[1]["text"]],
        texts[canonical[2]["text"]],
        texts[canonical[3]["text"]],
        texts[canonical[4]["text"]],
    ]

    assert mixed_row[2] == "1"
    assert mixed_row[4] == texts[canonical[0]["text"]]
    assert mixed_row[5]
    assert mixed_row[5] != texts[canonical[1]["text"]]
    assert mixed_row[6] == ""
    assert mixed_row[7] == ""
    assert mixed_row[8] == ""

    assert none_row[1] == "None"
    assert none_row[2] == "0"
    assert none_row[4:] == [""] * 5


def test_csv_answer_columns_follow_canonical_question_order(
    admin_client: TestClient,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    session = start_session(admin_client, capitals_quiz["id"])
    worker = joined_student(student, student_id="s-shuffled", name="Shuffler")
    answer_every(worker, lambda q: correct_position(q, texts))
    assert submit(worker).status_code == 200
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    rows, _ = parse_csv(csv_export(admin_client, session["id"]), session["id"])
    canonical_order = [question["text"] for question in capitals_quiz["questions"]]

    assert rows[0][4:] == canonical_order
    assert rows[1][4:] == [texts[text] for text in canonical_order]


def test_csv_escapes_commas_quotes_and_slugs_the_filename(
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    quiz = create_quiz(admin_client, title="Capitals, Set One: 'final'")
    session = start_session(admin_client, quiz["id"])
    worker = joined_student(
        student, student_id='A,1', name='Ada, "Lady" Lovelace'
    )
    texts = correct_texts(quiz)
    answer_every(worker, lambda q: correct_position(q, texts))
    assert submit(worker).status_code == 200
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = csv_export(admin_client, session["id"])
    rows, disposition = parse_csv(response, session["id"])

    assert "capitals-set-one-final" in disposition.lower()
    assert rows[0][4:] == [question["text"] for question in quiz["questions"]]
    name_row = rows[1]
    assert name_row[0] == "A,1"
    assert name_row[1] == 'Ada, "Lady" Lovelace'
    assert response.text.count('"Ada, ""Lady"" Lovelace"') == 1


def test_csv_exports_an_active_session_with_partial_results(
    admin_client: TestClient,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    session = start_session(admin_client, capitals_quiz["id"])

    done = joined_student(student, student_id="s-done", name="Done")
    answer_every(done, lambda q: correct_position(q, texts))
    assert submit(done).status_code == 200

    working = joined_student(student, student_id="s-working", name="Working")
    questions = {
        question["id"]: question
        for question in working.get("/api/student/quiz").json()["questions"]
    }
    for question in capitals_quiz["questions"][:2]:
        assert answer(
            working, question["id"], correct_position(questions[question["id"]], texts)
        ).status_code == 200

    joined_student(student, student_id="s-new", name="New")

    rows, _ = parse_csv(csv_export(admin_client, session["id"]), session["id"])
    by_id = {row[0]: row for row in rows[1:]}

    assert by_id["s-done"][2] == "5"
    assert by_id["s-done"][3]
    assert by_id["s-done"][4:] == [
        texts[question["text"]] for question in capitals_quiz["questions"]
    ]
    working_row = by_id["s-working"]
    assert working_row[2] == "2"
    assert working_row[3] == ""
    assert working_row[4] == texts[capitals_quiz["questions"][0]["text"]]
    assert working_row[5] == texts[capitals_quiz["questions"][1]["text"]]
    assert working_row[6:] == [""] * 3
    new_row = by_id["s-new"]
    assert new_row[2] == ""
    assert new_row[3] == ""
    assert new_row[4:] == [""] * 5


def test_csv_round_trips_the_whole_session_via_the_test_seam(
    admin_client: TestClient,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    session = start_session(admin_client, capitals_quiz["id"])
    worker = joined_student(student, student_id="s-ada", name="Ada")
    answer_every(worker, lambda q: correct_position(q, texts))
    assert submit(worker).status_code == 200
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    rows, _ = parse_csv(csv_export(admin_client, session["id"]), session["id"])

    assert len(rows) == 2
    assert rows[1][0] == "s-ada"
    assert rows[1][1] == "Ada"
    assert rows[1][2] == "5"
    assert all(rows[1][4:])