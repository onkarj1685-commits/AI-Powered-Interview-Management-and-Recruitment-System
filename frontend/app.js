// ============================================================
// ROSTER — Interview Management System (Frontend Logic)
// Modern SaaS Dashboard — No build step required.
// ============================================================

const API_BASE =
  typeof window !== "undefined" && window.location.protocol.startsWith("http") && window.location.origin
    ? window.location.origin
    : "http://localhost:8000";

// ============ AUTHENTICATION GUARD ============

function checkAuth() {
  const token = localStorage.getItem("auth_token");
  if (!token) {
    const isHttp = typeof window !== "undefined" && window.location.protocol.startsWith("http");
    window.location.href = isHttp ? "/login" : "login.html";
    return false;
  }
  return true;
}

// Enforce login for dashboard view
checkAuth();

// ============ API HELPER ============

async function api(path, options = {}) {
  const token = localStorage.getItem("auth_token");
  const defaultHeaders = { "Content-Type": "application/json" };
  if (token) {
    defaultHeaders["Authorization"] = `Bearer ${token}`;
  }
  const mergedHeaders = { ...defaultHeaders, ...(options.headers || {}) };

  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: mergedHeaders,
  });

  if (resp.status === 401 && !path.startsWith("/auth/login")) {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    window.location.href = "/login?expired=1";
    throw new Error("Session expired. Please log in again.");
  }

  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const detail = (data && data.detail) || resp.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

// ============ TOAST NOTIFICATIONS ============

function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const icons = { success: "✅", error: "❌", warning: "⚠️" };
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || icons.success}</span>
    <span>${message}</span>
    <button class="toast-dismiss" onclick="dismissToast(this)">&times;</button>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = "toastSlideOut 0.3s ease forwards";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function dismissToast(btn) {
  const toast = btn.closest(".toast");
  toast.style.animation = "toastSlideOut 0.3s ease forwards";
  setTimeout(() => toast.remove(), 300);
}

// ============ UTILITY HELPERS ============

function formToJson(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  ["duration_minutes", "score", "candidate_id", "job_id", "interviewer_id", "interview_id"].forEach((key) => {
    if (key in data && data[key] !== "") data[key] = Number(data[key]);
  });
  return data;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function statusBadge(status) {
  const norm = (status || "").toLowerCase();
  const labels = {
    scheduled: "Scheduled", completed: "Completed",
    cancelled: "Cancelled", no_show: "No Show",
    open: "Open", closed: "Closed", on_hold: "On Hold",
    applied: "Applied", shortlisted: "Shortlisted",
    selected: "Selected", rejected: "Rejected",
    sent: "Delivered", failed: "Failed", pending: "Pending",
  };
  return `<span class="badge badge-${norm}"><span class="badge-dot"></span>${labels[norm] || status}</span>`;
}

function getInitials(name) {
  if (!name) return "US";
  return name.trim().split(/\s+/).map(w => w[0]).join("").toUpperCase().slice(0, 2) || "US";
}

// ============ TOGGLE FORM PANELS ============

function toggleForm(entity) {
  const panel = document.getElementById(`form-panel-${entity}`);
  if (panel.style.display === "none") {
    panel.style.display = "block";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } else {
    panel.style.display = "none";
  }
}

// ============ TAB / VIEW NAVIGATION ============

function switchView(viewName) {
  if (!viewName) return;
  const btn = document.querySelector(`.nav-item[data-view="${viewName}"]`);
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  if (btn) btn.classList.add("active");
  const viewId = `view-${viewName}`;
  const targetEl = document.getElementById(viewId);
  if (targetEl) targetEl.classList.add("active");

  // Load view-specific data
  if (viewName === "dashboard") loadDashboard();
  if (viewName === "analytics") initAnalyticsView();
  if (viewName === "resume-analyzer") initResumeAnalyzerView();
  if (viewName === "resume-screening") initResumeScreeningView();
  if (viewName === "notifications") loadNotifications();

  // Push history state if supported
  if (typeof window !== "undefined" && window.history && window.history.pushState) {
    const url = viewName === "dashboard" ? "/" : `/${viewName}`;
    if (window.location.pathname !== url && !window.location.protocol.startsWith("file:")) {
      window.history.pushState({ view: viewName }, "", url);
    }
  }
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.view) switchView(btn.dataset.view);
  });
});

// Detect active route on page load
window.addEventListener("DOMContentLoaded", () => {
  const path = (window.location.pathname || "").replace(/^\//, "").split("/")[0].toLowerCase();
  const hash = (window.location.hash || "").replace(/^#/, "").toLowerCase();
  if (path === "analytics" || hash === "analytics") {
    switchView("analytics");
  } else if (path && document.getElementById(`view-${path}`)) {
    switchView(path);
  }
});

// ============ SEARCH / FILTER ============

function setupSearch(inputId, tableId, columns) {
  const input = document.getElementById(inputId);
  if (!input) return;
  input.addEventListener("input", () => {
    const term = input.value.toLowerCase();
    const rows = document.querySelectorAll(`#${tableId} tr`);
    rows.forEach((row) => {
      if (row.classList.contains("empty-state-row")) return;
      const cells = Array.from(row.querySelectorAll("td"));
      const text = columns.map(i => (cells[i] ? cells[i].textContent : "")).join(" ").toLowerCase();
      row.style.display = text.includes(term) ? "" : "none";
    });
  });
}

// ============ DASHBOARD ============

async function loadDashboard() {
  try {
    const stats = await api("/dashboard/stats");

    // KPI values
    document.getElementById("kpi-candidates").textContent = stats.total_candidates;
    document.getElementById("kpi-jobs").textContent = stats.total_jobs;
    document.getElementById("kpi-interviews").textContent = stats.total_interviews;
    document.getElementById("kpi-score").textContent =
      stats.average_score !== null ? stats.average_score.toFixed(1) : "—";

    // Interview status bars
    const totalInt = stats.total_interviews || 1;
    const statusColors = {
      scheduled: "#D97706", completed: "#059669",
      cancelled: "#DC2626", no_show: "#BE123C",
    };
    const statusContainer = document.getElementById("status-chart");
    statusContainer.innerHTML = "";
    for (const [key, count] of Object.entries(stats.interviews_by_status)) {
      const pct = Math.round((count / totalInt) * 100);
      statusContainer.innerHTML += `
        <div class="status-bar-item">
          <span class="status-bar-label">${key.replace("_", " ")}</span>
          <div class="status-bar-track">
            <div class="status-bar-fill" style="width:${pct}%; background:${statusColors[key] || '#6366F1'}"></div>
          </div>
          <span class="status-bar-count">${count}</span>
        </div>
      `;
    }

    // Job status bars
    const totalJobs = stats.total_jobs || 1;
    const jobColors = { open: "#059669", on_hold: "#D97706", closed: "#DC2626" };
    const jobContainer = document.getElementById("job-status-chart");
    jobContainer.innerHTML = "";
    for (const [key, count] of Object.entries(stats.jobs_by_status)) {
      const pct = Math.round((count / totalJobs) * 100);
      jobContainer.innerHTML += `
        <div class="status-bar-item">
          <span class="status-bar-label">${key.replace("_", " ")}</span>
          <div class="status-bar-track">
            <div class="status-bar-fill" style="width:${pct}%; background:${jobColors[key] || '#6366F1'}"></div>
          </div>
          <span class="status-bar-count">${count}</span>
        </div>
      `;
    }

    // Recent interviews
    const recentEl = document.getElementById("recent-interviews");
    if (stats.recent_interviews.length === 0) {
      recentEl.innerHTML = `
        <div class="empty-state">
          <span class="empty-icon">📅</span>
          <p>No interviews yet</p>
        </div>`;
    } else {
      recentEl.innerHTML = stats.recent_interviews.map(iv => `
        <div class="recent-item">
          <div class="recent-avatar">${getInitials(iv.candidate_name)}</div>
          <div class="recent-info">
            <div class="recent-name">${iv.candidate_name}</div>
            <div class="recent-detail">${iv.round_name || iv.job_title} · ${iv.interviewer_name}</div>
          </div>
          ${statusBadge(iv.status)}
          <span class="recent-time">${fmtDate(iv.scheduled_at)}</span>
        </div>
      `).join("");
    }
  } catch (err) {
    console.error("Dashboard load error:", err);
  }
}

// ============ CANDIDATES ============

async function loadCandidates() {
  const candidates = await api("/candidates/");
  const tbody = document.getElementById("table-candidates");
  tbody.innerHTML = "";
  if (candidates.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="7">
      <div class="empty-state"><span class="empty-icon">👤</span><p>No candidates yet. Add your first one above!</p></div>
    </td></tr>`;
  }
  candidates.forEach((c) => {
    const tr = document.createElement("tr");
    const resumeLink = c.resume_url
      ? `<a href="${c.resume_url.startsWith("http") ? c.resume_url : API_BASE + c.resume_url}" target="_blank" rel="noopener noreferrer" class="btn btn-ghost" style="padding:4px 10px; font-size:12px; display:inline-flex; align-items:center; gap:4px; text-decoration:none;">📄 View</a>`
      : `<span style="color:var(--text-muted); font-size:12px;">—</span>`;

    const candStatus = (c.status || "applied").toLowerCase();
    const stageBadge = statusBadge(candStatus);

    tr.innerHTML = `
      <td class="id-col">#${c.id}</td>
      <td class="name-col">${c.full_name}</td>
      <td class="mono-col">${c.email}</td>
      <td>${c.phone || '<span style="color:var(--text-muted)">—</span>'}</td>
      <td>${resumeLink}</td>
      <td>${stageBadge}</td>
      <td class="actions-col" style="display:flex; gap:6px;">
        <button class="btn btn-ghost" data-action="status-candidate" data-id="${c.id}" data-name="${encodeURIComponent(c.full_name)}" data-status="${candStatus}" style="padding:4px 8px; font-size:12px;" title="Update pipeline status & trigger email">🏷️ Stage</button>
        <button class="btn btn-danger" data-action="delete-candidate" data-id="${c.id}">Remove</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
  return candidates;
}

document.getElementById("form-candidate").addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  const originalText = submitBtn.textContent;
  try {
    const fileInput = document.getElementById("candidate-resume-file");
    let resumeUrl = null;

    if (fileInput && fileInput.files && fileInput.files.length > 0) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Uploading resume…";

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);

      const uploadResp = await fetch(`${API_BASE}/candidates/upload-resume`, {
        method: "POST",
        body: formData,
      });

      if (!uploadResp.ok) {
        const err = await uploadResp.json().catch(() => null);
        throw new Error((err && err.detail) || "Failed to upload resume file");
      }

      const uploadResult = await uploadResp.json();
      resumeUrl = uploadResult.resume_url;
    }

    const payload = formToJson(e.target);
    payload.resume_url = resumeUrl || payload.resume_url || null;

    submitBtn.textContent = "Saving candidate…";
    await api("/candidates/", { method: "POST", body: JSON.stringify(payload) });
    showToast("Candidate added successfully! HR notification dispatched. 📢");
    e.target.reset();
    if (fileInput) fileInput.value = "";
    toggleForm("candidate");
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = originalText;
  }
});

