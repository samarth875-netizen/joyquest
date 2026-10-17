const store = {
  getPoints: () => Number(localStorage.getItem("jq_points") || 0),
  setPoints: (n) => localStorage.setItem("jq_points", String(n)),
  getStreak: () => Number(localStorage.getItem("jq_streak") || 0),
  setStreak: (n) => localStorage.setItem("jq_streak", String(n)),
  getLastDay: () => localStorage.getItem("jq_last_day") || "",
  setLastDay: (d) => localStorage.setItem("jq_last_day", d),
  getJar: () => {
    try {
      return JSON.parse(localStorage.getItem("jq_jar") || "[]");
    } catch (e) {
      return [];
    }
  },
  setJar: (arr) => localStorage.setItem("jq_jar", JSON.stringify(arr)),
};

const todayKey = () => new Date().toISOString().slice(0, 10);
const yesterdayKey = () => {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
};

const $ = (id) => document.getElementById(id);

function renderStats() {
  $("points").textContent = store.getPoints();
  $("streak").textContent = store.getStreak();
}

function showStatus(text) {
  const box = $("status");
  box.hidden = false;
  $("statusText").textContent = text;
}
function hideStatus() {
  $("status").hidden = true;
}

let selectedMood = null;
let selectedMinutes = null;
let selectedBudget = null;

function selectOne(container, button) {
  container.querySelectorAll(".chip, .mood").forEach((b) => b.classList.remove("selected"));
  button.classList.add("selected");
}

$("moods").addEventListener("click", (e) => {
  const btn = e.target.closest(".mood");
  if (!btn) return;
  selectedMood = btn.dataset.mood;
  selectOne($("moods"), btn);
});
$("timeChips").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  selectedMinutes = Number(btn.dataset.minutes);
  selectOne($("timeChips"), btn);
});
$("budgetChips").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  selectedBudget = btn.dataset.budget;
  selectOne($("budgetChips"), btn);
});

async function getQuests(mood, minutes, budget, interests, memories) {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task: "quests", mood, minutes, budget, interests, memories }),
  });
  const data = await r.json();
  if (data.error) throw new Error(data.error);
  return data;
}

async function getRoughDay(mood, minutes, budget, interests, memories) {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task: "rough_day", mood, minutes, budget, interests, memories }),
  });
  const data = await r.json();
  if (data.error) throw new Error(data.error);
  return data;
}

function renderQuests(data) {
  const results = $("results");
  results.hidden = false;
  $("intro").textContent = data.intro || "";
  $("closing").textContent = data.closing || "";

  const wrap = $("questCards");
  wrap.innerHTML = "";

  data.quests.forEach((q, i) => {
    const card = document.createElement("div");
    card.className = "quest";

    const body = document.createElement("div");
    body.className = "q-body";
    body.innerHTML =
      '<p class="q-title"></p><p class="q-desc"></p>' +
      '<div class="q-tags"><span class="tag"></span><span class="tag cost"></span></div>';
    body.querySelector(".q-title").textContent = q.title;
    body.querySelector(".q-desc").textContent = q.description;
    body.querySelectorAll(".tag")[0].textContent = q.minutes + " min";
    body.querySelectorAll(".tag")[1].textContent = q.cost;

    const action = document.createElement("div");
    action.className = "q-action";
    const doneBtn = document.createElement("button");
    doneBtn.className = "small-btn";
    doneBtn.textContent = "done";
    doneBtn.addEventListener("click", () => completeQuest(card, doneBtn));
    action.appendChild(doneBtn);

    card.appendChild(body);
    card.appendChild(action);
    wrap.appendChild(card);
  });
}

function completeQuest(card, btn) {
  if (card.classList.contains("completed")) return;
  card.classList.add("completed");
  btn.textContent = "done ✓";
  btn.classList.add("done");
  btn.disabled = true;

  store.setPoints(store.getPoints() + 10);
  renderStats();

  const today = todayKey();
  const last = store.getLastDay();
  if (last !== today) {
    if (last === yesterdayKey()) {
      store.setStreak(store.getStreak() + 1);
    } else {
      store.setStreak(1);
    }
    store.setLastDay(today);
    renderStats();
  }

  const rect = btn.getBoundingClientRect();
  launchConfetti(rect.left + rect.width / 2, rect.top);
}

