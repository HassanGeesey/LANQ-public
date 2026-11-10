const views = ["setup", "login", "dashboard"];
const tabs = ["dashboard", "library", "session", "history", "account"];
const MIN_OPTIONS = 2;
const MAX_OPTIONS = 6;
const POLL_INTERVAL_MS = 3000;
const STATUS_LABELS = {
  joined: "Joined",
  in_progress: "In progress",
  submitted: "Submitted",
};
const RESULT_LABELS = {
  correct: "Correct",
  wrong: "Wrong",
  unanswered: "Unanswered",
};

function dashboardUrl() {
  return reviewSession === null
    ? "/api/admin/sessions/live"
    : `/api/admin/sessions/${reviewSession.id}/dashboard`;
}

function drilldownUrl(participantId) {
  return reviewSession === null
    ? `/api/admin/sessions/participants/${participantId}`
    : `/api/admin/sessions/${reviewSession.id}/participants/${participantId}`;
}

let quizzes = [];
let draft = null;
let editorErrors = {};
let liveTimer = null;
let reviewSession = null;

function show(name) {
  for (const view of views) {
    document.getElementById(view + "-view").hidden = view !== name;
  }
  document.getElementById("masthead-user").hidden = name !== "dashboard";
}

function showTab(name) {
  for (const tab of tabs) {
    document.getElementById(tab + "-tab").hidden = tab !== name;
  }
  for (const button of document.querySelectorAll("#tab-bar .tab")) {
    button.classList.toggle("tab-active", button.dataset.tab === name);
  }
}

function showError(message) {
  const el = document.getElementById("error-message");
  el.textContent = message;
  el.hidden = !message;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function requestJson(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = null;
    try {
      detail = (await response.json()).detail;
    } catch (err) {
      detail = null;
    }
    const error = new Error("Request failed");
    if (typeof detail === "string") {
      error.message = detail;
    } else if (detail && typeof detail.message === "string") {
      error.message = detail.message;
      error.errors = detail.errors || [];
    }
    throw error;
  }
  return response.json();
}

function postJson(url, body) {
  return requestJson("POST", url, body);
}

function formData(form) {
  const data = {};
  for (const field of form.elements) {
    if (field.name) data[field.name] = field.value;
  }
  return data;
}

function wireForm(formId, url, onSuccess) {
  document.getElementById(formId).addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    try {
      await postJson(url, formData(event.target));
      onSuccess();
    } catch (err) {
      showError(err.message);
    }
  });
}

function newQuestion() {
  return {
    id: null,
    text: "",
    options: [
      { text: "", correct: true },
      { text: "", correct: false },
    ],
  };
}

async function loadLibrary() {
  quizzes = await requestJson("GET", "/api/admin/quizzes");
  renderLibrary();
  renderSessionPicker();
}

function renderLibrary() {
  const list = document.getElementById("quiz-list");
  document.getElementById("quiz-list-empty").hidden = quizzes.length > 0;
  list.innerHTML = "";
  for (const quiz of quizzes) {
    const item = document.createElement("li");
    item.className = "quiz-item";
    const count = quiz.question_count;
    item.innerHTML = `
      <span class="quiz-title">${escapeHtml(quiz.title)}</span>
      <span class="quiz-count">${count} ${count === 1 ? "question" : "questions"}</span>
      <span class="quiz-actions">
        <button type="button" data-action="edit">Edit</button>
        <button type="button" data-action="delete">Delete</button>
      </span>`;
    item
      .querySelector('[data-action="edit"]')
      .addEventListener("click", () => openEditor(quiz.id));
    item
      .querySelector('[data-action="delete"]')
      .addEventListener("click", () => deleteQuiz(quiz));
    list.appendChild(item);
  }
}

async function deleteQuiz(quiz) {
  const confirmed = window.confirm(
    `Delete "${quiz.title}" and all of its questions? This cannot be undone.`
  );
  if (!confirmed) return;
  showError("");
  try {
    await requestJson("DELETE", `/api/admin/quizzes/${quiz.id}`, {});
    await loadLibrary();
  } catch (err) {
    showError(err.message);
  }
}