document.getElementById("table-candidates").addEventListener("click", async (e) => {
  if (e.target.dataset.action === "status-candidate") {
    const id = e.target.dataset.id;
    const name = decodeURIComponent(e.target.dataset.name || "Candidate");
    const status = e.target.dataset.status || "applied";
    openCandidateStatusModal(id, name, status);
    return;
  }
  if (e.target.dataset.action === "delete-candidate") {
    if (!confirm("Remove this candidate? This will also delete their interviews.")) return;
    try {
      await api(`/candidates/${e.target.dataset.id}`, { method: "DELETE" });
      showToast("Candidate removed.");
      await refreshAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }
});

// ============ JOB POSITIONS ============

async function loadJobs() {
  const jobs = await api("/jobs/");
  const tbody = document.getElementById("table-jobs");
  tbody.innerHTML = "";
  if (jobs.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="5">
      <div class="empty-state"><span class="empty-icon">💼</span><p>No job positions yet. Create one above!</p></div>
    </td></tr>`;
  }
  jobs.forEach((j) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="id-col">#${j.id}</td>
      <td class="name-col">${j.title}</td>
      <td>${j.department || '<span style="color:var(--text-muted)">—</span>'}</td>
      <td>${statusBadge(j.status)}</td>
      <td class="actions-col">
        <button class="btn btn-danger" data-action="delete-job" data-id="${j.id}">Remove</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
  return jobs;
}

document.getElementById("form-job").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/jobs/", { method: "POST", body: JSON.stringify(formToJson(e.target)) });
    showToast("Job position added!");
    e.target.reset();
    toggleForm("job");
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
});

document.getElementById("table-jobs").addEventListener("click", async (e) => {
  if (e.target.dataset.action === "delete-job") {
    if (!confirm("Remove this job position?")) return;
    try {
      await api(`/jobs/${e.target.dataset.id}`, { method: "DELETE" });
      showToast("Job position removed.");
      await refreshAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }
});

// ============ INTERVIEWERS ============

async function loadInterviewers() {
  const interviewers = await api("/interviewers/");
  const tbody = document.getElementById("table-interviewers");
  tbody.innerHTML = "";
  if (interviewers.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="5">
      <div class="empty-state"><span class="empty-icon">🎯</span><p>No interviewers yet. Add one above!</p></div>
    </td></tr>`;
  }
  interviewers.forEach((i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="id-col">#${i.id}</td>
      <td class="name-col">${i.full_name}</td>
      <td class="mono-col">${i.email}</td>
      <td>${i.title || '<span style="color:var(--text-muted)">—</span>'}</td>
      <td class="actions-col">
        <button class="btn btn-danger" data-action="delete-interviewer" data-id="${i.id}">Remove</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
  return interviewers;
}

document.getElementById("form-interviewer").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/interviewers/", { method: "POST", body: JSON.stringify(formToJson(e.target)) });
    showToast("Interviewer added!");
    e.target.reset();
    toggleForm("interviewer");
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
});

document.getElementById("table-interviewers").addEventListener("click", async (e) => {
  if (e.target.dataset.action === "delete-interviewer") {
    if (!confirm("Remove this interviewer?")) return;
    try {
      await api(`/interviewers/${e.target.dataset.id}`, { method: "DELETE" });
      showToast("Interviewer removed.");
      await refreshAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  }
});

// ============ INTERVIEWS ============

function fillSelect(select, items, labelFn) {
  if (items.length === 0) {
    select.innerHTML = '<option value="" disabled>None available</option>';
    return;
  }
  select.innerHTML = items.map((i) => `<option value="${i.id}">${labelFn(i)}</option>`).join("");
}

async function loadInterviews(candidates, jobs, interviewers) {
  window.cachedCandidates = candidates;
  window.cachedJobs = jobs;
  window.cachedInterviewers = interviewers;

  fillSelect(document.getElementById("select-candidate"), candidates, (c) => c.full_name);
  fillSelect(document.getElementById("select-job"), jobs, (j) => j.title);
  fillSelect(document.getElementById("select-interviewer"), interviewers, (i) => i.full_name);

  const interviews = await api("/interviews/");
  window.cachedInterviews = interviews;
  const tbody = document.getElementById("table-interviews");
  tbody.innerHTML = "";
  if (interviews.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="8">
      <div class="empty-state"><span class="empty-icon">📅</span><p>No interviews scheduled yet.</p></div>
    </td></tr>`;
  }

  const candidateById = Object.fromEntries(candidates.map((c) => [c.id, c]));
  const interviewerById = Object.fromEntries(interviewers.map((i) => [i.id, i]));

  interviews.forEach((iv) => {
    const candidate = candidateById[iv.candidate_id];
    const interviewer = interviewerById[iv.interviewer_id];
    const tr = document.createElement("tr");

    const meetingHtml = iv.meeting_link
      ? (iv.meeting_link.startsWith("http")
        ? `<a href="${iv.meeting_link}" target="_blank" rel="noopener noreferrer" class="btn btn-ghost" style="padding:2px 8px; font-size:11px; text-decoration:none; display:inline-flex; align-items:center; gap:4px;">🎥 Join</a>`
        : `<span style="font-size:12px; color:var(--text-secondary); max-width:110px; display:inline-block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${iv.meeting_link}">📍 ${iv.meeting_link}</span>`)
      : `<span style="color:var(--text-muted); font-size:12px;">—</span>`;

    const reminderSentPill = iv.reminder_sent
      ? `<span title="24-hour reminder email delivered" style="display:inline-block; font-size:10px; background:#ECFDF5; color:#059669; padding:2px 6px; border-radius:10px; font-weight:600; margin-left:4px;">✓ Reminded</span>`
      : "";

    tr.innerHTML = `
      <td class="id-col">#${iv.id}</td>
      <td class="name-col">${candidate ? candidate.full_name : "—"}</td>
      <td>${iv.round_name || '<span style="color:var(--text-muted)">—</span>'}</td>
      <td>${interviewer ? interviewer.full_name : "—"}</td>
      <td class="mono-col">${fmtDate(iv.scheduled_at)}</td>
      <td>${meetingHtml}</td>
      <td>${statusBadge(iv.status)} ${reminderSentPill}</td>
      <td class="actions-col" style="display:flex; flex-wrap:wrap; gap:4px;">
        <button class="btn btn-ghost" data-action="feedback" data-id="${iv.id}" style="padding:4px 8px; font-size:11px;">📝 Feedback</button>
        <button class="btn btn-ghost" data-action="reschedule" data-id="${iv.id}" style="padding:4px 8px; font-size:11px;" title="Reschedule & dispatch email">📅 Reschedule</button>
        <button class="btn btn-ghost" data-action="send-reminder" data-id="${iv.id}" style="padding:4px 8px; font-size:11px;" title="Send 24h reminder email now">⏰ Remind</button>
        ${iv.status !== 'cancelled' ? `<button class="btn btn-danger" data-action="cancel-interview" data-id="${iv.id}" style="padding:4px 8px; font-size:11px;" title="Cancel & dispatch cancellation email">Cancel</button>` : ''}
        <button class="btn btn-ghost" data-action="delete-interview" data-id="${iv.id}" style="padding:4px 6px; font-size:11px; color:var(--text-muted);" title="Delete Record">✕</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById("form-interview").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/interviews/", { method: "POST", body: JSON.stringify(formToJson(e.target)) });
    showToast("Interview scheduled! Confirmation email sent to candidate. 🎉");
    e.target.reset();
    toggleForm("interview");
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
});

document.getElementById("table-interviews").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const action = btn.dataset.action;
  const id = btn.dataset.id;

  if (action === "delete-interview") {
    if (!confirm("Remove this interview record?")) return;
    try {
      await api(`/interviews/${id}`, { method: "DELETE" });
      showToast("Interview record removed.");
      await refreshAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  } else if (action === "feedback") {
    openFeedbackModal(id);
  } else if (action === "reschedule") {
    openRescheduleModal(id);
  } else if (action === "cancel-interview") {
    const reason = prompt("Optional cancellation reason to include in email to candidate:", "Interviewer emergency / schedule conflict");
    if (reason === null) return; // user cancelled prompt
    try {
      await api(`/interviews/${id}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason: reason || "Interview cancelled by HR" }),
      });
      showToast("Interview cancelled! Cancellation email sent to candidate. ⚠️");
      await refreshAll();
    } catch (err) {
      showToast(err.message, "error");
    }
  } else if (action === "send-reminder") {
    try {
      btn.disabled = true;
      btn.textContent = "Sending…";
      const resp = await api(`/interviews/${id}/send-reminder`, { method: "POST" });
      if (resp && resp.status === "failed") {
        showToast(`Email delivery failed: ${resp.error_message || "SMTP dispatch error"}`, "error");
      } else {
        showToast("24-hour reminder email dispatched successfully! ⏰");
      }
      await refreshAll();
    } catch (err) {
      showToast(err.message || "Failed to dispatch reminder email", "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⏰ Remind";
    }
  }
});

// ============ FEEDBACK MODAL ============

function openFeedbackModal(interviewId) {
  document.getElementById("feedback-modal").style.display = "flex";
  document.getElementById("feedback-title").textContent = `Feedback — Interview #${interviewId}`;
  document.querySelector('#form-feedback input[name="interview_id"]').value = interviewId;
}

function closeFeedbackModal() {
  document.getElementById("feedback-modal").style.display = "none";
  document.getElementById("form-feedback").reset();
}

document.getElementById("cancel-feedback").addEventListener("click", closeFeedbackModal);

// Close modal when clicking overlay background
document.getElementById("feedback-modal").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeFeedbackModal();
});

document.getElementById("form-feedback").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = formToJson(e.target);
  const interviewId = payload.interview_id;
  delete payload.interview_id;
  try {
    await api(`/interviews/${interviewId}/feedback`, { method: "POST", body: JSON.stringify(payload) });
    showToast("Feedback submitted — interview marked completed! ✅");
    closeFeedbackModal();
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
});

// ============ API CONNECTION CHECK ============

async function checkApiConnection() {
  const dot = document.getElementById("api-dot");
  const text = document.getElementById("api-status-text");
  try {
    await api("/health");
    dot.classList.remove("error");
    text.textContent = "API Connected";
    return true;
  } catch {
    dot.classList.add("error");
    text.textContent = "API Offline";
    return false;
  }
}

// ============ BOOTSTRAP ============

async function refreshAll() {
  const [candidates, jobs, interviewers] = await Promise.all([
    loadCandidates(),
    loadJobs(),
    loadInterviewers(),
  ]);
  await loadInterviews(candidates, jobs, interviewers);
  // Refresh dashboard stats if dashboard is the active view
  if (document.getElementById("view-dashboard").classList.contains("active")) {
    await loadDashboard();
  }
  // Refresh analytics if analytics view is active
  if (document.getElementById("view-analytics")?.classList.contains("active")) {
    await loadAnalyticsData();
  }
  // Refresh notifications if notifications view is active
  if (document.getElementById("view-notifications")?.classList.contains("active")) {
    await loadNotifications(currentNotificationFilter);
  }
}

// Initialize search handlers
setupSearch("search-candidates", "table-candidates", [1, 2]);
setupSearch("search-jobs", "table-jobs", [1, 2]);
setupSearch("search-interviewers", "table-interviewers", [1, 2, 3]);
setupSearch("search-interviews", "table-interviews", [1, 2, 3]);

function initUserProfile() {
  const badge = document.getElementById("user-profile-badge");
  const loginLink = document.getElementById("btn-sidebar-login");
  const avatarEl = document.getElementById("sidebar-user-avatar");
  const nameEl = document.getElementById("sidebar-user-name");
  const roleEl = document.getElementById("sidebar-user-role");
  const logoutBtn = document.getElementById("btn-logout");

  const token = localStorage.getItem("auth_token");
  const rawUser = localStorage.getItem("auth_user");
  let user = null;
  if (rawUser) {
    try {
      user = JSON.parse(rawUser);
    } catch (e) {
      user = null;
    }
  }

  if (token && badge) {
    badge.style.display = "flex";
    if (loginLink) loginLink.style.display = "none";
    const displayName = (user && (user.name || user.full_name || user.username)) || "User";
    if (nameEl) nameEl.textContent = displayName;
    if (roleEl) roleEl.textContent = (user && user.role ? user.role.toUpperCase() : "HR/USER");

    // Display profile picture from Google OAuth or fallback to initials
    if (avatarEl) {
      if (user && user.profile_picture) {
        avatarEl.innerHTML = `<img src="${user.profile_picture}" class="user-avatar-img" alt="${displayName}" onerror="this.parentElement.textContent='${getInitials(displayName)}'">`;
      } else {
        avatarEl.textContent = getInitials(displayName);
      }
    }
  } else if (loginLink) {
    if (badge) badge.style.display = "none";
    loginLink.style.display = "inline-flex";
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      try {
        await api("/auth/logout", { method: "POST" }).catch(() => { });
      } catch (e) {
        // Continue clearing client credentials
      }
      localStorage.removeItem("auth_token");
      localStorage.removeItem("auth_user");
      const isHttp = typeof window !== "undefined" && window.location.protocol.startsWith("http");
      window.location.href = isHttp ? "/login" : "login.html";
    });
  }
}

// Boot the app
(async () => {
  initUserProfile();
  const connected = await checkApiConnection();
  if (connected) {
    await loadDashboard();
    await refreshAll();

    // Direct routing support for /analytics
    if (window.location.pathname === "/analytics" || window.location.hash === "#analytics") {
      const anNav = document.querySelector('.nav-item[data-view="analytics"]');
      if (anNav) anNav.click();
    }
  } else {
    const main = document.querySelector(".main-content");
    main.insertAdjacentHTML(
      "afterbegin",
      `<div class="error-banner">
        <span class="error-banner-icon">⚠️</span>
        <div>
          <h3>Connection Error</h3>
          <p>Could not reach the API at <code>${API_BASE}</code>. 
          Make sure the backend is running, then reload this page.</p>
        </div>
      </div>`
    );
  }
})();

// ============ AI INTERVIEW HELPER ============

function switchAiTab(tab) {
  const askPanel = document.getElementById("ai-panel-ask");
  const genPanel = document.getElementById("ai-panel-gen");
  const askBtn = document.getElementById("btn-tab-ai-ask");
  const genBtn = document.getElementById("btn-tab-ai-gen");

  if (!askPanel || !genPanel) return;

  if (tab === "ask") {
    askPanel.style.display = "block";
    genPanel.style.display = "none";
    askBtn.className = "btn btn-primary";
    genBtn.className = "btn btn-secondary";
  } else {
    askPanel.style.display = "none";
    genPanel.style.display = "block";
    askBtn.className = "btn btn-secondary";
    genBtn.className = "btn btn-primary";
  }
}

function setAiPrompt(text) {
  const input = document.getElementById("ai-ask-question");
  if (input) {
    input.value = text;
    input.focus();
  }
}

function openAiForRole(role = "candidate") {
  document.querySelectorAll(".sidebar-nav .nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === "ai-assistant");
  });
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("active", v.id === "view-ai-assistant");
  });
  switchAiTab("ask");
  const roleSelect = document.getElementById("ai-ask-role");
  if (roleSelect) {
    roleSelect.value = role.toLowerCase() === "interviewer" ? "interviewer" : "candidate";
  }
}

function clearAiAsk() {
  const q = document.getElementById("ai-ask-question");
  const ctx = document.getElementById("ai-ask-context");
  const res = document.getElementById("ai-ask-result-box");
  if (q) q.value = "";
  if (ctx) ctx.value = "";
  if (res) res.style.display = "none";
}

function copyAiText(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {
    showToast("Copied to clipboard!");
  }).catch(() => {
    showToast("Unable to copy to clipboard", "warning");
  });
}

document.getElementById("form-ai-ask")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = document.getElementById("btn-submit-ai-ask");
  const originalText = submitBtn.innerHTML;
  const question = document.getElementById("ai-ask-question").value.trim();
  const context = document.getElementById("ai-ask-context").value.trim();
  const role = document.getElementById("ai-ask-role").value;

  if (!question) return;

  submitBtn.disabled = true;
  submitBtn.innerHTML = "<span>⏳</span> Thinking with Gemini…";

  const resultBox = document.getElementById("ai-ask-result-box");
  const resultText = document.getElementById("ai-ask-result-text");

  try {
    const data = await api("/ai/ask", {
      method: "POST",
      body: JSON.stringify({ question, context: context || null, role }),
    });
    resultText.textContent = data.answer;
    resultBox.style.display = "block";
    resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = originalText;
  }
});

document.getElementById("form-ai-gen")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = document.getElementById("btn-submit-ai-gen");
  const originalText = submitBtn.innerHTML;

  const job_title = document.getElementById("ai-gen-job-title").value.trim();
  const department = document.getElementById("ai-gen-dept").value.trim();
  const round_name = document.getElementById("ai-gen-round").value.trim();
  const experience_level = document.getElementById("ai-gen-level").value;

  if (!job_title) return;

  submitBtn.disabled = true;
  submitBtn.innerHTML = "<span>⏳</span> Generating with Gemini…";

  const resultBox = document.getElementById("ai-gen-result-box");
  const resultText = document.getElementById("ai-gen-result-text");

  try {
    const data = await api("/ai/generate-questions", {
      method: "POST",
      body: JSON.stringify({
        job_title,
        department: department || null,
        round_name: round_name || null,
        experience_level,
      }),
    });
    resultText.textContent = data.raw_response;
    resultBox.style.display = "block";
    resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = originalText;
  }
});

// ============================================================
// AI RESUME SCREENING & SHORTLISTING ENGINE (FRONTEND)
// ============================================================

let currentScreeningResults = [];
let screeningPresets = [];
let chartCandidateRanking = null;
let chartRecommendationDist = null;
let chartSkillCoverage = null;
let screeningInitialized = false;

const FALLBACK_PRESETS = [
  {
    role: "Senior Full Stack Engineer",
    min_experience_years: 3.5,
    required_skills: ["Python", "FastAPI", "PostgreSQL", "Docker", "REST APIs"],
    preferred_skills: ["AWS", "Redis", "CI/CD", "Kubernetes", "React"]
  },
  {
    role: "AI / Machine Learning Engineer",
    min_experience_years: 3.0,
    required_skills: ["Python", "Machine Learning", "PyTorch", "NLP", "Large Language Models (LLMs)"],
    preferred_skills: ["Docker", "AWS", "FastAPI", "Vector Databases", "MLOps"]
  },
  {
    role: "DevOps & Cloud Architect",
    min_experience_years: 4.0,
    required_skills: ["AWS", "Docker", "Kubernetes", "Terraform", "CI/CD", "Linux"],
    preferred_skills: ["Python", "Prometheus", "Grafana", "Ansible", "Bash"]
  },
  {
    role: "Frontend React Developer",
    min_experience_years: 2.5,
    required_skills: ["React", "JavaScript", "TypeScript", "HTML5", "CSS3", "REST APIs"],
    preferred_skills: ["Next.js", "Redux", "GraphQL", "Jest", "Tailwind CSS"]
  }
];

// Initialize the Resume Screening view
async function initResumeScreeningView() {
  if (screeningInitialized) return;
  screeningInitialized = true;

  // 1. Load presets from API or fallback
  try {
    const data = await api("/screening/presets");
    if (data && data.presets && data.presets.length > 0) {
      screeningPresets = data.presets.map(p => ({
        role: p.title || p.role || "Software Engineer",
        min_experience_years: p.min_experience_years || 2.5,
        required_skills: p.recommended_skills || p.required_skills || ["Python", "SQL", "Git"],
        preferred_skills: p.preferred_skills || ["Docker", "AWS", "REST APIs"],
      }));
    } else {
      screeningPresets = FALLBACK_PRESETS;
    }
  } catch (err) {
    console.warn("Could not fetch presets from API, using defaults", err);
    screeningPresets = FALLBACK_PRESETS;
  }

  // 2. Populate preset buttons
  renderPresetPills();

  // 3. Populate existing jobs dropdown
  try {
    const jobs = await api("/jobs/");
    const select = document.getElementById("screening-select-job");
    if (select && jobs && jobs.length > 0) {
      select.innerHTML = '<option value="">-- Custom Job Criteria --</option>' +
        jobs.map(j => `<option value="${j.id}" data-title="${j.title}">${j.title} (${j.department || 'General'})</option>`).join("");

      select.addEventListener("change", (e) => {
        const jobId = e.target.value;
        if (!jobId) return;
        const selectedOpt = select.options[select.selectedIndex];
        const jobTitle = selectedOpt.dataset.title;
        document.getElementById("screening-job-title").value = jobTitle;
        const match = screeningPresets.find(p => p.role.toLowerCase() === jobTitle.toLowerCase());
        if (match) {
          selectScreeningPreset(match);
        }
      });
    }
  } catch (err) {
    console.warn("Could not load jobs for screening dropdown", err);
  }

  // 4. Select first preset and run screening automatically
  if (screeningPresets.length > 0) {
    selectScreeningPreset(screeningPresets[0]);
    runCandidateScreening();
  }
}

