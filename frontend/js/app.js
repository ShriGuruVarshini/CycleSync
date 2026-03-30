/**
 * CycleSync SPA — plain JS, no framework.
 * JWT ID token is stored in memory only (never localStorage/sessionStorage).
 */

const API_BASE = "/api"; // local dev: served by scripts/local_server.py

// ── In-memory auth state ──────────────────────────────────────────────────
let _idToken = null;
let _resetEmail = null; // held between forgot-password and reset-password screens

function setToken(token) { _idToken = token; }
function clearToken()    { _idToken = null; }
function getToken()      { return _idToken; }

// ── View routing ──────────────────────────────────────────────────────────
const views = ["login", "register", "forgot", "reset", "dashboard", "profile", "mood"];

function showView(name) {
  views.forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.classList.toggle("hidden", v !== name);
  });
}

// ── API helpers ───────────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (getToken()) headers["Authorization"] = `Bearer ${getToken()}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

function showError(elId, msg) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
}

function hideError(elId) {
  const el = document.getElementById(elId);
  if (el) el.classList.add("hidden");
}

// ── Login ─────────────────────────────────────────────────────────────────
document.getElementById("form-login").addEventListener("submit", async e => {
  e.preventDefault();
  hideError("login-error");
  const email    = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const { ok, data } = await apiFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (ok) {
    setToken(data.token || data.id_token);
    showView("dashboard");
    loadDashboard();
  } else {
    showError("login-error", data.message || "Invalid email or password.");
  }
});

// ── Register ──────────────────────────────────────────────────────────────
document.getElementById("form-register").addEventListener("submit", async e => {
  e.preventDefault();
  hideError("reg-error");
  const payload = {
    email:             document.getElementById("reg-email").value.trim(),
    password:          document.getElementById("reg-password").value,
    display_name:      document.getElementById("reg-name").value.trim(),
    age:               parseInt(document.getElementById("reg-age").value, 10),
    last_period_date:  document.getElementById("reg-lpd").value,
    cycle_length_days: parseInt(document.getElementById("reg-cycle").value, 10),
  };
  const { ok, data } = await apiFetch("/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (ok) {
    setToken(data.token || data.id_token);
    showView("dashboard");
    loadDashboard();
  } else {
    showError("reg-error", data.message || "Registration failed.");
  }
});

// ── Forgot password ───────────────────────────────────────────────────────
document.getElementById("form-forgot").addEventListener("submit", async e => {
  e.preventDefault();
  hideError("forgot-msg");
  _resetEmail = document.getElementById("forgot-email").value.trim();
  await apiFetch("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email: _resetEmail }),
  });
  // Always show generic confirmation regardless of whether email exists
  const msg = document.getElementById("forgot-msg");
  msg.textContent = "If this email is registered, you will receive a reset code.";
  msg.classList.remove("hidden");
  setTimeout(() => showView("reset"), 2000);
});

// ── Reset password ────────────────────────────────────────────────────────
document.getElementById("form-reset").addEventListener("submit", async e => {
  e.preventDefault();
  hideError("reset-error");
  const code     = document.getElementById("reset-code").value.trim();
  const password = document.getElementById("reset-password").value;
  const confirm  = document.getElementById("reset-confirm").value;
  if (password !== confirm) {
    showError("reset-error", "Passwords do not match.");
    return;
  }
  const { ok, data } = await apiFetch("/auth/confirm-forgot-password", {
    method: "POST",
    body: JSON.stringify({ email: _resetEmail, code, password }),
  });
  if (ok) {
    showView("login");
  } else {
    showError("reset-error", data.message || "Invalid or expired code.");
  }
});

// ── Logout ────────────────────────────────────────────────────────────────
async function logout() {
  await apiFetch("/auth/logout", { method: "POST" });
  clearToken();
  showView("login");
}

// ── Dashboard ─────────────────────────────────────────────────────────────
async function loadDashboard() {
  const container = document.getElementById("dashboard-content");
  container.innerHTML = '<p class="loading">Loading your dashboard…</p>';
  const { ok, data } = await apiFetch("/dashboard");
  if (!ok) {
    container.innerHTML = `<p class="error">${data.message || "Failed to load dashboard."}</p>`;
    return;
  }
  renderDashboard(data);
}