async function openEditor(quizId) {
  showError("");
  editorErrors = {};
  try {
    if (quizId === null || quizId === undefined) {
      draft = {
        id: null,
        title: "",
        time_limit_seconds: null,
        questions: [newQuestion()],
      };
    } else {
      draft = await requestJson("GET", `/api/admin/quizzes/${quizId}`);
    }
  } catch (err) {
    showError(err.message);
    return;
  }
  document.getElementById("quiz-editor-heading").textContent = draft.id
    ? "Edit quiz"
    : "New quiz";
  renderEditor();
}

function closeEditor() {
  draft = null;
  editorErrors = {};
  document.getElementById("quiz-editor").hidden = true;
  document.getElementById("library-view").hidden = false;
}

function optionHtml(questionIndex, option, optionIndex, optionCount) {
  const field = `questions[${questionIndex}].options[${optionIndex}].text`;
  return `
    <div class="option">
      <label class="option-correct">
        <input type="radio" name="correct-option-${questionIndex}"
               data-action="mark-correct"
               data-question-index="${questionIndex}"
               data-option-index="${optionIndex}"
               ${option.correct ? "checked" : ""}>
        <span>Correct</span>
      </label>
      <input data-field="${field}" value="${escapeHtml(option.text)}"
             placeholder="Option ${optionIndex + 1}" autocomplete="off">
      <button type="button" data-action="remove-option"
              data-question-index="${questionIndex}"
              data-option-index="${optionIndex}"
              ${optionCount <= MIN_OPTIONS ? "disabled" : ""}>Remove</button>
      <p class="field-error" data-error-for="${field}" hidden></p>
    </div>`;
}

function questionHtml(question, questionIndex) {
  const optionCount = question.options.length;
  const options = question.options
    .map((option, optionIndex) =>
      optionHtml(questionIndex, option, optionIndex, optionCount)
    )
    .join("");
  return `
    <li class="question">
      <div class="row-between">
        <h3 class="question-heading">Question ${questionIndex + 1}</h3>
        <span class="question-actions">
          <button type="button" data-action="move-up"
                  data-question-index="${questionIndex}"
                  ${questionIndex === 0 ? "disabled" : ""}>Up</button>
          <button type="button" data-action="move-down"
                  data-question-index="${questionIndex}"
                  ${questionIndex === draft.questions.length - 1 ? "disabled" : ""}>Down</button>
          <button type="button" data-action="remove-question"
                  data-question-index="${questionIndex}">Remove</button>
        </span>
      </div>
      <label>Question
        <input data-field="questions[${questionIndex}].text"
               value="${escapeHtml(question.text)}" autocomplete="off">
      </label>
      <p class="field-error" data-error-for="questions[${questionIndex}].text" hidden></p>
      <fieldset class="options">
        <legend>Answer options — mark the one correct answer</legend>
        ${options}
        <button type="button" data-action="add-option"
                data-question-index="${questionIndex}"
                ${optionCount >= MAX_OPTIONS ? "disabled" : ""}>Add option</button>
      </fieldset>
      <p class="field-error" data-error-for="questions[${questionIndex}].options" hidden></p>
    </li>`;
}

function renderEditorErrors() {
  for (const element of document.querySelectorAll("[data-error-for]")) {
    const message = editorErrors[element.dataset.errorFor] || "";
    element.textContent = message;
    element.hidden = !message;
  }
  const summary = document.getElementById("editor-error-summary");
  const messages = Object.values(editorErrors);
  summary.hidden = messages.length === 0;
  summary.textContent = messages.length
    ? `${messages.length} ${messages.length === 1 ? "problem" : "problems"} to fix: ` +
      messages.join(" ")
    : "";
}

function renderEditor() {
  document.getElementById("library-view").hidden = true;
  document.getElementById("quiz-editor").hidden = false;
  document.getElementById("quiz-title").value = draft.title;
  document.getElementById("quiz-time-limit").value =
    draft.time_limit_seconds === null || draft.time_limit_seconds === undefined
      ? ""
      : String(Math.round(draft.time_limit_seconds / 60));
  document.getElementById("question-list").innerHTML = draft.questions
    .map(questionHtml)
    .join("");
  renderEditorErrors();
}