function renderPresetPills() {
  const container = document.getElementById("preset-pills-container");
  if (!container) return;
  container.innerHTML = screeningPresets.map((p, idx) => `
    <button type="button" class="preset-pill-btn ${idx === 0 ? 'active' : ''}" data-idx="${idx}">
      <span>💼</span> ${p.role} (${p.min_experience_years}y+)
    </button>
  `).join("");

  container.querySelectorAll(".preset-pill-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      container.querySelectorAll(".preset-pill-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const idx = parseInt(btn.dataset.idx, 10);
      selectScreeningPreset(screeningPresets[idx]);
    });
  });
}

function selectScreeningPreset(preset) {
  document.getElementById("screening-job-title").value = preset.role;
  document.getElementById("screening-min-exp").value = preset.min_experience_years || 2.0;
  document.getElementById("screening-req-skills").value = (preset.required_skills || []).join(", ");
  document.getElementById("screening-pref-skills").value = (preset.preferred_skills || []).join(", ");
}

async function runCandidateScreening() {
  const jobTitle = document.getElementById("screening-job-title")?.value.trim() || "Software Engineer";
  const minExp = parseFloat(document.getElementById("screening-min-exp")?.value) || 0;
  const reqSkillsRaw = document.getElementById("screening-req-skills")?.value.trim() || "";
  const prefSkillsRaw = document.getElementById("screening-pref-skills")?.value.trim() || "";
  const jobId = document.getElementById("screening-select-job")?.value;

  const requiredSkills = reqSkillsRaw
    ? reqSkillsRaw.split(",").map(s => s.trim()).filter(Boolean)
    : [];
  const preferredSkills = prefSkillsRaw
    ? prefSkillsRaw.split(",").map(s => s.trim()).filter(Boolean)
    : [];

  const runBtn = document.getElementById("btn-run-screening");
  const runTopBtn = document.getElementById("btn-run-screening-top");
  const origText = runBtn ? runBtn.innerHTML : "";
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.innerHTML = "<span>⏳</span> Screening Candidates with NLP…";
  }
  if (runTopBtn) {
    runTopBtn.disabled = true;
    runTopBtn.innerHTML = "<span>⏳</span> Screening…";
  }

  try {
    const payload = {
      job_title: jobTitle,
      min_experience_years: minExp,
      required_skills: requiredSkills,
      preferred_skills: preferredSkills,
      job_id: jobId ? Number(jobId) : null,
    };

    const data = await api("/screening/screen", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    currentScreeningResults = data.rankings || data.ranked_candidates || [];
    const summary = data.summary || {};

    // 1. Update KPIs
    updateScreeningKPIs({
      total_screened: summary.total_candidates ?? data.total_screened ?? currentScreeningResults.length,
      shortlisted_count: summary.shortlisted_count ?? data.shortlisted_count ?? 0,
      highest_match_score: summary.top_score ?? data.highest_match_score ?? 0,
      average_score: summary.average_score ?? data.average_score ?? 0,
    });

    // 2. Render Charts
    renderCandidateRankingChart(currentScreeningResults);
    renderRecommendationDonutChart(data.analytics?.recommendation_distribution || data.recommendation_summary || {});
    renderSkillCoverageChart(data.analytics?.skill_coverage || data.required_skill_demand_coverage || {});

    // 3. Render Table
    renderScreenedCandidatesTable(currentScreeningResults);

    const shortlistedCount = summary.shortlisted_count ?? data.shortlisted_count ?? 0;
    showToast(`Screened ${currentScreeningResults.length} candidates. ${shortlistedCount} shortlisted!`);
  } catch (err) {
    showToast(`Screening failed: ${err.message}`, "error");
  } finally {
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.innerHTML = origText;
    }
    if (runTopBtn) {
      runTopBtn.disabled = false;
      runTopBtn.innerHTML = "<span>⚡</span> Run Screening";
    }
  }
}

function updateScreeningKPIs(data) {
  const totalEl = document.getElementById("kpi-screened-total");
  const shortEl = document.getElementById("kpi-screened-shortlisted");
  const topEl = document.getElementById("kpi-screened-top-score");
  const avgEl = document.getElementById("kpi-screened-avg-score");

  if (totalEl) totalEl.textContent = data.total_screened || 0;
  if (shortEl) shortEl.textContent = data.shortlisted_count || 0;
  if (topEl) topEl.textContent = (data.highest_match_score !== null && data.highest_match_score !== undefined)
    ? `${data.highest_match_score}%`
    : "—";
  if (avgEl) avgEl.textContent = (data.average_score !== null && data.average_score !== undefined)
    ? `${data.average_score}%`
    : "—";
}

// Chart 1: Candidate Match Ranking Leaderboard
function renderCandidateRankingChart(candidates) {
  const canvas = document.getElementById("chart-candidate-ranking");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartCandidateRanking) {
    chartCandidateRanking.destroy();
  }

  const topCandidates = candidates.slice(0, 8);
  const labels = topCandidates.map(c => `#${c.rank} ${c.candidate_name || c.full_name}`);
  const scores = topCandidates.map(c => c.overall_score);

  const colors = topCandidates.map(c => {
    const rec = (c.recommendation || "").toLowerCase().replace(/\s+/g, "_");
    switch (rec) {
      case "strongly_shortlisted": return "rgba(16, 185, 129, 0.85)";
      case "shortlisted": return "rgba(99, 102, 241, 0.85)";
      case "under_review": return "rgba(245, 158, 11, 0.85)";
      default: return "rgba(239, 68, 68, 0.75)";
    }
  });

  const borderColors = topCandidates.map(c => {
    const rec = (c.recommendation || "").toLowerCase().replace(/\s+/g, "_");
    switch (rec) {
      case "strongly_shortlisted": return "#059669";
      case "shortlisted": return "#4F46E5";
      case "under_review": return "#D97706";
      default: return "#DC2626";
    }
  });

  chartCandidateRanking = new Chart(canvas, {
    type: "bar",
    data: {
      labels: labels.length ? labels : ["No candidates"],
      datasets: [{
        label: "Match Score (%)",
        data: scores.length ? scores : [0],
        backgroundColor: colors.length ? colors : ["#CBD5E1"],
        borderColor: borderColors.length ? borderColors : ["#94A3B8"],
        borderWidth: 1.5,
        borderRadius: 6,
      }]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `Match Score: ${ctx.parsed.x}%`,
            afterLabel: (ctx) => {
              const cand = topCandidates[ctx.dataIndex];
              return cand ? `Tier: ${cand.recommendation_badge || cand.recommendation}\nExp: ${cand.experience_years} yrs` : "";
            }
          }
        }
      },
      scales: {
        x: {
          min: 0,
          max: 100,
          ticks: { callback: (val) => `${val}%`, font: { family: 'Inter', size: 11 } },
          grid: { color: "#F1F5F9" }
        },
        y: {
          ticks: { font: { family: 'Inter', size: 12, weight: '600' } },
          grid: { display: false }
        }
      }
    }
  });
}

// Chart 2: Recommendation Distribution Donut
function renderRecommendationDonutChart(summary) {
  const canvas = document.getElementById("chart-recommendation-dist");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartRecommendationDist) {
    chartRecommendationDist.destroy();
  }

  const stronglyCount = summary["Strongly Shortlisted"] ?? summary.strongly_shortlisted ?? 0;
  const shortCount = summary["Shortlisted"] ?? summary.shortlisted ?? 0;
  const reviewCount = summary["Under Review"] ?? summary.under_review ?? 0;
  const notCount = summary["Not Recommended"] ?? summary.not_recommended ?? 0;

  const total = stronglyCount + shortCount + reviewCount + notCount;

  chartRecommendationDist = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: ["Strongly Shortlisted", "Shortlisted", "Under Review", "Not Recommended"],
      datasets: [{
        data: total > 0 ? [stronglyCount, shortCount, reviewCount, notCount] : [0, 0, 0, 1],
        backgroundColor: [
          "#10B981",
          "#6366F1",
          "#F59E0B",
          "#EF4444"
        ],
        borderWidth: 2,
        borderColor: "#FFFFFF",
        hoverOffset: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "68%",
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            font: { family: 'Inter', size: 11 },
            boxWidth: 12,
            padding: 10
          }
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const val = ctx.parsed;
              const pct = total > 0 ? Math.round((val / total) * 100) : 0;
              return ` ${ctx.label}: ${val} (${pct}%)`;
            }
          }
        }
      }
    }
  });
}

// Chart 3: Skill Demand Coverage Bar Chart
function renderSkillCoverageChart(coverageData) {
  const canvas = document.getElementById("chart-skill-coverage");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartSkillCoverage) {
    chartSkillCoverage.destroy();
  }

  const skills = Object.keys(coverageData || {});
  const percentages = skills.map(s => {
    const val = coverageData[s];
    return typeof val === "object" && val !== null ? (val.percentage ?? 0) : Number(val) || 0;
  });
  const counts = skills.map(s => {
    const val = coverageData[s];
    return typeof val === "object" && val !== null ? (val.candidate_count ?? val.count ?? 0) : 0;
  });

  chartSkillCoverage = new Chart(canvas, {
    type: "bar",
    data: {
      labels: skills.length ? skills : ["No Required Skills Specified"],
      datasets: [{
        label: "Candidate Pool Coverage (%)",
        data: percentages.length ? percentages : [0],
        backgroundColor: "rgba(99, 102, 241, 0.8)",
        borderColor: "#6366F1",
        borderWidth: 1.5,
        borderRadius: 6,
        hoverBackgroundColor: "rgba(79, 70, 229, 0.95)",
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `Coverage: ${ctx.parsed.y}% (${counts[ctx.dataIndex] || 0} candidates)`
          }
        }
      },
      scales: {
        y: {
          min: 0,
          max: 100,
          ticks: { callback: (val) => `${val}%`, font: { family: 'Inter', size: 11 } },
          grid: { color: "#F1F5F9" }
        },
        x: {
          ticks: { font: { family: 'Inter', size: 12, weight: '600' } },
          grid: { display: false }
        }
      }
    }
  });
}

// Render Ranked Candidates Table
function renderScreenedCandidatesTable(candidates) {
  const tbody = document.getElementById("tbody-screened-candidates");
  if (!tbody) return;
  tbody.innerHTML = "";

  const filter = document.getElementById("screening-filter-rec")?.value || "all";

  let filtered = candidates;
  if (filter === "shortlisted_only") {
    filtered = candidates.filter(c => {
      const rec = (c.recommendation || "").toLowerCase();
      return rec.includes("shortlisted");
    });
  } else if (filter !== "all") {
    filtered = candidates.filter(c => {
      const recNorm = (c.recommendation || "").toLowerCase().replace(/\s+/g, "_");
      return recNorm === filter;
    });
  }

  if (!filtered || filtered.length === 0) {
    tbody.innerHTML = `
      <tr class="empty-state-row">
        <td colspan="8">
          <div class="empty-state">
            <span class="empty-icon">🔍</span>
            <p>No candidates match the selected filter criteria.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  filtered.forEach((c) => {
    const rankNum = c.rank || 1;
    const rankClass = rankNum === 1 ? "rank-1" : rankNum === 2 ? "rank-2" : rankNum === 3 ? "rank-3" : "";
    const rankMedal = rankNum === 1 ? "🥇" : rankNum === 2 ? "🥈" : rankNum === 3 ? "🥉" : `#${rankNum}`;

    let scoreColor = "#EF4444";
    if (c.overall_score >= 80) scoreColor = "#10B981";
    else if (c.overall_score >= 65) scoreColor = "#6366F1";
    else if (c.overall_score >= 50) scoreColor = "#F59E0B";

    // Format matched skills pills (show first 3 + counter)
    const matched = c.matched_skills || c.matched_required_skills || [];
    const matchedHtml = matched.length > 0
      ? matched.slice(0, 3).map(s => `<span class="skill-pill skill-pill-match">✓ ${s}</span>`).join("") +
      (matched.length > 3 ? `<span class="skill-pill skill-pill-extra">+${matched.length - 3}</span>` : "")
      : '<span style="color:var(--text-muted); font-size:12px;">None</span>';

    // Format missing skills pills (show first 2 + counter)
    const missing = c.missing_skills || c.missing_required_skills || [];
    const missingHtml = missing.length > 0
      ? missing.slice(0, 2).map(s => `<span class="skill-pill skill-pill-missing">✕ ${s}</span>`).join("") +
      (missing.length > 2 ? `<span class="skill-pill skill-pill-extra">+${missing.length - 2}</span>` : "")
      : '<span style="color:#059669; font-size:12px; font-weight:600;">✓ 100% Fit</span>';

    const candName = c.candidate_name || c.full_name || "Candidate";
    const recClass = (c.recommendation || "").toLowerCase().replace(/\s+/g, "_");
    const recText = c.recommendation_badge || c.recommendation || "Evaluated";

    const tr = document.createElement("tr");
    tr.className = "screening-candidate-row";
    tr.innerHTML = `
      <td>
        <span class="rank-badge ${rankClass}" title="Rank #${rankNum}">${rankMedal}</span>
      </td>
      <td class="name-col">
        <div style="font-weight:700; color:var(--text-primary);">${candName}</div>
        <div style="font-size:12px; color:var(--text-secondary);">${c.email}</div>
      </td>
      <td>
        <div class="score-badge-wrap">
          <span style="font-weight:800; font-family:'JetBrains Mono', monospace; font-size:15px; color:${scoreColor};">${c.overall_score}%</span>
          <div class="score-bar-mini">
            <div class="score-bar-mini-fill" style="width:${c.overall_score}%; background:${scoreColor};"></div>
          </div>
        </div>
      </td>
      <td>
        <span class="mono" style="font-weight:600;">${c.experience_years} yrs</span>
        <span style="font-size:11px; color:var(--text-muted); display:block;">req: ${c.required_experience_years || 0} yrs</span>
      </td>
      <td style="max-width:200px;">${matchedHtml}</td>
      <td style="max-width:180px;">${missingHtml}</td>
      <td>
        <span class="badge badge-rec-${recClass}">
          <span class="badge-dot"></span>${recText}
        </span>
      </td>
      <td style="text-align:right; white-space:nowrap;">
        <button class="btn btn-ghost" data-action="view-screening-detail" data-candidate-id="${c.candidate_id}" style="font-size:12px; padding:6px 10px;">
          🔍 Breakdown
        </button>
        <button class="btn btn-primary" data-action="schedule-screened" data-candidate-id="${c.candidate_id}" style="font-size:12px; padding:6px 10px;">
          📅 Schedule
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// Table action clicks (Breakdown modal & Schedule)
document.getElementById("table-screened-candidates")?.addEventListener("click", (e) => {
  const breakdownBtn = e.target.closest("[data-action='view-screening-detail']");
  if (breakdownBtn) {
    const candId = Number(breakdownBtn.dataset.candidateId);
    openScreeningDetailModal(candId);
    return;
  }

  const scheduleBtn = e.target.closest("[data-action='schedule-screened']");
  if (scheduleBtn) {
    const candId = Number(scheduleBtn.dataset.candidateId);
    const cand = currentScreeningResults.find(c => c.candidate_id === candId);
    scheduleFromScreening(candId, cand ? cand.full_name : "");
  }
});

// Modal Open Handler
function openScreeningDetailModal(candidateId) {
  const candidate = currentScreeningResults.find(c => c.candidate_id === candidateId);
  if (!candidate) return;

  const modal = document.getElementById("screening-detail-modal");
  if (!modal) return;

  // Header & Score
  const candName = candidate.candidate_name || candidate.full_name || "Candidate";
  document.getElementById("modal-screen-candidate-name").textContent = candName;
  document.getElementById("modal-screen-candidate-email").textContent = `${candidate.email} • ${candidate.phone || 'No phone'} • ${candidate.experience_years} yrs exp`;
  document.getElementById("modal-screen-score-text").textContent = `${candidate.overall_score}%`;
  document.getElementById("modal-screen-rank-text").textContent = `#${candidate.rank}`;

  // Recommendation Badge
  const recBadgeEl = document.getElementById("modal-screen-rec-badge");
  if (recBadgeEl) {
    const recClass = (candidate.recommendation || "").toLowerCase().replace(/\s+/g, "_");
    const recText = candidate.recommendation_badge || candidate.recommendation || "Evaluated";
    recBadgeEl.innerHTML = `<span class="badge badge-rec-${recClass}"><span class="badge-dot"></span>${recText}</span>`;
  }

  // Component Bars
  const breakdown = candidate.score_breakdown || {};
  const reqPct = breakdown.required_skills_fit || 0;
  const prefPct = breakdown.preferred_skills_fit || 0;
  const expPct = breakdown.experience_fit || 0;
  const depthPct = breakdown.skill_depth_fit || 0;

  document.getElementById("modal-bar-req-score").textContent = `${reqPct}%`;
  document.getElementById("modal-bar-req-fill").style.width = `${reqPct}%`;

  document.getElementById("modal-bar-pref-score").textContent = `${prefPct}%`;
  document.getElementById("modal-bar-pref-fill").style.width = `${prefPct}%`;

  document.getElementById("modal-bar-exp-score").textContent = `${expPct}%`;
  document.getElementById("modal-bar-exp-fill").style.width = `${expPct}%`;

  document.getElementById("modal-bar-depth-score").textContent = `${depthPct}%`;
  document.getElementById("modal-bar-depth-fill").style.width = `${depthPct}%`;

  // Matched Skills Wrap
  const matchedWrap = document.getElementById("modal-matched-skills-wrap");
  if (matchedWrap) {
    const matched = candidate.matched_skills || candidate.matched_required_skills || [];
    matchedWrap.innerHTML = matched.length > 0
      ? matched.map(s => `<span class="skill-pill skill-pill-match">✓ ${s}</span>`).join("")
      : '<span style="color:var(--text-muted); font-size:12px;">None matched</span>';
  }

  // Missing Skills Wrap
  const missingWrap = document.getElementById("modal-missing-skills-wrap");
  if (missingWrap) {
    const missing = candidate.missing_skills || candidate.missing_required_skills || [];
    missingWrap.innerHTML = missing.length > 0
      ? missing.map(s => `<span class="skill-pill skill-pill-missing">✕ ${s}</span>`).join("")
      : '<span style="color:#059669; font-size:12px; font-weight:600;">✓ Complete required skill match</span>';
  }

  // All Categorized Skills
  const allSkillsWrap = document.getElementById("modal-all-skills-wrap");
  if (allSkillsWrap) {
    const cats = candidate.skills_by_category || {};
    const catKeys = Object.keys(cats);
    if (catKeys.length > 0) {
      allSkillsWrap.innerHTML = catKeys.map(cat => `
        <div>
          <span style="font-weight:600; color:var(--text-primary);">${cat}:</span>
          ${cats[cat].map(s => `<span class="skill-pill skill-pill-extra">${s}</span>`).join("")}
        </div>
      `).join("");
    } else {
      allSkillsWrap.innerHTML = '<span style="color:var(--text-muted);">No categorized skills extracted</span>';
    }
  }

  // AI Reasoning
  const reasonEl = document.getElementById("modal-screen-reason-text");
  if (reasonEl) {
    reasonEl.textContent = candidate.reasoning || candidate.ai_reasoning || "Evaluation completed using NLP skill boundary detection.";
  }

  // Modal Schedule Button
  const schedBtn = document.getElementById("modal-btn-schedule");
  if (schedBtn) {
    schedBtn.onclick = () => {
      scheduleFromScreening(candidate.candidate_id, candName);
    };
  }

  modal.style.display = "flex";
}

// 1-Click Schedule Action from Candidate Card or Modal
function scheduleFromScreening(candidateId, candidateName) {
  // Close screening modal if open
  const modal = document.getElementById("screening-detail-modal");
  if (modal) modal.style.display = "none";

  // Switch view to interviews
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === "interviews"));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-interviews"));

  // Ensure interview form panel is open
  const formPanel = document.getElementById("form-panel-interview");
  if (formPanel && formPanel.style.display === "none") {
    formPanel.style.display = "block";
  }

  // Pre-select candidate
  const candSelect = document.getElementById("select-candidate");
  if (candSelect) {
    candSelect.value = String(candidateId);
  }

  // Pre-populate round name
  const roundInput = document.querySelector("#form-interview input[name='round_name']");
  if (roundInput && !roundInput.value) {
    roundInput.value = "Technical Round 1 (Screened Candidate)";
  }

  if (formPanel) {
    formPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  showToast(`Candidate selected! Please pick an interviewer and set the schedule.`);
}

