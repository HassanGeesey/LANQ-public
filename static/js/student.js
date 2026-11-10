const MESSAGES = {
  no_quiz: "No active quiz. Your teacher hasn't started yet.",
  ended: "This session has ended. Your teacher stopped the quiz.",
  submitted: "You have already submitted.",
  submittedSuccess: "Submitted successfully.",
  unavailable: "This quiz is no longer available. Reload the page.",
};

let justSubmitted = false;
let savedAnswers = {};
let countdownTimer = null;
const previewQuizId = (() => {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("preview");
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : null;
})();

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showMessage(text) {
  stopCountdown();
  document.getElementById("join-view").hidden = true;
  document.getElementById("quiz-view").hidden = true;
  const el = document.getElementById("state-message");
  el.hidden = false;
  if (text === MESSAGES.submittedSuccess) {
    el.className = "receipt";
    el.innerHTML =
      '<div class="receipt-stamp">Recorded</div>' +
      '<p class="receipt-text">Your answers have been submitted.</p>' +
      '<p class="receipt-note">You may close this page. Your teacher has the record.</p>';
  } else {
    el.className = "state-message";
    el.textContent = text;
  }
}

function showJoin(errorText) {
  stopCountdown();
  document.getElementById("state-message").hidden = true;
  document.getElementById("quiz-view").hidden = true;
  document.getElementById("join-view").hidden = false;
  showJoinError(errorText);
}

function showJoinError(errorText) {
  const element = document.getElementById("join-error");
  element.textContent = errorText || "";
  element.hidden = !errorText;
}

function showQuiz() {
  document.getElementById("state-message").hidden = true;
  document.getElementById("join-view").hidden = true;
  document.getElementById("quiz-view").hidden = false;
}

function stopCountdown() {
  if (countdownTimer !== null) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
  const timer = document.getElementById("quiz-timer");
  if (timer) timer.hidden = true;
}

function disableQuizControls() {
  document.querySelectorAll("#quiz-view input, #quiz-view button").forEach((input) => {
    input.disabled = true;
  });
}

function startCountdown(deadline, serverTime) {
  const timer = document.getElementById("quiz-timer");
  const value = document.getElementById("quiz-timer-value");
  timer.hidden = false;
  // Server-provided time reference corrects device clock skew.
  const skew = Date.parse(serverTime) - Date.now();
  const target = Date.parse(deadline) - skew;

  function render() {
    const remaining = target - Date.now();
    timer.classList.toggle("urgent", remaining > 0 && remaining <= 60000);
    if (remaining <= 0) {
      value.textContent = "0:00";
      stopCountdown();
      disableQuizControls();
      refresh();
      return;
    }
    const totalSeconds = Math.ceil(remaining / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    value.textContent = `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  stopCountdown();
  render();
  countdownTimer = setInterval(render, 500);
}

function detailMessage(body) {
  const detail = body && body.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") {
    const messages = (detail.errors || []).map((error) => error.message);
    return [detail.message, ...messages].join(" ");
  }
  return "Join failed. Please try again.";
}

async function renderQuizBody(quiz, { preview = false } = {}) {
  const saved = quiz.answers || {};
  savedAnswers = saved;
  document.getElementById("quiz-title").textContent = quiz.title;
  const list = document.getElementById("quiz-questions");
  list.innerHTML = "";
  quiz.questions.forEach((question, index) => {
    const item = document.createElement("li");
    item.className = "question";
    const options = question.options
      .map((option, optionIndex) => {
        const checked = saved[String(question.id)] === optionIndex ? " checked" : "";
        return `<li><label class="option"><input type="radio" ` +
          `name="question-${question.id}" data-question="${question.id}" ` +
          `data-position="${optionIndex}"${checked}><span>${escapeHtml(option)}</span></label></li>`;
      })
      .join("");
    item.innerHTML = `
      <h3 class="question-heading">Question ${index + 1}</h3>
      <p>${escapeHtml(question.text)}</p>
      <ol class="options student-options">${options}</ol>`;
    list.appendChild(item);
  });
  showQuiz();
  if (preview) {
    disableQuizControls();
    document.getElementById("submit-quiz").hidden = true;
    return;
  }
  document.getElementById("submit-quiz").hidden = false;
  if (quiz.deadline && quiz.server_time) {
    startCountdown(quiz.deadline, quiz.server_time);
  }
}

async function renderQuiz() {
  const response = await fetch("/api/student/quiz");
  if (response.status === 401) {
    await refresh();
    return;
  }
  if (!response.ok) {
    showMessage(MESSAGES.unavailable);
    return;
  }
  const quiz = await response.json();
  await renderQuizBody(quiz);
}

async function renderPreview() {
  const response = await fetch(`/api/admin/quizzes/${previewQuizId}/preview`);
  if (!response.ok) {
    showMessage(MESSAGES.unavailable);
    return;
  }
  const quiz = await response.json();
  await renderQuizBody(quiz, { preview: true });
}

async function saveAnswer(questionId, position) {
  let ok = false;
  try {
    const response = await fetch("/api/student/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question_id: questionId, position }),
    });
    if (response.status === 409 || response.status === 401) {
      await refresh();
      return;
    }
    ok = response.ok;
  } catch (err) {
    ok = false;
  }
  if (ok) {
    savedAnswers[String(questionId)] = position;
    return;
  }
  revertSelection(questionId, position);
}

function revertSelection(questionId, position) {
  const selected = document.querySelector(
    `input[name="question-${questionId}"][data-position="${position}"]`
  );
  if (!selected) return;
  const previous = savedAnswers[String(questionId)];
  const target = previous === undefined
    ? null
    : document.querySelector(
        `input[name="question-${questionId}"][data-position="${previous}"]`
      );
  if (target) {
    target.checked = true;
  } else {
    selected.checked = false;
  }
}

async function refresh() {
  if (previewQuizId !== null) {
    await renderPreview();
    return;
  }
  let state = null;
  try {
    const response = await fetch("/api/student/state");
    if (!response.ok) return;
    state = (await response.json()).state;
  } catch (err) {
    return;
  }
  if (state === "join") {
    showJoin("");
  } else if (state === "quiz") {
    await renderQuiz();
  } else {
    const text =
      state === "submitted" && justSubmitted
        ? MESSAGES.submittedSuccess
        : MESSAGES[state] || MESSAGES.no_quiz;
    justSubmitted = false;
    showMessage(text);
  }
}

document.getElementById("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  showJoinError("");
  const form = event.target;
  const payload = {
    student_id: form.elements.student_id.value,
    name: form.elements.name.value,
  };
  try {
    const response = await fetch("/api/student/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      if (response.status === 409) {
        await refresh();
        return;
      }
      showJoinError(detailMessage(await response.json().catch(() => null)));
      return;
    }
  } catch (err) {
    showJoinError("Could not reach the server. Try again.");
    return;
  }
  await refresh();
});

document
  .getElementById("quiz-questions")
  .addEventListener("change", async (event) => {
    const input = event.target;
    if (!input.matches('input[type="radio"]')) return;
    await saveAnswer(Number(input.dataset.question), Number(input.dataset.position));
  });

document.getElementById("submit-quiz").addEventListener("click", async () => {
  const button = document.getElementById("submit-quiz");
  button.disabled = true;
  try {
    const response = await fetch("/api/student/submit", { method: "POST" });
    if (response.status === 409 || response.status === 401) {
      await refresh();
      return;
    }
    if (!response.ok) return;
    justSubmitted = true;
  } finally {
    button.disabled = false;
  }
  await refresh();
});

refresh();