function renderDashboard(d) {
  const container = document.getElementById("dashboard-content");
  const activeMood    = d.active_mood    || "";
  const predictedMood = d.predicted_mood || "";
  const loggedMood    = d.logged_mood    || "";
  const name = d.display_name || "there";

  // Determine nudge based on active mood (logged takes priority over predicted)
  // Show hobby pop-up whenever active mood is Sad or Angry
  const needsNudge = activeMood === "Sad" || activeMood === "Angry";

  // Build nudge message based on active + predicted combo
  function getNudge() {
    if (activeMood === "Sad" && predictedMood === "Sad") {
      return {
        emoji: "🌧️",
        line: `Hey ${name}, I can see you're feeling sad today — and your cycle agrees.`,
        cta: "I know what you love. Let your hobbies wrap you in a little comfort 💛",
        show: true,
      };
    }
    if (activeMood === "Sad" && predictedMood === "Happy") {
      return {
        emoji: "🌤️",
        line: `Hey ${name}, you're feeling sad today — but brighter days are coming soon.`,
        cta: "Your hobbies are here to lift you up in the meantime 🌸",
        show: true,
      };
    }
    if (activeMood === "Angry" && predictedMood === "Angry") {
      return {
        emoji: "🔥",
        line: `Hey ${name}, feeling fired up today — totally valid for this phase.`,
        cta: "Channel that energy into something you love 🌿",
        show: true,
      };
    }
    if (activeMood === "Angry" && predictedMood === "Happy") {
      return {
        emoji: "⚡",
        line: `Hey ${name}, feeling a bit intense today — that's okay.`,
        cta: "Take a breath and try one of your favourite things 🎶",
        show: true,
      };
    }
    if (activeMood === "Happy") {
      return {
        emoji: "✨",
        line: `Hey ${name}, you're glowing today!`,
        cta: "Keep that energy going — dive into something you love 🎉",
        show: true,
      };
    }
    return { emoji: "💫", line: `Hey ${name}!`, cta: "Here are your hobbies for today.", show: true };
  }

  const nudge = getNudge();

  // Hobby icons
  const hobbyIcon = { Songs: "🎵", Movies: "🎬", Poetry: "📖", "Digital Colouring": "🎨" };
  const hobbies = Object.keys(d.recommendations || {});

  const hobbiesHtml = hobbies.map((cat, i) => `
    <div class="hobby-pill" style="animation-delay:${0.12 * i}s" onclick="toggleHobbyItems('hobby-${i}')">
      <span class="hobby-icon">${hobbyIcon[cat] || "🌟"}</span>
      <span class="hobby-name">${escHtml(cat)}</span>
      <span class="hobby-arrow" id="arrow-${i}">▾</span>
    </div>
    <div class="hobby-items hidden" id="hobby-${i}">
      ${(d.recommendations[cat] || []).length === 0
        ? `<p class="hobby-empty">No items yet — add some via the admin panel!</p>`
        : (d.recommendations[cat] || []).map(item => `
          <div class="rec-card">
            <div class="rec-title">${escHtml(item.title)}</div>
            <div class="rec-desc">${escHtml(item.description)}</div>
          </div>`).join("")}
    </div>`).join("");

  // Mood badge class
  const moodClass = { Sad: "mood-sad", Angry: "mood-angry", Happy: "mood-happy" };

  container.innerHTML = `
    <div class="phase-card">
      <h2>${escHtml(d.phase)} — Day ${d.day_in_cycle}</h2>
      <p class="phase-message">${escHtml(d.phase_message || "")}</p>
      <div class="support-message">${escHtml(d.support_message || "")}</div>
    </div>

    <div class="mood-display">
      <div class="mood-badge ${loggedMood ? "logged" : "predicted"} ${moodClass[activeMood] || ""}">
        <div class="label">Active Mood ${loggedMood ? "(logged)" : "(predicted)"}</div>
        <div class="value">${escHtml(activeMood)}</div>
      </div>
      ${loggedMood ? `
      <div class="mood-badge predicted ${moodClass[predictedMood] || ""}">
        <div class="label">Predicted Mood</div>
        <div class="value">${escHtml(predictedMood)}</div>
      </div>` : ""}
    </div>

    <div class="nudge-card ${needsNudge ? "nudge-highlight" : ""}">
      <div class="nudge-emoji">${nudge.emoji}</div>
      <p class="nudge-line">${nudge.line}</p>
      <p class="nudge-cta">${nudge.cta}</p>
      <div class="hobby-list">${hobbiesHtml}</div>
    </div>
  `;
}

function toggleHobbyItems(id) {
  const el    = document.getElementById(id);
  const index = id.split("-")[1];
  const arrow = document.getElementById(`arrow-${index}`);
  if (!el) return;
  const isHidden = el.classList.contains("hidden");
  el.classList.toggle("hidden", !isHidden);
  if (arrow) arrow.textContent = isHidden ? "▴" : "▾";
  if (isHidden) {
    el.classList.add("hobby-pop");
    setTimeout(() => el.classList.remove("hobby-pop"), 400);
  }
}