// Close Screening Detail Modal
document.getElementById("btn-close-screening-modal")?.addEventListener("click", () => {
  document.getElementById("screening-detail-modal").style.display = "none";
});
document.getElementById("modal-btn-close")?.addEventListener("click", () => {
  document.getElementById("screening-detail-modal").style.display = "none";
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const modal = document.getElementById("screening-detail-modal");
    if (modal && modal.style.display === "flex") {
      modal.style.display = "none";
    }
  }
});

// Criteria Form Submit
document.getElementById("form-screening-criteria")?.addEventListener("submit", (e) => {
  e.preventDefault();
  runCandidateScreening();
});

// Top button trigger
document.getElementById("btn-run-screening-top")?.addEventListener("click", () => {
  runCandidateScreening();
});

// Recommendation filter dropdown
document.getElementById("screening-filter-rec")?.addEventListener("change", () => {
  renderScreenedCandidatesTable(currentScreeningResults);
});

// Interactive NLP Skill Tester Tool
const btnToggleNlp = document.getElementById("btn-toggle-nlp-tester");
const btnCloseNlp = document.getElementById("btn-close-nlp-tester");
const panelNlp = document.getElementById("panel-nlp-tester");
const btnFillSample = document.getElementById("btn-fill-sample-resume");
const btnExtractSkills = document.getElementById("btn-extract-skills-test");

btnToggleNlp?.addEventListener("click", () => {
  if (!panelNlp) return;
  panelNlp.style.display = panelNlp.style.display === "none" ? "block" : "none";
  if (panelNlp.style.display === "block") {
    panelNlp.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});

btnCloseNlp?.addEventListener("click", () => {
  if (panelNlp) panelNlp.style.display = "none";
});

btnFillSample?.addEventListener("click", () => {
  const textarea = document.getElementById("nlp-test-text");
  if (textarea) {
    textarea.value = `Senior Full Stack Software Engineer with 6+ years of experience designing and deploying high-performance microservices and cloud architectures.
Key Expertise:
• Languages & Web: Python, FastAPI, Django, JavaScript, TypeScript, React, HTML5, CSS3, Tailwind CSS.
• Databases & Caching: PostgreSQL, MongoDB, Redis, SQLAlchemy, relational query optimization.
• Cloud & DevOps: AWS (EC2, S3, RDS, Lambda), Docker, Kubernetes, Terraform, CI/CD with GitHub Actions, Linux.
• AI & Data: Machine Learning, NLP skill parsing, PyTorch, Large Language Models (LLMs), Vector Databases.
• Architecture: Microservices, RESTful APIs, Event-Driven Architecture, Unit Testing (Pytest, Jest).`;
  }
});

btnExtractSkills?.addEventListener("click", async () => {
  const textarea = document.getElementById("nlp-test-text");
  const text = textarea ? textarea.value.trim() : "";
  if (!text) {
    showToast("Please enter or load resume text to extract skills", "warning");
    return;
  }

  const origBtnText = btnExtractSkills.innerHTML;
  btnExtractSkills.disabled = true;
  btnExtractSkills.innerHTML = "<span>⏳</span> Extracting with NLP…";

  try {
    const data = await api("/screening/extract-skills", {
      method: "POST",
      body: JSON.stringify({ text }),
    });

    const resultBox = document.getElementById("nlp-extract-results");
    const output = document.getElementById("nlp-categorized-skills-output");

    if (resultBox && output) {
      const byCat = data.skills_by_category || {};
      const catKeys = Object.keys(byCat);

      if (catKeys.length === 0) {
        output.innerHTML = '<div style="color:var(--text-muted);">No matching technical skills detected in text.</div>';
      } else {
        output.innerHTML = catKeys.map(cat => `
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <strong style="min-width:180px; font-size:12px; color:var(--text-primary);">${cat}:</strong>
            <div style="display:flex; flex-wrap:wrap; gap:4px;">
              ${byCat[cat].map(s => `<span class="skill-pill skill-pill-match">✓ ${s}</span>`).join("")}
            </div>
          </div>
        `).join("");
      }

      resultBox.style.display = "block";
      resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
      showToast(`Extracted ${data.skills_count} skills (${data.experience_years} yrs exp detected)!`);
    }
  } catch (err) {
    showToast(`Skill extraction failed: ${err.message}`, "error");
  } finally {
    btnExtractSkills.disabled = false;
    btnExtractSkills.innerHTML = origBtnText;
  }
});

// ============================================================
// AI RESUME ANALYZER (Client-Side Logic)
// ============================================================

let currentSelectedResumeFile = null;
let currentAnalysisId = null;
let isAnalyzerInitialized = false;

function initResumeAnalyzerView() {
  if (isAnalyzerInitialized) return;
  isAnalyzerInitialized = true;

  const dropzone = document.getElementById("resume-dropzone");
  const fileInput = document.getElementById("resume-file-input");
  const browseBtn = document.getElementById("btn-browse-file");
  const removeBtn = document.getElementById("btn-remove-file");
  const analyzeBtn = document.getElementById("btn-analyze-resume");
  const sampleBtn = document.getElementById("btn-load-sample-resume");
  const downloadPdfBtn = document.getElementById("btn-download-pdf-report");

  // Browse button opens file picker
  browseBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput?.click();
  });

  dropzone?.addEventListener("click", () => {
    fileInput?.click();
  });

  // Drag and drop listeners
  dropzone?.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone?.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone?.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleResumeFileSelect(e.dataTransfer.files[0]);
    }
  });

  // File input change
  fileInput?.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleResumeFileSelect(e.target.files[0]);
    }
  });

  // Remove selected file
  removeBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    currentSelectedResumeFile = null;
    if (fileInput) fileInput.value = "";
    const badge = document.getElementById("uploaded-file-badge");
    if (badge) badge.style.display = "none";
    showToast("Resume removed. Select or drop another PDF.", "warning");
  });

  // Analyze Resume button
  analyzeBtn?.addEventListener("click", () => {
    runResumeAnalysis();
  });

  // Load sample button
  sampleBtn?.addEventListener("click", () => {
    loadSampleResumeAnalysis();
  });

  // Download PDF Report button
  downloadPdfBtn?.addEventListener("click", () => {
    downloadResumeReportPdf();
  });
}

function handleResumeFileSelect(file) {
  if (!file) return;
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) {
    showToast("Please select or drop a valid PDF file (.pdf)", "error");
    return;
  }

  currentSelectedResumeFile = file;
  const badge = document.getElementById("uploaded-file-badge");
  const nameEl = document.getElementById("uploaded-file-name");
  const sizeEl = document.getElementById("uploaded-file-size");

  if (badge && nameEl && sizeEl) {
    nameEl.textContent = file.name;
    const sizeKb = (file.size / 1024).toFixed(1);
    sizeEl.textContent = `${sizeKb} KB • PDF Document ready for analysis`;
    badge.style.display = "flex";
  }

  showToast(`Loaded "${file.name}" — Click "Analyze Resume" to process!`, "success");
}

async function runResumeAnalysis() {
  if (!currentSelectedResumeFile) {
    showToast("Please select or drop a PDF resume first, or click 'Load Sample Resume'", "warning");
    return;
  }

  const analyzeBtn = document.getElementById("btn-analyze-resume");
  const spinner = document.getElementById("analyze-spinner");
  const btnIcon = document.getElementById("analyze-btn-icon");
  const btnText = document.getElementById("analyze-btn-text");

  if (analyzeBtn) analyzeBtn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (btnIcon) btnIcon.style.display = "none";
  if (btnText) btnText.textContent = "Analyzing Resume with AI & NLP...";

  try {
    const formData = new FormData();
    formData.append("file", currentSelectedResumeFile);

    const token = localStorage.getItem("auth_token");
    const headers = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const resp = await fetch(`${API_BASE}/analyzer/upload-and-analyze`, {
      method: "POST",
      headers: headers,
      body: formData,
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.detail || `Upload failed with status ${resp.status}`);
    }

    const data = await resp.json();
    renderAnalyzerResults(data);
    showToast(`Analysis Complete! Resume Score: ${data.overall_score}/100`, "success");

  } catch (err) {
    showToast(`Resume Analysis failed: ${err.message}`, "error");
  } finally {
    if (analyzeBtn) analyzeBtn.disabled = false;
    if (spinner) spinner.style.display = "none";
    if (btnIcon) btnIcon.style.display = "inline";
    if (btnText) btnText.textContent = "Analyze Resume";
  }
}

async function loadSampleResumeAnalysis() {
  const analyzeBtn = document.getElementById("btn-analyze-resume");
  const spinner = document.getElementById("analyze-spinner");
  const btnIcon = document.getElementById("analyze-btn-icon");
  const btnText = document.getElementById("analyze-btn-text");

  if (analyzeBtn) analyzeBtn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (btnIcon) btnIcon.style.display = "none";
  if (btnText) btnText.textContent = "Loading Sample Resume Analysis...";

  try {
    const data = await api("/analyzer/sample-analysis");

    // Display sample file badge
    const badge = document.getElementById("uploaded-file-badge");
    const nameEl = document.getElementById("uploaded-file-name");
    const sizeEl = document.getElementById("uploaded-file-size");
    if (badge && nameEl && sizeEl) {
      nameEl.textContent = data.filename || "Aditya_Verma_Data_Analyst_Resume.pdf";
      sizeEl.textContent = "Sample Data Analyst Resume Profile (Demo)";
      badge.style.display = "flex";
    }

    renderAnalyzerResults(data);
    showToast(`Loaded Sample Resume Analysis! Score: ${data.overall_score}/100`, "success");

  } catch (err) {
    showToast(`Failed to load sample: ${err.message}`, "error");
  } finally {
    if (analyzeBtn) analyzeBtn.disabled = false;
    if (spinner) spinner.style.display = "none";
    if (btnIcon) btnIcon.style.display = "inline";
    if (btnText) btnText.textContent = "Analyze Resume";
  }
}

