# LANQ

LANQ is a self-contained LAN quiz web app for classrooms with **no internet access**.
The teacher runs it on their laptop; students join from the same network by scanning a
QR code. Pages, scripts, and styles are all served locally — no CDNs, no external fonts.

## Requirements

- Python 3.11+

## Install

Run LANQ from source with:

```bash
pip install -r requirements.txt
```

## Start

One command:

```bash
uvicorn lanq.main:app --host 0.0.0.0 --port 8000
```

Then open:

- `http://<your-machine-ip>:8000/admin` — the teacher admin page (first run guides you
  through creating your username and password; it can only ever be set up once)
- `http://<your-machine-ip>:8000/` — the student page

The database (`lanq.db`) is created and initialized automatically on first boot.

## Windows installer

Tagged Windows releases include `LANQ-Setup-<version>.exe`. The machine-wide Inno
Setup installer places `LANQ.exe` in `%ProgramData%\LANQ\app`; LANQ creates its
SQLite database at `%ProgramData%\LANQ\data\lanq.db` on first launch. Installing or
updating requires administrator approval. Setup asks which Windows account should
access the data; Windows administrators and SYSTEM retain access as well.

When setup finds an earlier LANQ installation made with this installer, it asks
whether to update it. An older standalone `LANQ.exe` is not registered as an install,
so setup cannot locate it automatically. To bring its data forward, close that app and
select its `lanq.db` on the optional import page. The original database is copied, not
deleted. If ProgramData already contains a database, setup asks whether to keep that
database or back it up and replace it with the selected file. Updates create a
timestamped database backup before changing data. Uninstall keeps the database and
backups unless you explicitly choose to remove them.

To build the installer locally, install Python 3.11+, PyInstaller, and Inno Setup 6,
then run:

```bat
python -m pip install -r requirements.txt pyinstaller
build_installer.bat 1.0.0
```

The setup executable is written to `dist\installer`.

## Running a class

On the admin page, save a quiz in the library, open the **Live session** tab, pick the
quiz and press **Start session**. The tab then shows a QR code and the plain join URL
for students. Only one session can run at a time, and while it runs that quiz is locked
against editing or deletion. **Stop session** ends it: students still working see that
the session ended, the join page disappears, and the quiz becomes editable again.

## Teacher and student flow

### Teacher

1. Start the app with the single command above.
2. Open `http://<your-machine-ip>:8000/admin` and create the teacher account on first run.
3. In the **Quiz library** tab, create or edit a quiz. Use **Preview** to open a
   student-style page that shuffles the questions and options but does not create a
   participant or save any answers.
4. Switch to **Live session**, choose a quiz, and press **Start session**.
5. Students scan the QR code or open the join URL shown in the session panel.

### Student

1. Open `http://<your-machine-ip>:8000/` on the classroom network.
2. If the teacher has started a quiz, enter your student ID and name and join.
3. Answer the shuffled questions, submit once, and then the app shows only the success
   confirmation page without revealing scores or feedback.
4. If the teacher stops the session or the time limit expires, the page shows the
   session-ended state instead of the quiz.

## Join address and QR code

The join URL encoded in the QR code is built from your machine's LAN address:

- The IP is detected automatically and offline-safe — detection makes no external
  connections.
- `LANQ_LAN_IP` overrides the detection, for machines where it picks the wrong
  interface (a VPN or virtual adapter).
- `LANQ_PORT` sets the port shown in the join URL and QR code (default `8000`). Set it
  to the port you actually pass to uvicorn.

```bash
LANQ_LAN_IP=192.168.1.24 LANQ_PORT=8000 uvicorn lanq.main:app --host 0.0.0.0 --port 8000
```

## Firewall (read this before class)

Students must be able to reach your machine. On first run, allow Python (or uvicorn)
through the OS firewall for **incoming TCP connections on port 8000**:

- **Windows**: accept the firewall prompt for Python, or add an inbound rule for TCP 8000.
- **macOS**: System Settings → Network → Firewall → allow Python.
- **Linux**: `sudo ufw allow 8000/tcp` (if ufw is enabled).

An unallowed inbound port is the most likely reason students cannot join.

## Passwords

The teacher password is stored only as a PBKDF2-HMAC-SHA256 hash with a per-user random
salt. Login failures always return the same generic error, and logout or a password
change invalidates every existing login session.

## Development

```bash
pip install -r requirements-dev.txt
pytest            # run the test suite
python -m mypy lanq tests   # typecheck
```