function setDraftValue(field, value) {
  if (field === "title") {
    draft.title = value;
    return;
  }
  if (field === "time_limit_seconds") {
    const minutes = parseInt(value, 10);
    draft.time_limit_seconds =
      Number.isFinite(minutes) && minutes > 0 ? minutes * 60 : null;
    return;
  }
  let match = field.match(/^questions\[(\d+)\]\.text$/);
  if (match) {
    draft.questions[Number(match[1])].text = value;
    return;
  }
  match = field.match(/^questions\[(\d+)\]\.options\[(\d+)\]\.text$/);
  if (match) {
    draft.questions[Number(match[1])].options[Number(match[2])].text = value;
  }
}

function quizPayload() {
  return {
    title: draft.title,
    time_limit_seconds: draft.time_limit_seconds,
    questions: draft.questions.map((question) => ({
      ...(question.id === null ? {} : { id: question.id }),
      text: question.text,
      options: question.options.map((option) => ({
        text: option.text,
        correct: option.correct,
      })),
    })),
  };
}

async function saveQuiz() {
  showError("");
  try {
    if (draft.id === null || draft.id === undefined) {
      await postJson("/api/admin/quizzes", quizPayload());
    } else {
      await requestJson("PUT", `/api/admin/quizzes/${draft.id}`, quizPayload());
    }
    closeEditor();
    await loadLibrary();
  } catch (err) {
    editorErrors = {};
    if (err.errors && err.errors.length) {
      for (const error of err.errors) {
        editorErrors[error.field] = error.message;
      }
    } else {
      showError(err.message);
    }
    renderEditor();
  }
}

async function previewDraft() {
  if (!draft || draft.id === null || draft.id === undefined) {
    showError("Save the quiz once before previewing it.");
    return;
  }
  showError("");
  const previewUrl = `/?preview=${draft.id}`;
  window.open(previewUrl, "_blank", "noopener,noreferrer");
}

function handleEditorClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || !draft) return;
  const action = button.dataset.action;
  const questionIndex = Number(button.dataset.questionIndex);
  const optionIndex = Number(button.dataset.optionIndex);
  const question = draft.questions[questionIndex];
  if (action === "move-up" && questionIndex > 0) {
    draft.questions[questionIndex] = draft.questions[questionIndex - 1];
    draft.questions[questionIndex - 1] = question;
  } else if (action === "move-down" && questionIndex < draft.questions.length - 1) {
    draft.questions[questionIndex] = draft.questions[questionIndex + 1];
    draft.questions[questionIndex + 1] = question;
  } else if (action === "remove-question") {
    draft.questions.splice(questionIndex, 1);
  } else if (action === "add-option") {
    question.options.push({
      text: "",
      correct: !question.options.some((option) => option.correct),
    });
  } else if (action === "remove-option") {
    const [removed] = question.options.splice(optionIndex, 1);
    if (removed.correct && question.options.length > 0) {
      question.options[0].correct = true;
    }
  } else {
    return;
  }
  renderEditor();
}

function renderSessionPicker() {
  const select = document.getElementById("session-quiz-select");
  select.innerHTML = "";
  for (const quiz of quizzes) {
    const option = document.createElement("option");
    option.value = String(quiz.id);
    option.textContent = quiz.title;
    select.appendChild(option);
  }
  const empty = quizzes.length === 0;
  document.getElementById("session-no-quizzes").hidden = !empty;
  document.getElementById("start-session-button").disabled = empty;
}

function renderSession(data) {
  const active = data.session !== null;
  document.getElementById("session-idle").hidden = active;
  document.getElementById("session-live").hidden = !active;
  document.getElementById("session-live-controls").hidden = !active;
  if (active) {
    document.getElementById("session-live-title").textContent =
      data.session.title;
    document.getElementById("session-join-url").textContent = data.join_url;
    document.getElementById("session-qr").innerHTML = data.qr_svg;
    document.getElementById("session-qr-large").innerHTML = data.qr_svg;
    document.getElementById("session-qr-dialog-url").textContent = data.join_url;
  }
  renderSessionPicker();
}