function renderAnalyzerResults(data) {
  if (!data) return;
  currentAnalysisId = data.id || null;

  const resultsWrap = document.getElementById("analyzer-results-wrap");
  if (resultsWrap) resultsWrap.style.display = "block";

  // Section 3: Resume Score & Metrics
  const overallScoreEl = document.getElementById("res-overall-score");
  const strengthBadge = document.getElementById("res-strength-badge");
  const atsScoreEl = document.getElementById("res-ats-score");
  const targetRoleEl = document.getElementById("res-target-role");
  const candNameEl = document.getElementById("res-candidate-name");
  const filenameEl = document.getElementById("res-filename");

  if (overallScoreEl) overallScoreEl.textContent = data.overall_score;
  if (strengthBadge) {
    strengthBadge.textContent = data.strength || "Good";
    strengthBadge.className = `badge ${data.overall_score >= 85 ? "badge-completed" : "badge-strength"}`;
  }
  if (atsScoreEl) atsScoreEl.textContent = `${data.ats_score}%`;
  if (targetRoleEl) targetRoleEl.textContent = data.target_role || "Data Analyst";
  if (candNameEl) candNameEl.textContent = data.candidate_name || "Candidate";
  if (filenameEl) filenameEl.textContent = data.filename || "resume.pdf";

  // Skills Found & Missing
  const skillsFoundCount = document.getElementById("res-skills-found-count");
  const skillsFoundWrap = document.getElementById("res-skills-found");
  const skillsMissingCount = document.getElementById("res-skills-missing-count");
  const skillsMissingWrap = document.getElementById("res-skills-missing");

  const found = data.skills_found || [];
  const missing = data.missing_skills || [];

  if (skillsFoundCount) skillsFoundCount.textContent = `${found.length} Detected`;
  if (skillsFoundWrap) {
    if (found.length === 0) {
      skillsFoundWrap.innerHTML = '<span style="color:var(--text-muted); font-size:12px;">No skills automatically recognized.</span>';
    } else {
      skillsFoundWrap.innerHTML = found.map(s => `<span class="skill-pill skill-pill-match">✔ ${s}</span>`).join("");
    }
  }

  if (skillsMissingCount) skillsMissingCount.textContent = `${missing.length} Gaps`;
  if (skillsMissingWrap) {
    if (missing.length === 0) {
      skillsMissingWrap.innerHTML = '<span style="color:#059669; font-size:12px;">No major benchmark skill gaps!</span>';
    } else {
      skillsMissingWrap.innerHTML = missing.map(s => `<span class="skill-pill skill-pill-missing">✘ ${s}</span>`).join("");
    }
  }

  // Section 4: AI Suggestions
  const suggestionsList = document.getElementById("res-suggestions-list");
  if (suggestionsList) {
    const sugs = data.suggestions || [];
    suggestionsList.innerHTML = sugs.map(sug => `
      <div class="suggestion-item">
        <span class="suggestion-icon">💡</span>
        <div>${sug}</div>
      </div>
    `).join("");
  }

  // Section 5: Resume Breakdown
  const b = data.breakdown || {};
  const techScore = b.technical_skills_score || 80;
  const projScore = b.projects_score || 85;
  const eduScore = b.education_score || 90;
  const expScore = b.experience_score || 70;
  const atsScore = b.ats_score || data.ats_score || 88;

  const setBar = (valId, barId, score) => {
    const valEl = document.getElementById(valId);
    const barEl = document.getElementById(barId);
    if (valEl) valEl.textContent = `${score}%`;
    if (barEl) {
      barEl.style.width = "0%";
      setTimeout(() => { barEl.style.width = `${score}%`; }, 100);
    }
  };

  setBar("val-tech-score", "bar-tech-score", techScore);
  setBar("val-proj-score", "bar-proj-score", projScore);
  setBar("val-edu-score", "bar-edu-score", eduScore);
  setBar("val-exp-score", "bar-exp-score", expScore);
  setBar("val-ats-score", "bar-ats-score", atsScore);

  // Section 6: AI Recommendation
  const strengthsList = document.getElementById("res-strengths-list");
  const weaknessesList = document.getElementById("res-weaknesses-list");
  const finalRecEl = document.getElementById("res-final-rec");

  const st = data.strengths || [];
  const wk = data.weaknesses || [];

  if (strengthsList) {
    strengthsList.innerHTML = st.map(item => `<li>${item}</li>`).join("");
  }
  if (weaknessesList) {
    weaknessesList.innerHTML = wk.map(item => `<li>${item}</li>`).join("");
  }
  if (finalRecEl) {
    finalRecEl.textContent = data.recommendation || "Suitable for Fresher Data Analyst Role";
  }

  // Scroll smoothly to results
  resultsWrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

function downloadResumeReportPdf() {
  if (!currentAnalysisId) {
    showToast("Please analyze a resume first to download its report.", "warning");
    return;
  }
  showToast("Generating and downloading AI Resume Report PDF...", "success");
  const downloadUrl = `${API_BASE}/analyzer/report/${currentAnalysisId}/pdf`;
  window.open(downloadUrl, "_blank");
}


// ============================================================
// EMAIL NOTIFICATIONS & AUDIT LOGS
// ============================================================

let allNotificationLogs = [];
let currentNotificationFilter = "all";

async function loadNotifications(filterType = "all") {
  currentNotificationFilter = filterType;
  try {
    // 1. Fetch SMTP status
    const smtpInfo = await api("/notifications/smtp-status").catch(() => null);
    if (smtpInfo) {
      const badgeText = document.getElementById("smtp-status-text");
      const badgeEl = document.getElementById("smtp-status-badge");
      if (badgeText && badgeEl) {
        if (smtpInfo.configured) {
          badgeText.textContent = `Gmail SMTP: Live (${smtpInfo.email_from})`;
          badgeEl.style.borderColor = "#10B981";
          badgeEl.style.color = "#047857";
          badgeEl.style.background = "#ECFDF5";
        } else {
          badgeText.textContent = `Gmail SMTP: Simulated (Dev Mode)`;
          badgeEl.style.borderColor = "#F59E0B";
          badgeEl.style.color = "#B45309";
          badgeEl.style.background = "#FFFBEB";
        }
      }
    }

    // 2. Fetch stats
    const stats = await api("/notifications/stats").catch(() => null);
    if (stats) {
      const elTotal = document.getElementById("stat-notif-total");
      const elSent = document.getElementById("stat-notif-sent");
      const elReminders = document.getElementById("stat-notif-reminders");
      const elRate = document.getElementById("stat-notif-rate");
      if (elTotal) elTotal.textContent = stats.total || 0;
      if (elSent) elSent.textContent = stats.sent || 0;
      if (elReminders) elReminders.textContent = stats.reminders || 0;
      if (elRate) elRate.textContent = stats.success_rate || "100%";
    }

    // 3. Fetch notifications
    const logs = await api("/notifications/?limit=150");
    allNotificationLogs = logs || [];
    renderNotificationsTable();
  } catch (err) {
    console.error("Failed to load notifications:", err);
  }
}

function filterNotifications(filterType, btn) {
  currentNotificationFilter = filterType;
  document.querySelectorAll(".filter-chips .chip").forEach((b) => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  renderNotificationsTable();
}

function formatNotificationTypeBadge(type) {
  const map = {
    interview_scheduled: { label: "📅 Scheduled", color: "#4F46E5", bg: "#EEF2FF" },
    interview_reminder: { label: "⏰ 24h Reminder", color: "#059669", bg: "#ECFDF5" },
    interview_rescheduled: { label: "⚠️ Rescheduled", color: "#D97706", bg: "#FFFBEB" },
    interview_cancelled: { label: "🚫 Cancelled", color: "#DC2626", bg: "#FEF2F2" },
    status_update: { label: "🏷️ Status Update", color: "#2563EB", bg: "#EFF6FF" },
    hr_new_candidate: { label: "📢 HR Alert", color: "#7C3AED", bg: "#F5F3FF" },
    hr_event: { label: "📢 HR Event", color: "#4B5563", bg: "#F3F4F6" },
    test_email: { label: "🧪 Test Email", color: "#0D9488", bg: "#F0FDFA" },
  };
  const item = map[type] || { label: type, color: "#64748B", bg: "#F1F5F9" };
  return `<span style="display:inline-block; font-size:11px; font-weight:700; color:${item.color}; background:${item.bg}; padding:3px 8px; border-radius:12px;">${item.label}</span>`;
}

function renderNotificationsTable() {
  const tbody = document.getElementById("table-notifications");
  if (!tbody) return;
  tbody.innerHTML = "";

  const query = (document.getElementById("search-notifications")?.value || "").toLowerCase().trim();

  let filtered = allNotificationLogs;
  if (currentNotificationFilter !== "all") {
    if (currentNotificationFilter === "failed") {
      filtered = filtered.filter((l) => l.status === "failed");
    } else {
      filtered = filtered.filter((l) => l.notification_type === currentNotificationFilter);
    }
  }

  if (query) {
    filtered = filtered.filter(
      (l) =>
        (l.recipient || "").toLowerCase().includes(query) ||
        (l.subject || "").toLowerCase().includes(query) ||
        (l.notification_type || "").toLowerCase().includes(query)
    );
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr class="empty-state-row"><td colspan="7">
        <div class="empty-state" style="padding:36px 0;">
          <span class="empty-icon">📧</span>
          <p>No email logs found matching this filter.</p>
        </div>
      </td></tr>
    `;
    return;
  }

  filtered.forEach((log) => {
    const tr = document.createElement("tr");

    const statusPill =
      log.status === "sent"
        ? `<span class="badge badge-sent"><span class="badge-dot"></span>Sent</span>`
        : log.status === "failed"
          ? `<span class="badge badge-failed" title="${log.error_message || 'Delivery error'}"><span class="badge-dot"></span>Failed</span>`
          : `<span class="badge badge-pending"><span class="badge-dot"></span>Pending</span>`;

    const retryBtn =
      log.status === "failed"
        ? `<button class="btn btn-ghost" onclick="retryNotification(${log.id})" style="padding:4px 8px; font-size:11px; color:#DC2626;" title="Retry delivery">🔄 Retry</button>`
        : "";

    tr.innerHTML = `
      <td class="id-col">#${log.id}</td>
      <td class="mono-col" style="font-weight:600;">${log.recipient}</td>
      <td>${formatNotificationTypeBadge(log.notification_type)}</td>
      <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${log.subject}">
        ${log.subject}
      </td>
      <td>${statusPill}</td>
      <td class="mono-col" style="font-size:12px;">${fmtDate(log.sent_at || log.created_at)}</td>
      <td class="actions-col" style="display:flex; gap:6px;">
        <button class="btn btn-ghost" onclick="openEmailPreviewModal(${log.id})" style="padding:4px 8px; font-size:11px;">👁️ Preview</button>
        ${retryBtn}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function searchNotificationsTable() {
  renderNotificationsTable();
}

// ============ EMAIL PREVIEW MODAL ============

async function openEmailPreviewModal(logId) {
  try {
    const log = await api(`/notifications/${logId}`);
    if (!log) return;

    document.getElementById("email-preview-modal").style.display = "flex";
    document.getElementById("preview-modal-recipient").textContent = log.recipient;
    document.getElementById("preview-modal-subject").textContent = log.subject;
    document.getElementById("preview-modal-type").innerHTML = formatNotificationTypeBadge(log.notification_type);
    document.getElementById("preview-modal-status").innerHTML = statusBadge(log.status);
    document.getElementById("preview-modal-time").textContent = fmtDate(log.sent_at || log.created_at);

    const errorWrap = document.getElementById("preview-modal-error-wrap");
    const errorEl = document.getElementById("preview-modal-error");
    if (log.error_message) {
      errorWrap.style.display = "block";
      errorEl.textContent = log.error_message;
    } else {
      errorWrap.style.display = "none";
    }

    const retryBtn = document.getElementById("preview-modal-btn-retry");
    if (log.status === "failed") {
      retryBtn.style.display = "inline-flex";
      retryBtn.onclick = () => retryNotification(log.id);
    } else {
      retryBtn.style.display = "none";
    }

    // Render HTML in sandboxed container
    const bodyContainer = document.getElementById("preview-modal-body-container");
    bodyContainer.innerHTML = log.body_html || "<p style='padding:20px; color:#64748B;'>No HTML preview available.</p>";
  } catch (err) {
    showToast(err.message, "error");
  }
}

function closeEmailPreviewModal() {
  document.getElementById("email-preview-modal").style.display = "none";
}

async function retryNotification(logId) {
  try {
    showToast("Retrying email dispatch…");
    const updated = await api(`/notifications/${logId}/retry`, { method: "POST" });
    if (updated.status === "sent") {
      showToast("Notification redelivered successfully! ✅");
    } else {
      showToast(`Retry failed: ${updated.error_message}`, "error");
    }
    closeEmailPreviewModal();
    await loadNotifications(currentNotificationFilter);
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ============ TEST EMAIL MODAL ============

function openTestEmailModal() {
  document.getElementById("test-email-modal").style.display = "flex";
  const user = JSON.parse(localStorage.getItem("auth_user") || "{}");
  const emailInput = document.getElementById("test-email-input");
  if (emailInput && !emailInput.value && user.email) {
    emailInput.value = user.email;
  }
}

function closeTestEmailModal() {
  document.getElementById("test-email-modal").style.display = "none";
  document.getElementById("form-test-email")?.reset();
}

document.getElementById("form-test-email")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("btn-submit-test-email");
  const origText = btn.textContent;
  try {
    btn.disabled = true;
    btn.textContent = "Sending test email…";
    const payload = formToJson(e.target);
    await api("/notifications/test", { method: "POST", body: JSON.stringify(payload) });
    showToast("Test email sent successfully via Gmail SMTP! ✉️");
    closeTestEmailModal();
    await loadNotifications("all");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
});

// ============ RESCHEDULE MODAL ============

async function openRescheduleModal(interviewId) {
  const modal = document.getElementById("reschedule-modal");
  if (!modal) return;
  modal.style.display = "flex";

  const errBox = document.getElementById("reschedule-modal-error");
  if (errBox) {
    errBox.style.display = "none";
    errBox.textContent = "";
  }
  const btn = document.getElementById("btn-confirm-reschedule");
  if (btn) {
    btn.disabled = false;
    btn.textContent = "Confirm Reschedule";
  }
  const cancelBtn = document.getElementById("btn-cancel-reschedule");
  if (cancelBtn) cancelBtn.disabled = false;

  // Retrieve interview details from cache or fetch from API
  let iv = (window.cachedInterviews || []).find((x) => String(x.id) === String(interviewId));
  if (!iv) {
    try {
      iv = await api(`/interviews/${interviewId}`);
    } catch {
      iv = null;
    }
  }

  const candidate = (window.cachedCandidates || []).find((c) => iv && c.id === iv.candidate_id);
  const job = (window.cachedJobs || []).find((j) => iv && j.id === iv.job_id);

  document.getElementById("reschedule-interview-id").value = interviewId;

  const sub = document.getElementById("reschedule-modal-subtitle");
  if (sub) {
    const rName = iv && iv.round_name ? `"${iv.round_name}"` : `Interview #${interviewId}`;
    sub.textContent = `Reschedule ${rName}. Candidate will receive an updated email with new timing and details.`;
  }

  // Pre-fill read-only fields
  const candNameInput = document.getElementById("reschedule-candidate-name");
  if (candNameInput) candNameInput.value = candidate ? candidate.full_name : (iv?.candidate?.full_name || "—");

  const candEmailInput = document.getElementById("reschedule-candidate-email");
  if (candEmailInput) candEmailInput.value = candidate ? candidate.email : (iv?.candidate?.email || "—");

  const jobInput = document.getElementById("reschedule-job-title");
  if (jobInput) jobInput.value = job ? job.title : (iv?.job?.title || "—");

  const currentDtInput = document.getElementById("reschedule-current-datetime");
  if (currentDtInput) currentDtInput.value = iv && iv.scheduled_at ? fmtDate(iv.scheduled_at) : "—";

  // Pre-fill editable fields
  const roundInput = document.getElementById("reschedule-round-name");
  if (roundInput) roundInput.value = iv && iv.round_name ? iv.round_name : "";

  // Populate Interviewers dropdown
  const interviewerSelect = document.getElementById("reschedule-interviewer-id");
  if (interviewerSelect) {
    const intrList = window.cachedInterviewers || [];
    if (intrList.length === 0) {
      interviewerSelect.innerHTML = `<option value="">Default Interviewer</option>`;
    } else {
      interviewerSelect.innerHTML = intrList
        .map(
          (intr) =>
            `<option value="${intr.id}" ${iv && iv.interviewer_id === intr.id ? "selected" : ""}>${intr.full_name} (${intr.title || "Interviewer"})</option>`
        )
        .join("");
    }
  }

  // Pre-fill Date and Time
  const dateInput = document.getElementById("reschedule-new-date");
  const timeInput = document.getElementById("reschedule-new-time");
  if (iv && iv.scheduled_at) {
    try {
      const d = new Date(iv.scheduled_at);
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      const hh = String(d.getHours()).padStart(2, "0");
      const min = String(d.getMinutes()).padStart(2, "0");
      if (dateInput) dateInput.value = `${yyyy}-${mm}-${dd}`;
      if (timeInput) timeInput.value = `${hh}:${min}`;
    } catch {
      if (dateInput) dateInput.value = "";
      if (timeInput) timeInput.value = "";
    }
  }

  if (dateInput) {
    const todayStr = new Date().toISOString().split("T")[0];
    dateInput.min = todayStr;
  }

  const durInput = document.getElementById("reschedule-duration");
  if (durInput) durInput.value = iv && iv.duration_minutes ? iv.duration_minutes : 45;

  const linkInput = document.getElementById("reschedule-meeting-link");
  if (linkInput) linkInput.value = iv && iv.meeting_link ? iv.meeting_link : "";

  const reasonInput = document.getElementById("reschedule-reason");
  if (reasonInput) reasonInput.value = "";
}

function closeRescheduleModal() {
  const modal = document.getElementById("reschedule-modal");
  if (modal) modal.style.display = "none";
  document.getElementById("form-reschedule")?.reset();
  const errBox = document.getElementById("reschedule-modal-error");
  if (errBox) {
    errBox.style.display = "none";
    errBox.textContent = "";
  }
  const btn = document.getElementById("btn-confirm-reschedule");
  if (btn) {
    btn.disabled = false;
    btn.textContent = "Confirm Reschedule";
  }
}

let isRescheduling = false;

document.getElementById("form-reschedule")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (isRescheduling) return;

  const ivId = document.getElementById("reschedule-interview-id").value;
  const btn = document.getElementById("btn-confirm-reschedule");
  const cancelBtn = document.getElementById("btn-cancel-reschedule");
  const errBox = document.getElementById("reschedule-modal-error");

  const newDate = document.getElementById("reschedule-new-date").value.trim();
  const newTime = document.getElementById("reschedule-new-time").value.trim();

  // Validate date & time
  if (!newDate || !newTime) {
    if (errBox) {
      errBox.textContent = "Please provide both a new interview date and time.";
      errBox.style.display = "block";
    }
    return;
  }

  // Prevent past dates
  const selectedDateTime = new Date(`${newDate}T${newTime}`);
  const now = new Date();
  if (selectedDateTime < (now - 2 * 60 * 1000)) {
    if (errBox) {
      errBox.textContent = "New interview date and time cannot be in the past.";
      errBox.style.display = "block";
    }
    return;
  }

  const payload = {
    scheduled_at: `${newDate}T${newTime}:00`,
    duration_minutes: Number(document.getElementById("reschedule-duration").value) || 45,
    round_name: document.getElementById("reschedule-round-name").value.trim() || null,
    interviewer_id: Number(document.getElementById("reschedule-interviewer-id").value) || null,
    meeting_link: document.getElementById("reschedule-meeting-link").value.trim() || null,
    reason: document.getElementById("reschedule-reason").value.trim() || null,
  };

  isRescheduling = true;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Rescheduling...";
  }
  if (cancelBtn) cancelBtn.disabled = true;
  if (errBox) {
    errBox.style.display = "none";
    errBox.textContent = "";
  }

  try {
    const res = await api(`/interviews/${ivId}/reschedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    closeRescheduleModal();

    if (res && res.email_sent === false) {
      showToast("Interview rescheduled, but the email notification could not be sent.", "warning");
    } else {
      showToast("Interview rescheduled successfully! Candidate notified.", "success");
    }

    await refreshAll();
    if (document.getElementById("view-notifications")?.classList.contains("active")) {
      await loadNotifications();
    }
  } catch (err) {
    if (errBox) {
      errBox.textContent = err.message || "Failed to reschedule interview.";
      errBox.style.display = "block";
    }
    showToast(err.message || "Failed to reschedule interview", "error");
  } finally {
    isRescheduling = false;
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Confirm Reschedule";
    }
    if (cancelBtn) cancelBtn.disabled = false;
  }
});

// ============ CANDIDATE STATUS MODAL ============

function openCandidateStatusModal(candidateId, candidateName, currentStatus) {
  document.getElementById("candidate-status-modal").style.display = "flex";
  document.getElementById("status-modal-cand-id").value = candidateId;
  document.getElementById("status-modal-cand-name").textContent = candidateName || "Candidate";

  const select = document.getElementById("status-modal-select");
  if (select && currentStatus) {
    select.value = currentStatus.toLowerCase();
  }
  document.getElementById("status-modal-notes").value = "";
}

function closeCandidateStatusModal() {
  document.getElementById("candidate-status-modal").style.display = "none";
  document.getElementById("form-candidate-status")?.reset();
}

document.getElementById("form-candidate-status")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const candId = document.getElementById("status-modal-cand-id").value;
  const payload = formToJson(e.target);
  delete payload.candidate_id;

  try {
    await api(`/candidates/${candId}/status`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    showToast(`Candidate marked as "${payload.status.toUpperCase()}"! Notification email sent. 🏷️`);
    closeCandidateStatusModal();
    await refreshAll();
    if (document.getElementById("view-notifications")?.classList.contains("active")) {
      await loadNotifications();
    }
  } catch (err) {
    showToast(err.message, "error");
  }
});

// Close modals when clicking overlay backgrounds
["email-preview-modal", "test-email-modal", "reschedule-modal", "candidate-status-modal"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) {
    el.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) el.style.display = "none";
    });
  }
});


// ============================================================
// RECRUITMENT ANALYTICS & HIRING INSIGHTS MODULE (FRONTEND)
// ============================================================

let currentAnalyticsFilters = {
  time_range: "last_30_days",
  start_date: null,
  end_date: null,
  job_id: null,
  department: null,
  interview_status: null,
  candidate_stage: null,
  interviewer_id: null,
};

let pipelineViewMode = "stage"; // "stage" or "funnel"
let jobDistributionSort = "highest"; // "highest", "lowest", "title"
let monthlyTrendSpan = 6; // 6 or 12

let chartPipelineInstance = null;
let chartInterviewStatusInstance = null;
let chartJobDistributionInstance = null;
let chartMonthlyTrendsInstance = null;
let chartInterviewerWorkloadInstance = null;
let chartFeedbackScoresInstance = null;

let currentAnalyticsTab = "activity";
let analyticsTablePage = 1;
const analyticsTablePageSize = 10;
let analyticsTableSearchTerm = "";
let analyticsTotalPages = 1;
let rawInterviewerPerfData = [];
let analyticsFiltersInitialized = false;

// 1. Initialize view and populate dropdowns
async function initAnalyticsView() {
  if (!analyticsFiltersInitialized) {
    await loadAnalyticsFilterOptions();
  }
  await loadAnalyticsData();
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// 2. Load filter options dynamically from backend
async function loadAnalyticsFilterOptions(forceReload = false) {
  if (analyticsFiltersInitialized && !forceReload) return;

  const jobSelect = document.getElementById("an-filter-job");
  const deptSelect = document.getElementById("an-filter-dept");
  const itvSelect = document.getElementById("an-filter-itv");

  // Show loading state in dropdowns
  if (jobSelect) {
    jobSelect.innerHTML = '<option value="">Loading job positions...</option>';
    jobSelect.disabled = true;
  }
  if (deptSelect) {
    deptSelect.innerHTML = '<option value="">Loading departments...</option>';
    deptSelect.disabled = true;
  }
  if (itvSelect) {
    itvSelect.innerHTML = '<option value="">Loading interviewers...</option>';
    itvSelect.disabled = true;
  }

  try {
    let filters = null;
    // Attempt primary endpoint /analytics/filter-options, then fallback to /analytics/filters
    try {
      filters = await api("/analytics/filter-options");
    } catch (e1) {
      try {
        filters = await api("/analytics/filters");
      } catch (e2) {
        // Fallback directly to core resource endpoints if analytics filter endpoint fails
        const [jobsList, itvsList] = await Promise.all([
          api("/jobs/").catch(() => []),
          api("/interviewers/").catch(() => []),
        ]);
        const extractedDepts = [...new Set((jobsList || []).map(j => (j.department || "").trim()).filter(Boolean))].sort();
        filters = {
          job_positions: jobsList || [],
          departments: extractedDepts,
          interviewers: itvsList || [],
        };
      }
    }

    if (!filters) {
      throw new Error("Empty filter response from server");
    }

    // A. Populate Job Positions
    if (jobSelect) {
      const rawJobs = filters.job_positions || filters.jobs || [];
      const uniqueJobs = [];
      const seenJobIds = new Set();
      rawJobs.forEach(j => {
        if (j && j.id && !seenJobIds.has(j.id)) {
          seenJobIds.add(j.id);
          uniqueJobs.push(j);
        }
      });

      if (uniqueJobs.length === 0) {
        jobSelect.innerHTML = '<option value="">All Job Positions</option><option value="" disabled>No Job Positions Available</option>';
      } else {
        let jobHtml = '<option value="">All Job Positions</option>';
        uniqueJobs.forEach(j => {
          jobHtml += `<option value="${j.id}">${escapeHtml(j.title)}</option>`;
        });
        jobSelect.innerHTML = jobHtml;
      }
      jobSelect.disabled = false;
      if (currentAnalyticsFilters.job_id) {
        jobSelect.value = String(currentAnalyticsFilters.job_id);
      }
    }

    // B. Populate Departments
    if (deptSelect) {
      const rawDepts = filters.departments || [];
      const cleanDepts = [];
      const seenDepts = new Set();
      rawDepts.forEach(d => {
        if (typeof d === "string") {
          const trimmed = d.trim();
          if (trimmed && !seenDepts.has(trimmed.toLowerCase())) {
            seenDepts.add(trimmed.toLowerCase());
            cleanDepts.push(trimmed);
          }
        }
      });
      cleanDepts.sort((a, b) => a.localeCompare(b));

      if (cleanDepts.length === 0) {
        deptSelect.innerHTML = '<option value="">All Departments</option><option value="" disabled>No Departments Available</option>';
      } else {
        let deptHtml = '<option value="">All Departments</option>';
        cleanDepts.forEach(d => {
          deptHtml += `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`;
        });
        deptSelect.innerHTML = deptHtml;
      }
      deptSelect.disabled = false;
      if (currentAnalyticsFilters.department) {
        deptSelect.value = currentAnalyticsFilters.department;
      }
    }

    // C. Populate Interviewers
    if (itvSelect) {
      const rawItvs = filters.interviewers || [];
      const uniqueItvs = [];
      const seenItvIds = new Set();
      rawItvs.forEach(i => {
        if (i && i.id && !seenItvIds.has(i.id)) {
          seenItvIds.add(i.id);
          uniqueItvs.push(i);
        }
      });
      uniqueItvs.sort((a, b) => (a.name || a.full_name || "").localeCompare(b.name || b.full_name || ""));

      if (uniqueItvs.length === 0) {
        itvSelect.innerHTML = '<option value="">All Interviewers</option><option value="" disabled>No Interviewers Available</option>';
      } else {
        let itvHtml = '<option value="">All Interviewers</option>';
        uniqueItvs.forEach(i => {
          const displayName = i.name || i.full_name || `Interviewer #${i.id}`;
          itvHtml += `<option value="${i.id}">${escapeHtml(displayName)}</option>`;
        });
        itvSelect.innerHTML = itvHtml;
      }
      itvSelect.disabled = false;
      if (currentAnalyticsFilters.interviewer_id) {
        itvSelect.value = String(currentAnalyticsFilters.interviewer_id);
      }
    }

    analyticsFiltersInitialized = true;
    clearAnalyticsError();
  } catch (err) {
    console.error("Failed to load analytics filters:", err);
    if (jobSelect) {
      jobSelect.innerHTML = '<option value="">All Job Positions</option>';
      jobSelect.disabled = false;
    }
    if (deptSelect) {
      deptSelect.innerHTML = '<option value="">All Departments</option>';
      deptSelect.disabled = false;
    }
    if (itvSelect) {
      itvSelect.innerHTML = '<option value="">All Interviewers</option>';
      itvSelect.disabled = false;
    }
    analyticsFiltersInitialized = false;
    showAnalyticsError("Unable to load filter dropdowns from database: " + (err.message || "Network error"), true);
  }
}

