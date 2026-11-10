import csv
import io
import re
import sqlite3

from lanq.dashboard import answers_by_participant, roster_entries
from lanq.sessions import snapshot_of


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "session"


def export_filename(session: sqlite3.Row) -> str:
    title = str(snapshot_of(session)["title"])
    return f"session-{int(session['id'])}-{_slugify(title)}.csv"


def csv_text(conn: sqlite3.Connection, session: sqlite3.Row) -> str:
    snapshot = snapshot_of(session)
    questions = snapshot["questions"]
    answers = answers_by_participant(conn, int(session["id"]))
    roster = roster_entries(conn, session, answers)
    chosen_by_question = {
        participant_id: dict(saved)
        for participant_id, saved in answers.items()
    }

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = ["ID", "Name", "Score", "Submitted"]
    header += [str(question["text"]) for question in questions]
    writer.writerow(header)

    for entry in roster:
        chosen = chosen_by_question.get(int(entry["id"]), {})
        row = [
            str(entry["student_id"]),
            str(entry["name"]),
            entry["score"] if entry["score"] is not None else "",
            str(entry["submitted_at"]) if entry["submitted_at"] is not None else "",
        ]
        for question in questions:
            canonical_index = chosen.get(int(question["id"]))
            options = [str(option) for option in question["options"]]
            if canonical_index is not None and 0 <= canonical_index < len(options):
                row.append(options[canonical_index])
            else:
                row.append("")
        writer.writerow(row)
    return buffer.getvalue()