async function loadSession() {
  try {
    const data = await requestJson("GET", "/api/admin/sessions/current");
    renderSession(data);
  } catch (err) {
    showError(err.message);
  }
}

const lastAccuracyScale = {};

function renderAccuracyChart(stats) {
  const chart = document.getElementById("accuracy-chart");
  chart.innerHTML = "";
  document.getElementById("accuracy-empty").hidden = stats.length > 0;
  chart.hidden = stats.length === 0;
  stats.forEach((entry, index) => {
    const answered = entry.answered_count;
    const percent =
      answered === 0 ? null : Math.round((entry.correct_count / answered) * 100);
    const summary =
      percent === null
        ? `No answers yet (0/${entry.participant_count})`
        : `${percent}% correct (${entry.correct_count}/${answered})`;
    const item = document.createElement("li");
    item.className =
      percent === null ? "accuracy-item accuracy-unanswered" : "accuracy-item";
    item.title = entry.text;
    item.innerHTML = `
      <span class="accuracy-label">Q${index + 1}</span>
      <span class="accuracy-bar" aria-hidden="true">
        <span class="accuracy-fill"></span>
      </span>
      <span class="accuracy-value">${escapeHtml(summary)}</span>`;
    const fill = item.querySelector(".accuracy-fill");
    const target = (percent || 0) / 100;
    const previous = lastAccuracyScale[index];
    if (previous !== undefined && previous === target) {
      fill.style.transform = `scaleX(${target})`;
    } else {
      requestAnimationFrame(() => {
        fill.style.transform = `scaleX(${target})`;
      });
    }
    lastAccuracyScale[index] = target;
    chart.appendChild(item);
  });
}

function wireParticipantRow(row, participantId) {
  row.className = "participant-row";
  row.tabIndex = 0;
  const open = () => openDrilldown(participantId);
  row.addEventListener("click", open);
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
}

function drilldownOptionHtml(question, option, optionIndex) {
  const classes = ["drilldown-option"];
  const markers = [];
  if (optionIndex === question.correct_index) {
    classes.push("drilldown-option-correct");
    markers.push("Correct answer");
  }
  if (optionIndex === question.chosen_index) {
    if (question.result === "wrong") classes.push("drilldown-option-wrong");
    markers.push("Student's answer");
  }
  return `
    <li class="${classes.join(" ")}">
      <span>${escapeHtml(option)}</span>
      <span class="drilldown-marker">${escapeHtml(markers.join(" · "))}</span>
    </li>`;
}

function renderDrilldown(data) {
  const participant = data.participant;
  const status = STATUS_LABELS[participant.status] || participant.status;
  const score = participant.score === null ? "" : ` · Score ${participant.score}`;
  document.getElementById("drilldown-title").textContent = participant.name;
  document.getElementById("drilldown-meta").textContent =
    `${participant.student_id} · ${status}${score}`;

  const list = document.getElementById("drilldown-questions");
  list.innerHTML = "";
  data.questions.forEach((question, index) => {
    const item = document.createElement("li");
    item.className = `drilldown-question drilldown-${question.result}`;
    const options = question.options
      .map((option, optionIndex) => drilldownOptionHtml(question, option, optionIndex))
      .join("");
    item.innerHTML = `
      <div class="row-between">
        <h4 class="drilldown-question-heading">Question ${index + 1}</h4>
        <span class="result-badge result-badge-${question.result}">${escapeHtml(
          RESULT_LABELS[question.result] || question.result
        )}</span>
      </div>
      <p class="drilldown-question-text">${escapeHtml(question.text)}</p>
      <ul class="drilldown-options">${options}</ul>`;
    list.appendChild(item);
  });
  document.getElementById("drilldown").hidden = false;
}