// 3. Build query string helper
function buildAnalyticsQueryString(overrides = {}) {
  const f = { ...currentAnalyticsFilters, ...overrides };
  const params = new URLSearchParams();
  if (f.time_range) params.append("time_range", f.time_range);
  if (f.start_date) params.append("start_date", f.start_date);
  if (f.end_date) params.append("end_date", f.end_date);
  if (f.job_id) params.append("job_id", f.job_id);
  if (f.department) params.append("department", f.department);
  if (f.interview_status) params.append("interview_status", f.interview_status);
  if (f.candidate_stage) params.append("candidate_stage", f.candidate_stage);
  if (f.interviewer_id) params.append("interviewer_id", f.interviewer_id);
  return params.toString();
}

// 4. Load all analytics components
async function loadAnalyticsData() {
  const qs = buildAnalyticsQueryString();
  renderActiveFilterChips();
  clearAnalyticsError();

  // Set loading state on all 8 KPI cards
  const kpiIds = ["candidates", "jobs", "interviews", "completion", "score", "cancelled", "hired", "pending"];
  kpiIds.forEach(id => {
    const el = document.getElementById(`an-kpi-${id}`);
    if (el) el.classList.add("loading");
  });

  // Load KPIs
  try {
    const kpis = await api(`/analytics/overview?${qs}`);
    renderAnalyticsKPIs(kpis);
  } catch (err) {
    console.error("Overview KPI load error:", err);
    kpiIds.forEach(id => {
      const el = document.getElementById(`an-kpi-${id}`);
      if (el) el.classList.remove("loading");
    });
    showAnalyticsError(err.message);
  }

  // Load Pipeline
  try {
    const pipelineData = await api(`/analytics/recruitment-pipeline?${qs}`);
    renderPipelineChart(pipelineData);
  } catch (err) {
    console.error("Pipeline chart error:", err);
  }

  // Load Monthly Trends
  try {
    const trendQs = new URLSearchParams();
    trendQs.append("months", monthlyTrendSpan);
    if (currentAnalyticsFilters.time_range === "custom" && currentAnalyticsFilters.start_date) {
      trendQs.append("start_date", currentAnalyticsFilters.start_date);
      trendQs.append("end_date", currentAnalyticsFilters.end_date);
    } else {
      trendQs.append("time_range", currentAnalyticsFilters.time_range);
    }
    if (currentAnalyticsFilters.job_id) trendQs.append("job_id", currentAnalyticsFilters.job_id);
    if (currentAnalyticsFilters.department) trendQs.append("department", currentAnalyticsFilters.department);
    if (currentAnalyticsFilters.interviewer_id) trendQs.append("interviewer_id", currentAnalyticsFilters.interviewer_id);
    const trendsData = await api(`/analytics/monthly-trends?${trendQs.toString()}`);
    renderMonthlyTrendsChart(trendsData);
  } catch (err) {
    console.error("Monthly trends error:", err);
  }

  // Load Job Distribution
  try {
    const jobDistQs = new URLSearchParams();
    if (currentAnalyticsFilters.job_id) jobDistQs.append("job_id", currentAnalyticsFilters.job_id);
    if (currentAnalyticsFilters.department) jobDistQs.append("department_filter", currentAnalyticsFilters.department);
    jobDistQs.append("sort_order", jobDistributionSort);
    const jobDistData = await api(`/analytics/job-distribution?${jobDistQs.toString()}`);
    renderJobDistributionChart(jobDistData);
  } catch (err) {
    console.error("Job distribution chart error:", err);
  }

  // Load Interview Status
  try {
    const statusData = await api(`/analytics/interview-status?${qs}`);
    renderInterviewStatusChart(statusData);
  } catch (err) {
    console.error("Status chart error:", err);
  }

  // Load Interviewer Workload Chart & Performance Table
  try {
    const itvData = await api(`/analytics/interviewer-performance?${qs}`);
    rawInterviewerPerfData = itvData.interviewers || [];
    renderInterviewerWorkloadChart(rawInterviewerPerfData);
    renderInterviewerPerformanceTable(rawInterviewerPerfData);
  } catch (err) {
    console.error("Interviewer performance error:", err);
  }

  // Load Feedback Score Analysis
  try {
    const fbData = await api(`/analytics/feedback-analysis?${qs}`);
    renderFeedbackAnalysisChart(fbData);
  } catch (err) {
    console.error("Feedback analysis chart error:", err);
  }

  // Load Active Detailed Table
  await loadAnalyticsTableData();
}