const CONFETTI_COLORS = ["#c96", "#22303c", "#d9cbb5", "#5b5b5b"];
function launchConfetti(x, y) {
  const layer = document.getElementById("confetti");
  for (let i = 0; i < 26; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = x + (Math.random() * 100 - 50) + "px";
    piece.style.top = y + "px";
    piece.style.background = CONFETTI_COLORS[i % CONFETTI_COLORS.length];
    piece.style.animationDelay = Math.random() * 0.15 + "s";
    piece.style.transform = "rotate(" + Math.random() * 360 + "deg)";
    layer.appendChild(piece);
    setTimeout(() => piece.remove(), 1600);
  }
}

function renderJar() {
  const jar = store.getJar();
  const list = $("jarList");
  list.innerHTML = "";
  if (!jar.length) {
    const li = document.createElement("li");
    li.className = "jar-empty";
    li.textContent = "your jar is empty — add a happy moment above.";
    list.appendChild(li);
    return;
  }
  jar.slice().reverse().forEach((entry) => {
    const li = document.createElement("li");
    const text = document.createElement("span");
    text.textContent = entry.text;
    const date = document.createElement("span");
    date.className = "date";
    date.textContent = entry.date;
    li.appendChild(text);
    li.appendChild(date);
    list.appendChild(li);
  });
}

$("jarAddBtn").addEventListener("click", () => {
  const input = $("jarInput");
  const text = input.value.trim();
  if (!text) return;
  const jar = store.getJar();
  jar.push({ text: text.slice(0, 200), date: todayKey() });
  store.setJar(jar);
  input.value = "";
  renderJar();
});

$("roughBtn").addEventListener("click", async () => {
  const memories = store.getJar().slice(-10).map((e) => e.text);
  $("roughBtn").disabled = true;
  $("safety").hidden = true;
  showStatus("getting something gentle ready...");

  try {
    const data = await getRoughDay(
      selectedMood || "low",
      selectedMinutes || 10,
      selectedBudget || "free",
      $("interests").value.trim(),
      memories
    );
    hideStatus();

    if (data.safety) {
      showSafety(data.message);
      return;
    }

    const box = $("roughResult");
    box.hidden = false;
    box.innerHTML = "";
    const msg = document.createElement("div");
    msg.className = "rough-msg";
    msg.textContent = data.message;
    const sug = document.createElement("div");
    sug.className = "rough-suggest";
    sug.textContent = data.suggestion;
    box.appendChild(msg);
    box.appendChild(sug);
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    hideStatus();
    showStatus(err.message || "something went wrong. please try again.");
  } finally {
    $("roughBtn").disabled = false;
  }
});

function showSafety(message) {
  $("results").hidden = true;
  $("safety").hidden = false;
  $("safetyMsg").textContent = message;
  $("safety").scrollIntoView({ behavior: "smooth", block: "center" });
}

$("goBtn").addEventListener("click", async () => {
  if (!selectedMood) {
    showStatus("pick how you are feeling first.");
    return;
  }
  if (!selectedMinutes) {
    showStatus("choose how much time you have.");
    return;
  }
  if (!selectedBudget) {
    showStatus("choose a budget.");
    return;
  }

  $("safety").hidden = true;
  $("results").hidden = true;
  $("goBtn").disabled = true;
  showStatus("finding three small joys for you...");

  const memories = store.getJar().slice(-10).map((e) => e.text);

  try {
    const data = await getQuests(
      selectedMood,
      selectedMinutes,
      selectedBudget,
      $("interests").value.trim(),
      memories
    );
    hideStatus();

    if (data.safety) {
      showSafety(data.message);
      return;
    }
    renderQuests(data);
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    hideStatus();
    showStatus(err.message || "something went wrong. please try again.");
  } finally {
    $("goBtn").disabled = false;
  }
});

renderStats();
renderJar();