async function openDrilldown(participantId) {
  showError("");
  try {
    const data = await requestJson("GET", drilldownUrl(participantId));
    renderDrilldown(data);
  } catch (err) {
    showError(err.message);
  }
}

function closeDrilldown() {
  document.getElementById("drilldown").hidden = true;
}

function renderLiveResults(data) {
  const active = data.session !== null;
  document.getElementById("live-results").hidden = !active;
  document.getElementById("dashboard-empty").hidden = active;
  document.getElementById("dashboard-live-status").hidden =
    !active || reviewSession !== null;
  if (!active) {
    document.getElementById("dashboard-title").textContent = "Classroom dashboard";
    document.getElementById("dashboard-meta").hidden = true;
    closeDrilldown();
    return;
  }

  document.getElementById("dashboard-title").textContent = data.session.title;
  const meta = document.getElementById("dashboard-meta");
  meta.hidden = reviewSession === null;
  if (reviewSession !== null) {
    meta.textContent =
      `Started ${reviewSession.started_at} · Ended ${reviewSession.ended_at || "—"} · ` +
      `${reviewSession.participant_count} ${reviewSession.participant_count === 1 ? "student" : "students"}`;
  }

  const questionCount = data.accuracy.length;
  const participantCount = data.roster.length;
  const submittedCount = data.leaderboard.length;
  const inProgressCount = data.roster.filter(
    (entry) => entry.status === "in_progress"
  ).length;
  const correctCount = data.accuracy.reduce(
    (total, entry) => total + entry.correct_count,
    0
  );
  const answeredCount = data.accuracy.reduce(
    (total, entry) => total + entry.answered_count,
    0
  );
  const responseSlots = participantCount * questionCount;
  const incorrectCount = Math.max(0, answeredCount - correctCount);
  const unansweredCount = Math.max(0, responseSlots - answeredCount);
  const responseTotal = correctCount + incorrectCount + unansweredCount;
  const averageScore = submittedCount
    ? data.leaderboard.reduce((total, entry) => total + entry.score, 0) /
      submittedCount
    : null;

  document.getElementById("metric-participants").textContent = String(participantCount);
  document.getElementById("metric-submitted").textContent = String(submittedCount);
  document.getElementById("metric-in-progress").textContent = String(inProgressCount);
  document.getElementById("metric-average-score").textContent =
    averageScore === null
      ? "—"
      : `${averageScore.toFixed(1)} / ${questionCount}`;
  document.getElementById("outcomes-correct").textContent = String(correctCount);
  document.getElementById("outcomes-incorrect").textContent = String(incorrectCount);
  document.getElementById("outcomes-unanswered").textContent = String(unansweredCount);
  document.getElementById("outcomes-chart-total").textContent = String(responseTotal);
  document.getElementById("outcomes-total").textContent =
    `${responseTotal} ${responseTotal === 1 ? "response" : "responses"}`;
  const correctEnd = responseTotal ? (correctCount / responseTotal) * 100 : 0;
  const incorrectEnd = responseTotal
    ? correctEnd + (incorrectCount / responseTotal) * 100
    : 0;
  const outcomesChart = document.getElementById("outcomes-chart");
  outcomesChart.style.background = responseTotal
    ? `conic-gradient(#2a6b53 0 ${correctEnd}%, #b05d4d ${correctEnd}% ${incorrectEnd}%, #d6e0dd ${incorrectEnd}% 100%)`
    : "conic-gradient(#d6e0dd 0 100%)";
  outcomesChart.setAttribute(
    "aria-label",
    `Answer outcomes: ${correctCount} correct, ${incorrectCount} incorrect, ${unansweredCount} unanswered`
  );

  renderAccuracyChart(data.accuracy);

  const rosterBody = document.getElementById("roster-body");
  rosterBody.innerHTML = "";
  document.getElementById("roster-empty").hidden = data.roster.length > 0;
  document.getElementById("roster-table").hidden = data.roster.length === 0;
  for (const entry of data.roster) {
    const row = document.createElement("tr");
    const label = STATUS_LABELS[entry.status] || entry.status;
    const score = entry.score === null ? "—" : String(entry.score);
    row.innerHTML = `
      <td>${escapeHtml(entry.student_id)}</td>
      <td>${escapeHtml(entry.name)}</td>
      <td>${escapeHtml(entry.joined_at)}</td>
      <td>${escapeHtml(label)}</td>
      <td>${escapeHtml(score)}</td>`;
    wireParticipantRow(row, entry.id);
    rosterBody.appendChild(row);
  }

  const boardBody = document.getElementById("leaderboard-body");
  boardBody.innerHTML = "";
  document.getElementById("leaderboard-empty").hidden =
    data.leaderboard.length > 0;
  document.getElementById("leaderboard-table").hidden =
    data.leaderboard.length === 0;
  for (const entry of data.leaderboard) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(entry.rank)}</td>
      <td>${escapeHtml(entry.student_id)}</td>
      <td>${escapeHtml(entry.name)}</td>
      <td>${escapeHtml(entry.score)}</td>
      <td>${escapeHtml(entry.submitted_at)}</td>`;
    wireParticipantRow(row, entry.id);
    boardBody.appendChild(row);
  }
}

async function loadLiveResults() {
  try {
    const data = await requestJson("GET", dashboardUrl());
    renderLiveResults(data);
  } catch (err) {
    // Polling keeps the last good snapshot on a transient failure.
  }
}

function startLivePolling() {
  if (liveTimer !== null) return;
  loadLiveResults();
  liveTimer = setInterval(loadLiveResults, POLL_INTERVAL_MS);
}

function stopLivePolling() {
  if (liveTimer === null) return;
  clearInterval(liveTimer);
  liveTimer = null;
}

async function loadHistory() {
  try {
    const data = await requestJson("GET", "/api/admin/sessions/history");
    renderHistory(data);
  } catch (err) {
    showError(err.message);
  }
}

function renderHistory(sessions) {
  const list = document.getElementById("history-body");
  document.getElementById("history-empty").hidden = sessions.length > 0;
  document.getElementById("history-table").hidden = sessions.length === 0;
  list.innerHTML = "";
  for (const session of sessions) {
    const row = document.createElement("tr");
    const status = session.status === "active" ? "Active" : "Ended";
    const download = document.createElement("a");
    download.href = `/api/admin/sessions/${session.id}/export.csv`;
    download.download = "";
    download.textContent = "Download";
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.textContent = "Open";
    openButton.addEventListener("click", () => openHistorySession(session));
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", () => deleteHistorySession(session));
    row.innerHTML = `
      <td>${escapeHtml(session.title)}</td>
      <td>${escapeHtml(session.started_at)}</td>
      <td>${escapeHtml(session.ended_at || "—")}</td>
      <td>${escapeHtml(session.participant_count)}</td>
      <td>${escapeHtml(status)}</td>`;
    const actions = document.createElement("td");
    actions.className = "history-actions";
    actions.append(openButton, download, deleteButton);
    row.appendChild(actions);
    list.appendChild(row);
  }
}

async function openHistorySession(session) {
  showError("");
  reviewSession = session;
  stopLivePolling();
  try {
    const data = await requestJson("GET", dashboardUrl());
    renderLiveResults(data);
    showTab("dashboard");
  } catch (err) {
    reviewSession = null;
    showError(err.message);
  }
}

function closeReview() {
  reviewSession = null;
  document.getElementById("dashboard-meta").hidden = true;
  loadSession();
  startLivePolling();
}

async function deleteHistorySession(session) {
  const confirmed = window.confirm(
    `Delete the "${session.title}" session from ${session.started_at} and all ` +
      "of its results? This cannot be undone."
  );
  if (!confirmed) return;
  showError("");
  try {
    await requestJson("DELETE", `/api/admin/sessions/${session.id}`, {});
    if (reviewSession !== null && reviewSession.id === session.id) {
      closeReview();
    }
    await loadHistory();
  } catch (err) {
    showError(err.message);
  }
}

async function startSession() {
  showError("");
  const quizId = Number(document.getElementById("session-quiz-select").value);
  try {
    await postJson("/api/admin/sessions", { quiz_id: quizId });
    await loadSession();
    document.getElementById("session-qr-dialog").showModal();
    await loadLiveResults();
  } catch (err) {
    showError(err.message);
  }
}

async function stopSession() {
  const confirmed = window.confirm(
    "Stop this session? Students who have not submitted will see that the session ended."
  );
  if (!confirmed) return;
  showError("");
  try {
    await postJson("/api/admin/sessions/stop", {});
    await loadSession();
    await loadLiveResults();
  } catch (err) {
    showError(err.message);
  }
}

async function showDashboardIfLoggedIn() {
  const response = await fetch("/api/admin/me");
  if (!response.ok) return false;
  const data = await response.json();
  document.getElementById("whoami").textContent = data.username;
  show("dashboard");
  await loadLibrary();
  await loadSession();
  startLivePolling();
  await loadLiveResults();
  await loadHistory();
  showTab("dashboard");
  return true;
}

async function boot() {
  showError("");
  const state = await (await fetch("/api/admin/setup-state")).json();
  if (!state.setup_complete) {
    show("setup");
    return;
  }
  if (!(await showDashboardIfLoggedIn())) show("login");
}

wireForm("setup-form", "/api/admin/setup", boot);

wireForm("login-form", "/api/admin/login", showDashboardIfLoggedIn);

wireForm("change-password-form", "/api/admin/change-password", () => {
  stopLivePolling();
  show("login");
  showError("Password changed. Please log in again.");
});

document.getElementById("logout-button").addEventListener("click", async () => {
  showError("");
  await postJson("/api/admin/logout", {});
  stopLivePolling();
  show("login");
});

for (const button of document.querySelectorAll("#tab-bar .tab")) {
  button.addEventListener("click", () => {
    showTab(button.dataset.tab);
    if (button.dataset.tab === "dashboard") {
      if (reviewSession !== null) openHistorySession(reviewSession);
      else loadLiveResults();
    } else if (button.dataset.tab === "session") {
      if (reviewSession !== null) closeReview();
      else loadSession();
    } else if (button.dataset.tab === "history") {
      loadHistory();
    }
  });
}

document
  .getElementById("start-session-button")
  .addEventListener("click", startSession);

document
  .getElementById("stop-session-button")
  .addEventListener("click", stopSession);

document.getElementById("session-qr-open").addEventListener("click", () => {
  document.getElementById("session-qr-dialog").showModal();
});

document.getElementById("session-qr-close").addEventListener("click", () => {
  document.getElementById("session-qr-dialog").close();
});

document
  .getElementById("drilldown-close-button")
  .addEventListener("click", closeDrilldown);

document.getElementById("dashboard-open-session").addEventListener("click", () => {
  showTab("session");
  loadSession();
});

document.getElementById("new-quiz-button").addEventListener("click", () => {
  openEditor(null);
});

document.getElementById("add-question-button").addEventListener("click", () => {
  draft.questions.push(newQuestion());
  renderEditor();
});

document.getElementById("cancel-quiz-button").addEventListener("click", () => {
  closeEditor();
});

document
  .getElementById("preview-quiz-button")
  .addEventListener("click", previewDraft);

document
  .getElementById("quiz-editor-form")
  .addEventListener("submit", (event) => {
    event.preventDefault();
    saveQuiz();
  });

document.getElementById("quiz-editor").addEventListener("input", (event) => {
  const field = event.target.dataset.field;
  if (!field || !draft) return;
  setDraftValue(field, event.target.value);
});

document.getElementById("quiz-editor").addEventListener("change", (event) => {
  if (event.target.dataset.action !== "mark-correct" || !draft) return;
  const questionIndex = Number(event.target.dataset.questionIndex);
  const optionIndex = Number(event.target.dataset.optionIndex);
  draft.questions[questionIndex].options.forEach((option, index) => {
    option.correct = index === optionIndex;
  });
});

document
  .getElementById("quiz-editor")
  .addEventListener("click", handleEditorClick);

boot();