// 5. Render KPIs
function renderAnalyticsKPIs(kpis) {
  if (!kpis) return;

  const periodBadge = document.getElementById("an-active-period-badge");
  if (periodBadge && kpis.filter_summary) {
    periodBadge.textContent = kpis.filter_summary.period_label || "Selected Period";
  }

  const applyKPI = (elemId, kpiItem, defaultVal = "0") => {
    const valEl = document.getElementById(`an-kpi-${elemId}`);
    const subEl = document.getElementById(`an-kpi-${elemId}-sub`);
    const compEl = document.getElementById(`an-kpi-${elemId}-comp`);

    if (valEl) {
      valEl.classList.remove("loading");
      valEl.textContent = (kpiItem && kpiItem.display_value !== undefined && kpiItem.display_value !== null)
        ? kpiItem.display_value
        : defaultVal;
    }
    if (subEl) {
      subEl.textContent = (kpiItem && kpiItem.subtext) || "";
    }
    if (compEl) {
      compEl.className = `trend-pill ${(kpiItem && kpiItem.trend) || "neutral"}`;
      compEl.textContent = (kpiItem && kpiItem.comparison_text) || "No change vs previous period";
    }
  };

  applyKPI("candidates", kpis.total_candidates, "0");
  applyKPI("jobs", kpis.active_jobs, "0");
  applyKPI("interviews", kpis.total_interviews, "0");
  applyKPI("completion", kpis.completion_rate, "0.0%");
  applyKPI("score", kpis.avg_feedback_score, "0.0 / 5.0");
  applyKPI("cancelled", kpis.cancelled_interviews, "0");
  applyKPI("hired", kpis.candidates_hired, "0");
  applyKPI("pending", kpis.pending_interviews, "0");
}

// 6. Chart 1: Candidate Recruitment Pipeline (Horizontal Bar / Funnel)
function renderPipelineChart(data) {
  const canvas = document.getElementById("chart-recruitment-pipeline");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartPipelineInstance) {
    chartPipelineInstance.destroy();
  }

  const stages = data.stages || [];
  const labels = stages.map(s => s.stage_label);
  const values = pipelineViewMode === "funnel"
    ? stages.map(s => s.funnel_count)
    : stages.map(s => s.count);

  const colors = [
    "rgba(99, 102, 241, 0.85)",  // Applied - Indigo
    "rgba(139, 92, 246, 0.85)",  // Shortlisted - Purple
    "rgba(14, 165, 233, 0.85)",  // Interview Scheduled - Sky
    "rgba(5, 150, 105, 0.85)",   // Interviewed - Emerald
    "rgba(16, 185, 129, 0.85)",  // Selected - Green
    "rgba(239, 68, 68, 0.75)",   // Rejected - Red
  ];

  const borderColors = colors.map(c => c.replace("0.85", "1").replace("0.75", "1"));

  chartPipelineInstance = new Chart(canvas, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        label: pipelineViewMode === "funnel" ? "Cumulative Funnel Reach" : "Current Stage Candidates",
        data: values,
        backgroundColor: colors.slice(0, stages.length),
        borderColor: borderColors.slice(0, stages.length),
        borderWidth: 1.5,
        borderRadius: 6,
      }]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const st = stages[ctx.dataIndex];
              if (!st) return "";
              if (pipelineViewMode === "funnel") {
                return `Funnel Reach: ${st.funnel_count} candidates (${st.funnel_percentage}% of total applicants)`;
              }
              return `Active Candidates: ${st.count} (${st.percentage}% of total applicants)`;
            }
          }
        }
      },
      onClick: (evt, elements) => {
        if (!elements || elements.length === 0) return;
        const idx = elements[0].index;
        const st = stages[idx];
        if (st) {
          filterByPipelineStage(st.stage_key);
        }
      },
      scales: {
        x: {
          beginAtZero: true,
          ticks: { precision: 0 },
          grid: { color: "rgba(226, 232, 240, 0.6)" },
        },
        y: {
          grid: { display: false },
          ticks: { font: { weight: "600" } }
        }
      }
    }
  });
}

function togglePipelineViewMode() {
  pipelineViewMode = (pipelineViewMode === "stage") ? "funnel" : "stage";
  const btn = document.getElementById("btn-toggle-pipeline-mode");
  if (btn) {
    btn.textContent = (pipelineViewMode === "funnel") ? "Stage View" : "Funnel View";
  }
  loadAnalyticsData();
}

// 7. Chart 2: Interview Status Donut
function renderInterviewStatusChart(data) {
  const canvas = document.getElementById("chart-interview-status");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartInterviewStatusInstance) {
    chartInterviewStatusInstance.destroy();
  }

  const items = data.statuses || [];
  const total = data.total_interviews || 0;
  const totalBadge = document.getElementById("an-interview-status-total-badge");
  if (totalBadge) totalBadge.textContent = `${total} Interview${total === 1 ? '' : 's'}`;

  const labels = items.map(i => i.status_label);
  const counts = items.map(i => i.count);
  const bgColors = items.map(i => i.color);

  chartInterviewStatusInstance = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        data: counts.length && total > 0 ? counts : [1],
        backgroundColor: total > 0 ? bgColors : ["#E2E8F0"],
        borderWidth: 2,
        borderColor: "#FFFFFF",
        hoverOffset: total > 0 ? 6 : 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "right",
          labels: {
            boxWidth: 14,
            padding: 12,
            font: { family: "Inter", size: 12 },
          }
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              if (total === 0) return " No interviews recorded";
              const item = items[ctx.dataIndex];
              return ` ${item.status_label}: ${item.count} (${item.percentage}%)`;
            }
          }
        }
      },
      onClick: (evt, elements) => {
        if (!elements || elements.length === 0 || total === 0) return;
        const idx = elements[0].index;
        const statusItem = items[idx];
        if (statusItem) {
          filterByInterviewStatus(statusItem.status_key);
        }
      },
      cutout: "68%",
    }
  });
}

// 8. Chart 3: Job-Wise Candidate Distribution
function renderJobDistributionChart(data) {
  const canvas = document.getElementById("chart-job-distribution");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartJobDistributionInstance) {
    chartJobDistributionInstance.destroy();
  }

  const jobs = data.jobs || [];
  const labels = jobs.map(j => j.title.length > 20 ? j.title.slice(0, 18) + "…" : j.title);
  const counts = jobs.map(j => j.candidate_count);

  chartJobDistributionInstance = new Chart(canvas, {
    type: "bar",
    data: {
      labels: labels.length ? labels : ["No jobs posted"],
      datasets: [{
        label: "Candidates",
        data: counts.length ? counts : [0],
        backgroundColor: "rgba(99, 102, 241, 0.8)",
        borderColor: "#4F46E5",
        borderWidth: 1.5,
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const j = jobs[items[0].dataIndex];
              return j ? `${j.title} (${j.department || 'General'})` : "";
            },
            label: (ctx) => {
              const j = jobs[ctx.dataIndex];
              return j ? `Applicants: ${j.candidate_count} (${j.percentage}% of all candidates) · Interviews: ${j.interview_count}` : "";
            }
          }
        }
      },
      onClick: (evt, elements) => {
        if (!elements || elements.length === 0) return;
        const idx = elements[0].index;
        const j = jobs[idx];
        if (j && j.job_id) {
          filterByJobId(j.job_id);
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { precision: 0 },
          grid: { color: "rgba(226, 232, 240, 0.6)" },
        },
        x: {
          grid: { display: false },
        }
      }
    }
  });
}

function onJobSortChanged() {
  const sel = document.getElementById("an-job-sort-select");
  if (sel) {
    jobDistributionSort = sel.value;
    loadAnalyticsData();
  }
}

// 9. Chart 4: Monthly Recruitment Trends (Multi-Line)
function renderMonthlyTrendsChart(data) {
  const canvas = document.getElementById("chart-monthly-trends");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartMonthlyTrendsInstance) {
    chartMonthlyTrendsInstance.destroy();
  }

  const trends = data.trends || [];
  const labels = trends.map(t => t.month_label);

  chartMonthlyTrendsInstance = new Chart(canvas, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Candidates Registered",
          data: trends.map(t => t.candidates_registered),
          borderColor: "#6366F1",
          backgroundColor: "rgba(99, 102, 241, 0.08)",
          tension: 0.35,
          fill: true,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
        {
          label: "Interviews Scheduled",
          data: trends.map(t => t.interviews_scheduled),
          borderColor: "#0EA5E9",
          backgroundColor: "transparent",
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
        {
          label: "Interviews Completed",
          data: trends.map(t => t.interviews_completed),
          borderColor: "#059669",
          backgroundColor: "transparent",
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
        },
        {
          label: "Candidates Selected",
          data: trends.map(t => t.candidates_selected),
          borderColor: "#F59E0B",
          backgroundColor: "transparent",
          borderDash: [5, 5],
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "top",
          labels: {
            boxWidth: 12,
            font: { family: "Inter", size: 11 },
            usePointStyle: true,
          }
        },
        tooltip: {
          mode: "index",
          intersect: false,
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { precision: 0 },
          grid: { color: "rgba(226, 232, 240, 0.6)" },
        },
        x: {
          grid: { display: false },
        }
      }
    }
  });
}

function setMonthlyTrendSpan(span) {
  monthlyTrendSpan = span;
  const btn6m = document.getElementById("btn-trend-6m");
  const btn12m = document.getElementById("btn-trend-12m");
  if (span === 6) {
    if (btn6m) { btn6m.style.background = "#EEF2FF"; btn6m.style.color = "var(--primary)"; }
    if (btn12m) { btn12m.style.background = ""; btn12m.style.color = ""; }
  } else {
    if (btn12m) { btn12m.style.background = "#EEF2FF"; btn12m.style.color = "var(--primary)"; }
    if (btn6m) { btn6m.style.background = ""; btn6m.style.color = ""; }
  }
  loadAnalyticsData();
}

// 10. Chart 5: Interviewer Workload (Grouped Horizontal/Vertical Bar)
function renderInterviewerWorkloadChart(interviewers) {
  const canvas = document.getElementById("chart-interviewer-workload");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartInterviewerWorkloadInstance) {
    chartInterviewerWorkloadInstance.destroy();
  }

  const badge = document.getElementById("an-interviewer-count-badge");
  if (badge) {
    badge.textContent = `${(interviewers || []).length} Interviewer${(interviewers || []).length !== 1 ? 's' : ''}`;
  }

  const list = (interviewers && interviewers.length) ? interviewers.slice(0, 8) : [];
  const labels = list.map(i => i.full_name);

  chartInterviewerWorkloadInstance = new Chart(canvas, {
    type: "bar",
    data: {
      labels: labels.length ? labels : ["No Interviewers"],
      datasets: [
        {
          label: "Assigned",
          data: list.map(i => i.assigned_interviews),
          backgroundColor: "rgba(99, 102, 241, 0.8)",
          borderColor: "#6366F1",
          borderWidth: 1.5,
          borderRadius: 4,
        },
        {
          label: "Completed",
          data: list.map(i => i.completed_interviews),
          backgroundColor: "rgba(5, 150, 105, 0.8)",
          borderColor: "#059669",
          borderWidth: 1.5,
          borderRadius: 4,
        },
        {
          label: "Pending",
          data: list.map(i => i.pending_interviews),
          backgroundColor: "rgba(139, 92, 246, 0.8)",
          borderColor: "#8B5CF6",
          borderWidth: 1.5,
          borderRadius: 4,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "top",
          labels: { font: { family: "Inter", size: 11 }, boxWidth: 12 }
        },
        tooltip: {
          mode: "index",
          intersect: false,
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { precision: 0 },
          grid: { color: "rgba(226, 232, 240, 0.6)" },
        },
        x: {
          grid: { display: false },
        }
      }
    }
  });
}

// 11. Chart 6: Feedback Score Analysis (Bar Chart by Tiers)
function renderFeedbackAnalysisChart(data) {
  const canvas = document.getElementById("chart-feedback-scores");
  if (!canvas || typeof Chart === "undefined") return;

  if (chartFeedbackScoresInstance) {
    chartFeedbackScoresInstance.destroy();
  }

  const badge = document.getElementById("an-feedback-avg-badge");
  if (badge && data) {
    badge.textContent = `Avg: ${Number(data.average_score || 0).toFixed(1)} / 5.0 (${data.total_reviews || 0} reviews)`;
  }

  const ranges = (data && data.score_ranges) || [];
  const labels = ranges.map(r => `${r.score_range} (${r.label})`);
  const counts = ranges.map(r => r.count);

  const tierColors = [
    "rgba(239, 68, 68, 0.8)",   // 1.0 - 2.0 Needs Improvement (Red)
    "rgba(245, 158, 11, 0.8)",  // 2.1 - 3.0 Fair (Amber)
    "rgba(14, 165, 233, 0.8)",  // 3.1 - 4.0 Good (Sky/Blue)
    "rgba(16, 185, 129, 0.8)",  // 4.1 - 5.0 Excellent (Green)
  ];
  const tierBorders = ["#EF4444", "#F59E0B", "#0EA5E9", "#10B981"];

  chartFeedbackScoresInstance = new Chart(canvas, {
    type: "bar",
    data: {
      labels: labels.length ? labels : ["1.0-2.0", "2.1-3.0", "3.1-4.0", "4.1-5.0"],
      datasets: [{
        label: "Submitted Scorecards",
        data: counts.length ? counts : [0, 0, 0, 0],
        backgroundColor: tierColors,
        borderColor: tierBorders,
        borderWidth: 1.5,
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const item = ranges[ctx.dataIndex];
              return item ? `${item.count} reviews (${item.percentage}%)` : "";
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { precision: 0 },
          grid: { color: "rgba(226, 232, 240, 0.6)" },
        },
        x: {
          grid: { display: false },
        }
      }
    }
  });
}