// ── Profile ───────────────────────────────────────────────────────────────
async function loadProfile() {
  const { ok, data } = await apiFetch("/profile");
  if (!ok) return;
  document.getElementById("prof-name").value  = data.display_name || "";
  document.getElementById("prof-age").value   = data.age || "";
  document.getElementById("prof-lpd").value   = data.last_period_date || "";
  document.getElementById("prof-cycle").value = data.cycle_length_days || "";
  document.getElementById("prof-lang").value  = data.language_preference || "en";
  const hobbies = data.hobby_preferences || [];
  document.querySelectorAll("#form-hobbies input[name='hobby']").forEach(cb => {
    cb.checked = hobbies.includes(cb.value);
  });
}

document.getElementById("form-profile").addEventListener("submit", async e => {
  e.preventDefault();
  hideError("prof-error");
  const payload = {
    display_name:       document.getElementById("prof-name").value.trim(),
    age:                parseInt(document.getElementById("prof-age").value, 10),
    last_period_date:   document.getElementById("prof-lpd").value,
    cycle_length_days:  parseInt(document.getElementById("prof-cycle").value, 10),
    language_preference: document.getElementById("prof-lang").value,
  };
  const { ok, data } = await apiFetch("/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!ok) showError("prof-error", data.message || "Failed to save profile.");
});

document.getElementById("form-hobbies").addEventListener("submit", async e => {
  e.preventDefault();
  const hobbies = [...document.querySelectorAll("#form-hobbies input[name='hobby']:checked")]
    .map(cb => cb.value);
  await apiFetch("/profile/hobbies", {
    method: "PUT",
    body: JSON.stringify({ hobby_preferences: hobbies }),
  });
});

// ── Mood ──────────────────────────────────────────────────────────────────
async function loadMoodHistory() {
  const { ok, data } = await apiFetch("/mood/history");
  const container = document.getElementById("mood-history");
  if (!ok || !Array.isArray(data.entries)) {
    container.innerHTML = "<p>No mood history found.</p>";
    return;
  }
  container.innerHTML = data.entries.map(entry => `
    <div class="mood-entry">
      <span class="entry-date">${escHtml(entry.entry_date)}</span>
      <span class="entry-mood">${escHtml(entry.mood)}</span>
      <span class="entry-note">${escHtml(entry.note || "")}</span>
    </div>`).join("");
}

document.getElementById("form-mood").addEventListener("submit", async e => {
  e.preventDefault();
  hideError("mood-error");
  const mood = document.querySelector("input[name='mood']:checked")?.value;
  const note = document.getElementById("mood-note").value;
  if (!mood) { showError("mood-error", "Please select a mood."); return; }
  const { ok, data } = await apiFetch("/mood", {
    method: "POST",
    body: JSON.stringify({ mood, note }),
  });
  if (!ok) showError("mood-error", data.message || "Failed to save mood.");
  else loadMoodHistory();
});

// ── Navigation wiring ─────────────────────────────────────────────────────
document.getElementById("link-register").addEventListener("click", e => { e.preventDefault(); showView("register"); });
document.getElementById("link-login").addEventListener("click",    e => { e.preventDefault(); showView("login"); });
document.getElementById("link-forgot").addEventListener("click",   e => { e.preventDefault(); showView("forgot"); });
document.getElementById("link-back-login").addEventListener("click", e => { e.preventDefault(); showView("login"); });

document.getElementById("nav-profile").addEventListener("click",   e => { e.preventDefault(); showView("profile"); loadProfile(); });
document.getElementById("nav-mood").addEventListener("click",      e => { e.preventDefault(); showView("mood"); loadMoodHistory(); });
document.getElementById("nav-logout").addEventListener("click",    e => { e.preventDefault(); logout(); });
document.getElementById("nav-dashboard").addEventListener("click", e => { e.preventDefault(); showView("dashboard"); loadDashboard(); });
document.getElementById("nav-logout2").addEventListener("click",   e => { e.preventDefault(); logout(); });
document.getElementById("nav-dashboard2").addEventListener("click",e => { e.preventDefault(); showView("dashboard"); loadDashboard(); });
document.getElementById("nav-logout3").addEventListener("click",   e => { e.preventDefault(); logout(); });

// ── Helpers ───────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Boot ──────────────────────────────────────────────────────────────────
// In local dev mode auth is bypassed — go straight to dashboard.
// For production, change this to showView("login").
const _isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
if (_isLocal) {
  setToken("local-bypass-token");
  showView("dashboard");
  loadDashboard();
} else {
  showView("login");
}