// 12. Interviewer Performance Table
function renderInterviewerPerformanceTable(interviewers) {
  const tbody = document.getElementById("table-interviewer-perf");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!interviewers || interviewers.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="8"><div class="empty-state"><span class="empty-icon">🎯</span><p>No interviewer records found</p></div></td></tr>`;
    return;
  }

  interviewers.forEach(itv => {
    const tr = document.createElement("tr");
    const avgScoreDisplay = itv.average_score !== null
      ? `<span class="badge" style="background:#FFFBEB; color:#D97706; font-weight:700;">★ ${itv.average_score.toFixed(1)} / 5.0</span>`
      : `<span style="color:var(--text-muted)">—</span>`;

    const subRateColor = itv.feedback_submission_rate >= 80 ? "#059669" : (itv.feedback_submission_rate >= 50 ? "#D97706" : "#DC2626");

    tr.innerHTML = `
      <td class="name-col" style="font-weight: 600;">${itv.full_name}</td>
      <td>${itv.title || '<span style="color:var(--text-muted)">Interviewer</span>'}</td>
      <td class="mono-col">${itv.email}</td>
      <td style="font-weight:600;">${itv.assigned_interviews}</td>
      <td style="color:#059669; font-weight:600;">${itv.completed_interviews}</td>
      <td style="color:#D97706;">${itv.pending_interviews}</td>
      <td>
        <span style="font-weight:600; color:${subRateColor};">${itv.feedback_submission_rate.toFixed(1)}%</span>
        <div style="width:60px; height:4px; background:#F1F5F9; border-radius:99px; margin-top:3px; overflow:hidden;">
          <div style="width:${itv.feedback_submission_rate}%; height:100%; background:${subRateColor};"></div>
        </div>
      </td>
      <td>${avgScoreDisplay}</td>
    `;
    tbody.appendChild(tr);
  });
}

function filterInterviewerTable() {
  const term = (document.getElementById("an-search-interviewer")?.value || "").toLowerCase();
  const filtered = rawInterviewerPerfData.filter(i =>
    i.full_name.toLowerCase().includes(term) ||
    (i.title && i.title.toLowerCase().includes(term)) ||
    i.email.toLowerCase().includes(term)
  );
  renderInterviewerPerformanceTable(filtered);
}

// 11. Detailed Analytics Tables (Tabs & Pagination)
function switchAnalyticsTab(tabName) {
  currentAnalyticsTab = tabName;
  analyticsTablePage = 1;

  ["activity", "interviews", "jobs"].forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const content = document.getElementById(`an-content-${t}`);
    if (btn) btn.classList.toggle("active", t === tabName);
    if (content) content.style.display = (t === tabName) ? "block" : "none";
  });

  const searchInput = document.getElementById("an-tab-search-input");
  if (searchInput) {
    searchInput.placeholder = tabName === "activity"
      ? "Search candidate name or email…"
      : (tabName === "interviews" ? "Search interview candidate or round…" : "Search job title or department…");
  }

  loadAnalyticsTableData();
}

async function loadAnalyticsTableData() {
  const countLabel = document.getElementById("an-table-count-label");
  const pageInfo = document.getElementById("an-page-info");
  const prevBtn = document.getElementById("an-btn-prev-page");
  const nextBtn = document.getElementById("an-btn-next-page");

  const qs = new URLSearchParams();
  qs.append("page", analyticsTablePage);
  qs.append("page_size", analyticsTablePageSize);
  if (analyticsTableSearchTerm) qs.append("search", analyticsTableSearchTerm);

  // Apply current active filters to tables
  if (currentAnalyticsFilters.job_id) qs.append("job_id", currentAnalyticsFilters.job_id);
  if (currentAnalyticsFilters.department) qs.append("department", currentAnalyticsFilters.department);
  if (currentAnalyticsFilters.candidate_stage) qs.append("stage_filter", currentAnalyticsFilters.candidate_stage);
  if (currentAnalyticsFilters.interview_status) qs.append("status_filter", currentAnalyticsFilters.interview_status);
  if (currentAnalyticsFilters.interviewer_id) qs.append("interviewer_id", currentAnalyticsFilters.interviewer_id);
  if (currentAnalyticsFilters.time_range) qs.append("time_range", currentAnalyticsFilters.time_range);
  if (currentAnalyticsFilters.start_date) qs.append("start_date", currentAnalyticsFilters.start_date);
  if (currentAnalyticsFilters.end_date) qs.append("end_date", currentAnalyticsFilters.end_date);

  try {
    if (currentAnalyticsTab === "activity") {
      const data = await api(`/analytics/recent-activity?${qs.toString()}`);
      renderRecentActivityTable(data.items || []);
      updateTablePagination(data.total, data.page, data.total_pages);
    } else if (currentAnalyticsTab === "interviews") {
      const data = await api(`/analytics/interview-summary?${qs.toString()}`);
      renderInterviewSummaryTable(data.items || []);
      updateTablePagination(data.total, data.page, data.total_pages);
    } else if (currentAnalyticsTab === "jobs") {
      const data = await api(`/analytics/job-summary?${qs.toString()}`);
      renderJobSummaryTable(data.items || []);
      updateTablePagination(data.total, data.page, data.total_pages);
    }
  } catch (err) {
    console.error("Table data load error:", err);
  }
}

function updateTablePagination(total, page, totalPages) {
  analyticsTablePage = page;
  analyticsTotalPages = totalPages || 1;

  const countLabel = document.getElementById("an-table-count-label");
  const pageInfo = document.getElementById("an-page-info");
  const prevBtn = document.getElementById("an-btn-prev-page");
  const nextBtn = document.getElementById("an-btn-next-page");

  if (countLabel) countLabel.textContent = `Showing ${total} total records`;
  if (pageInfo) pageInfo.textContent = `Page ${page} of ${totalPages}`;
  if (prevBtn) prevBtn.disabled = (page <= 1);
  if (nextBtn) nextBtn.disabled = (page >= totalPages);
}

function changeAnalyticsPage(delta) {
  const newPage = analyticsTablePage + delta;
  if (newPage >= 1 && newPage <= analyticsTotalPages) {
    analyticsTablePage = newPage;
    loadAnalyticsTableData();
  }
}

function onAnalyticsTableSearch() {
  const input = document.getElementById("an-tab-search-input");
  analyticsTableSearchTerm = input ? input.value.trim() : "";
  analyticsTablePage = 1;
  loadAnalyticsTableData();
}

function renderRecentActivityTable(items) {
  const tbody = document.getElementById("table-an-activity");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (items.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="6"><div class="empty-state"><span class="empty-icon">👤</span><p>No candidates match active filters</p></div></td></tr>`;
    return;
  }

  items.forEach(c => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="id-col">#${c.candidate_id}</td>
      <td class="name-col">${c.candidate_name}</td>
      <td class="mono-col">${c.email}</td>
      <td>${c.job_title}</td>
      <td>${statusBadge(c.stage)}</td>
      <td>${c.registered_at}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderInterviewSummaryTable(items) {
  const tbody = document.getElementById("table-an-interviews");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (items.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="8"><div class="empty-state"><span class="empty-icon">📅</span><p>No interview records match active filters</p></div></td></tr>`;
    return;
  }

  items.forEach(iv => {
    const tr = document.createElement("tr");
    const scoreText = iv.feedback_score !== null
      ? `<span class="badge" style="background:#FFFBEB; color:#D97706; font-weight:700;">★ ${iv.feedback_score.toFixed(1)}</span>`
      : `<span style="color:var(--text-muted)">—</span>`;

    tr.innerHTML = `
      <td class="id-col">#${iv.interview_id}</td>
      <td class="name-col">${iv.candidate_name}</td>
      <td>${iv.job_title}</td>
      <td>${iv.interviewer_name}</td>
      <td class="mono-col">${iv.scheduled_at}</td>
      <td>${iv.round_name || 'General'}</td>
      <td>${statusBadge(iv.status)}</td>
      <td>${scoreText}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderJobSummaryTable(items) {
  const tbody = document.getElementById("table-an-jobs");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (items.length === 0) {
    tbody.innerHTML = `<tr class="empty-state-row"><td colspan="8"><div class="empty-state"><span class="empty-icon">💼</span><p>No job positions found</p></div></td></tr>`;
    return;
  }

  items.forEach(j => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="id-col">#${j.job_id}</td>
      <td class="name-col">${j.title}</td>
      <td>${j.department || 'General'}</td>
      <td>${statusBadge(j.status)}</td>
      <td style="font-weight:600;">${j.candidate_count}</td>
      <td>${j.interview_count}</td>
      <td style="color:#059669; font-weight:600;">${j.completed_interview_count}</td>
      <td style="color:#4F46E5; font-weight:600;">${j.selected_count}</td>
    `;
    tbody.appendChild(tr);
  });
}

// 12. Interactive Chart Click Filters
function filterByPipelineStage(stageKey) {
  currentAnalyticsFilters.candidate_stage = stageKey;
  const stageSelect = document.getElementById("an-filter-stage");
  if (stageSelect) stageSelect.value = stageKey;
  switchAnalyticsTab("activity");
  showToast(`Filtering candidate activity by stage "${stageKey.toUpperCase()}" 🏷️`);
}

function filterByInterviewStatus(statusKey) {
  currentAnalyticsFilters.interview_status = statusKey;
  const statusSelect = document.getElementById("an-filter-status");
  if (statusSelect) statusSelect.value = statusKey;
  switchAnalyticsTab("interviews");
  showToast(`Filtering interview logs by status "${statusKey.toUpperCase()}" 📅`);
}

function filterByJobId(jobId) {
  currentAnalyticsFilters.job_id = jobId;
  const jobSelect = document.getElementById("an-filter-job");
  if (jobSelect) jobSelect.value = jobId;
  loadAnalyticsData();
  showToast(`Filtering analytics by selected job position 💼`);
}

// 13. Preset Toolbar & Date Filter Handlers
function setAnalyticsPreset(preset) {
  currentAnalyticsFilters.time_range = preset;
  currentAnalyticsFilters.start_date = null;
  currentAnalyticsFilters.end_date = null;

  document.querySelectorAll("#analytics-presets-bar .preset-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.preset === preset);
  });

  const startWrap = document.getElementById("filter-custom-start-wrap");
  const endWrap = document.getElementById("filter-custom-end-wrap");
  if (startWrap) startWrap.style.display = (preset === "custom") ? "flex" : "none";
  if (endWrap) endWrap.style.display = (preset === "custom") ? "flex" : "none";

  analyticsTablePage = 1;
  loadAnalyticsData();
}

function toggleCustomDateInputs() {
  setAnalyticsPreset("custom");
  const startInput = document.getElementById("an-filter-start-date");
  const endInput = document.getElementById("an-filter-end-date");
  const now = new Date();
  const past30 = new Date(Date.now() - 30 * 86400000);

  if (startInput && !startInput.value) startInput.value = past30.toISOString().slice(0, 10);
  if (endInput && !endInput.value) endInput.value = now.toISOString().slice(0, 10);
  onCustomDateChanged();
}

function onCustomDateChanged() {
  const startVal = document.getElementById("an-filter-start-date")?.value;
  const endVal = document.getElementById("an-filter-end-date")?.value;

  if (startVal && endVal) {
    if (new Date(startVal) > new Date(endVal)) {
      showAnalyticsError("Start date cannot be after end date. Please adjust your range.");
      return;
    }
    clearAnalyticsError();
    currentAnalyticsFilters.time_range = "custom";
    currentAnalyticsFilters.start_date = startVal;
    currentAnalyticsFilters.end_date = endVal;
    analyticsTablePage = 1;
    loadAnalyticsData();
  }
}

function onAnalyticsFilterChanged() {
  currentAnalyticsFilters.job_id = document.getElementById("an-filter-job")?.value || null;
  currentAnalyticsFilters.department = document.getElementById("an-filter-dept")?.value || null;
  currentAnalyticsFilters.interview_status = document.getElementById("an-filter-status")?.value || null;
  currentAnalyticsFilters.candidate_stage = document.getElementById("an-filter-stage")?.value || null;
  currentAnalyticsFilters.interviewer_id = document.getElementById("an-filter-itv")?.value || null;

  analyticsTablePage = 1;
  loadAnalyticsData();
}

function resetAnalyticsFilters() {
  currentAnalyticsFilters = {
    time_range: "last_30_days",
    start_date: null,
    end_date: null,
    job_id: null,
    department: null,
    interview_status: null,
    candidate_stage: null,
    interviewer_id: null,
  };

  document.querySelectorAll("#analytics-presets-bar .preset-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.preset === "last_30_days");
  });

  const startWrap = document.getElementById("filter-custom-start-wrap");
  const endWrap = document.getElementById("filter-custom-end-wrap");
  if (startWrap) startWrap.style.display = "none";
  if (endWrap) endWrap.style.display = "none";

  ["an-filter-job", "an-filter-dept", "an-filter-status", "an-filter-stage", "an-filter-itv"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  const searchInput = document.getElementById("an-tab-search-input");
  if (searchInput) searchInput.value = "";
  analyticsTableSearchTerm = "";
  analyticsTablePage = 1;

  clearAnalyticsError();
  loadAnalyticsData();
  showToast("Recruitment analytics filters reset to default (Last 30 Days) 🔄");
}

function renderActiveFilterChips() {
  const container = document.getElementById("an-active-chips");
  if (!container) return;
  container.innerHTML = "";

  const activeFilters = [];
  if (currentAnalyticsFilters.job_id) {
    const jobText = document.getElementById("an-filter-job")?.selectedOptions[0]?.text || "Job ID " + currentAnalyticsFilters.job_id;
    activeFilters.push({ key: "job_id", label: `Job: ${jobText}` });
  }
  if (currentAnalyticsFilters.department) {
    activeFilters.push({ key: "department", label: `Dept: ${currentAnalyticsFilters.department}` });
  }
  if (currentAnalyticsFilters.interview_status) {
    activeFilters.push({ key: "interview_status", label: `Status: ${currentAnalyticsFilters.interview_status.toUpperCase()}` });
  }
  if (currentAnalyticsFilters.candidate_stage) {
    activeFilters.push({ key: "candidate_stage", label: `Stage: ${currentAnalyticsFilters.candidate_stage.toUpperCase()}` });
  }
  if (currentAnalyticsFilters.interviewer_id) {
    const itvText = document.getElementById("an-filter-itv")?.selectedOptions[0]?.text || "Interviewer " + currentAnalyticsFilters.interviewer_id;
    activeFilters.push({ key: "interviewer_id", label: `Interviewer: ${itvText}` });
  }

  if (activeFilters.length === 0) {
    container.style.display = "none";
    return;
  }

  container.style.display = "flex";
  activeFilters.forEach(f => {
    const chip = document.createElement("div");
    chip.className = "filter-chip";
    chip.innerHTML = `
      <span>${f.label}</span>
      <span class="filter-chip-remove" onclick="removeActiveFilter('${f.key}')" title="Remove filter">&times;</span>
    `;
    container.appendChild(chip);
  });
}

function removeActiveFilter(key) {
  currentAnalyticsFilters[key] = null;
  const selectIdMap = {
    job_id: "an-filter-job",
    department: "an-filter-dept",
    interview_status: "an-filter-status",
    candidate_stage: "an-filter-stage",
    interviewer_id: "an-filter-itv",
  };
  const selectEl = document.getElementById(selectIdMap[key]);
  if (selectEl) selectEl.value = "";
  loadAnalyticsData();
}

function showAnalyticsError(msg, allowRetry = false) {
  const errBox = document.getElementById("an-filter-error");
  if (errBox) {
    if (allowRetry) {
      errBox.innerHTML = `⚠️ ${escapeHtml(msg)} <button onclick="loadAnalyticsFilterOptions(true)" class="btn btn-sm btn-secondary" style="margin-left: 10px; padding: 2px 10px; font-size: 11.5px; cursor: pointer; border-radius: 4px;">🔄 Retry</button>`;
    } else {
      errBox.textContent = `⚠️ ${msg}`;
    }
    errBox.style.display = "block";
  }
}

function clearAnalyticsError() {
  const errBox = document.getElementById("an-filter-error");
  if (errBox) {
    errBox.textContent = "";
    errBox.style.display = "none";
  }
}

// 14. Export Handlers (CSV and PDF)
async function exportAnalytics(type) {
  const spinEl = document.getElementById(`spin-${type}`);
  const btnEl = document.getElementById(`btn-export-${type}`);
  if (btnEl) btnEl.classList.add("loading");
  if (spinEl) spinEl.style.display = "inline-block";

  try {
    const qs = buildAnalyticsQueryString();
    const token = localStorage.getItem("auth_token");
    const headers = token ? { "Authorization": `Bearer ${token}` } : {};

    const resp = await fetch(`${API_BASE}/analytics/export/${type}?${qs}`, { headers });
    if (!resp.ok) {
      const errJson = await resp.json().catch(() => null);
      throw new Error((errJson && errJson.detail) || `Failed to export ${type.toUpperCase()}`);
    }

    const blob = await resp.blob();
    const disposition = resp.headers.get("Content-Disposition") || "";
    let filename = `recruitment_analytics_${new Date().toISOString().slice(0, 10)}.${type}`;
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    if (filenameMatch && filenameMatch[1]) {
      filename = filenameMatch[1];
    }

    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(downloadUrl);

    showToast(`Analytics ${type.toUpperCase()} report generated & downloaded successfully! 📄`, "success");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    if (btnEl) btnEl.classList.remove("loading");
    if (spinEl) spinEl.style.display = "none";
  }
}




