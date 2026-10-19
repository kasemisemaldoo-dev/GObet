const state = {
  csrfToken: "",
  user: null,
  events: [],
  sports: [],
  sport: "Football",
  filter: "All",
  view: "markets",
  selections: new Map(),
  toastTimer: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (options.method === "POST") headers["X-CSRF-Token"] = state.csrfToken;
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
  if (data.csrf_token) state.csrfToken = data.csrf_token;
  return data;
}

function currency(value = state.user?.balance || 0, code = state.user?.currency || "EUR") {
  if (value === "UNLIMITED") return "Unlimited";
  return new Intl.NumberFormat(code === "ALL" ? "sq-AL" : "en-IE", {
    style: "currency", currency: code, minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(Number(value));
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 3000);
}

function showAuth(message = "") {
  state.user = null;
  $("#app-view").classList.add("hidden");
  $("#auth-view").classList.remove("hidden");
  $("#auth-error").textContent = message;
}

function showApp() {
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#account-name").textContent = state.user.display_name;
  $("#account-avatar").textContent = state.user.display_name.trim().charAt(0).toUpperCase();
  $("#account-username").textContent = `@${state.user.username}`;
  $("#header-balance").textContent = currency();
  $("#stake-currency").textContent = state.user.currency;
  $("#admin-nav").classList.toggle("hidden", state.user.role !== "admin");
  $("#account-nav").classList.toggle("hidden", state.user.username !== "zero5");
  $("#sports-count").textContent = String(state.sports.length).padStart(2, "0");
  renderSportNav();
  renderSlip();
}

async function refreshEvents() {
  const response = await api(`/api/events?sport=${encodeURIComponent(state.sport)}`);
  state.events = response.events;
  state.sports = response.sports;
  $("#sports-count").textContent = String(state.sports.length).padStart(2, "0");
  renderSportNav();
  renderEvents();
}

function renderSportNav() {
  const entries = [{ name: "All sports", code: "ALL" }, ...state.sports.map((sport) => ({ name: sport, code: sport.slice(0, 2).toUpperCase() }))];
  $("#sport-nav").innerHTML = entries.map(({ name, code }) => `
    <button class="sport-item ${state.sport === name || (name === "All sports" && state.sport === "All") ? "active" : ""}" data-sport="${escapeHTML(name === "All sports" ? "All" : name)}" type="button">
      <span class="sport-glyph">${escapeHTML(code)}</span>${escapeHTML(name)}
    </button>`).join("");
  $$(".sport-item").forEach((button) => button.addEventListener("click", () => selectSport(button.dataset.sport)));
}

function selectSport(sport) {
  state.sport = sport;
  state.filter = "All";
  state.view = "markets";
  setView("markets");
  $$(".filter-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.filter === "All"));
  $("#page-title").innerHTML = `${escapeHTML(sport === "All" ? "All sports" : sport)} <span>markets</span>`;
  $("#breadcrumb-current").textContent = sport === "All" ? "All sports" : sport;
  refreshEvents().catch((error) => showToast(error.message));
}

function visibleEvents() {
  if (state.filter === "Other") return state.events.filter((event) => event.sport !== "Football");
  if (state.filter === "Football") return state.events.filter((event) => event.sport === "Football");
  return state.events;
}

function renderEvents() {
  const events = visibleEvents();
  $("#market-count").textContent = `${events.length} FIXTURE${events.length === 1 ? "" : "S"}`;
  if (!events.length) {
    $("#event-list").innerHTML = '<div class="no-events">No fixtures in this filter.</div>';
    return;
  }
  $("#event-list").innerHTML = events.map((event) => {
    const initialMarket = event.markets[0];
    const odds = initialMarket.outcomes.map((outcome) => oddButton(event, initialMarket, outcome)).join("");
    const extraMarkets = event.markets.slice(1).map((market) => `
      <div class="extra-market-row"><span class="extra-market-label">${escapeHTML(market.label)}</span><div class="extra-market-options">${market.outcomes.map((outcome) => oddButton(event, market, outcome)).join("")}</div></div>`).join("");
    return `<article class="event-card" data-event="${escapeHTML(event.id)}">
      <div class="event-topline"><span class="event-league"><span class="league-mark">${escapeHTML(event.sport.slice(0, 2).toUpperCase())}</span>${escapeHTML(event.league)}</span><span class="event-time">${escapeHTML(event.time)} &middot; SAMPLE</span></div>
      <div class="event-main"><div class="teams">${teamRow(event.home)}${teamRow(event.away)}</div><div class="market-options">${odds}</div></div>
      ${event.markets.length > 1 ? `<button class="market-more" data-toggle-markets="${escapeHTML(event.id)}" type="button" aria-expanded="false">More markets <span aria-hidden="true">&#8964;</span></button><div class="extra-markets hidden" id="markets-${escapeHTML(event.id)}">${extraMarkets}</div>` : ""}
    </article>`;
  }).join("");
  $$(".odd-button", $("#event-list")).forEach((button) => button.addEventListener("click", () => toggleSelection(button)));
  $$("[data-toggle-markets]", $("#event-list")).forEach((button) => button.addEventListener("click", () => {
    const panel = $(`#markets-${button.dataset.toggleMarkets}`);
    panel.classList.toggle("hidden");
    button.setAttribute("aria-expanded", String(!panel.classList.contains("hidden")));
    button.firstElementChild.textContent = panel.classList.contains("hidden") ? "⌄" : "⌃";
  }));
  updateOddStates();
}

function teamRow(name) {
  const short = name.split(/\s+/).map((part) => part[0]).join("").slice(0, 3).toUpperCase();
  return `<div class="team-row"><span class="club-mark">${escapeHTML(short)}</span>${escapeHTML(name)}</div>`;
}

function oddButton(event, market, outcome) {
  const key = `${event.id}:${market.id}`;
  const selected = state.selections.get(key)?.outcome_key === outcome.key;
  return `<button class="odd-button ${selected ? "selected" : ""}" data-event-id="${escapeHTML(event.id)}" data-market-id="${escapeHTML(market.id)}" data-outcome-key="${escapeHTML(outcome.key)}" type="button" aria-pressed="${selected}" aria-label="${escapeHTML(`${event.home} vs ${event.away}, ${market.label}: ${outcome.label}, odds ${outcome.odds}`)}"><span class="odd-name">${escapeHTML(outcome.label)}</span><span class="odd-price">${Number(outcome.odds).toFixed(2)}</span></button>`;
}

function toggleSelection(button) {
  const event = state.events.find((item) => item.id === button.dataset.eventId);
  const market = event?.markets.find((item) => item.id === button.dataset.marketId);
  const outcome = market?.outcomes.find((item) => item.key === button.dataset.outcomeKey);
  if (!event || !market || !outcome) return;
  const key = `${event.id}:${market.id}`;
  if (state.selections.get(key)?.outcome_key === outcome.key) state.selections.delete(key);
  else state.selections.set(key, { event_id: event.id, market_id: market.id, outcome_key: outcome.key, event, market, outcome });
  renderSlip();
  updateOddStates();
  if (window.matchMedia("(max-width: 900px)").matches) $("#slip-panel").classList.add("open");
}

function updateOddStates() {
  $$(".odd-button", $("#event-list")).forEach((button) => {
    const selection = state.selections.get(`${button.dataset.eventId}:${button.dataset.marketId}`);
    const selected = selection?.outcome_key === button.dataset.outcomeKey;
    button.classList.toggle("selected", Boolean(selected));
    button.setAttribute("aria-pressed", String(Boolean(selected)));
  });
}

function renderSlip() {
  const selections = [...state.selections.values()];
  const matchCount = new Set(selections.map((selection) => selection.event_id)).size;
  $("#slip-count").textContent = String(matchCount);
  $("#header-slip-count").textContent = String(matchCount);
  if (!selections.length) {
    $("#slip-selections").innerHTML = '<div class="slip-empty"><span class="empty-mark">+</span><strong>Your slip is empty</strong><p>Choose an outcome from any match to add it here.</p></div>';
  } else {
    $("#slip-selections").innerHTML = selections.map((selection) => `
      <div class="slip-selection"><button class="remove-selection" data-remove="${escapeHTML(`${selection.event_id}:${selection.market_id}`)}" type="button" aria-label="Remove ${escapeHTML(selection.outcome.label)}">&times;</button>
        <div class="slip-selection-match">${escapeHTML(selection.event.home)} vs ${escapeHTML(selection.event.away)}</div>
        <div class="slip-selection-pick">${escapeHTML(selection.outcome.label)} <strong>${Number(selection.outcome.odds).toFixed(2)}</strong></div>
        <div class="slip-selection-market">${escapeHTML(selection.market.label)}</div></div>`).join("");
    $$("[data-remove]", $("#slip-selections")).forEach((button) => button.addEventListener("click", () => {
      state.selections.delete(button.dataset.remove);
      renderSlip();
      updateOddStates();
    }));
  }
  const combined = selections.reduce((product, selection) => product * Number(selection.outcome.odds), 1);
  const oddsLabel = selections.length ? combined.toFixed(2) : "—";
  $("#combined-odds").textContent = oddsLabel;
  $("#header-slip-odds").textContent = selections.length ? `@${oddsLabel}` : oddsLabel;
  $("#slip-toggle").setAttribute("aria-label", `Open bet slip, ${matchCount} matches, ${selections.length} selections, combined odds ${oddsLabel}`);
  updatePotentialReturn();
  $(".place-bet-button").disabled = !selections.length;
}

function updatePotentialReturn() {
  const stake = Number($("#stake-input").value);
  const combined = [...state.selections.values()].reduce((product, selection) => product * Number(selection.outcome.odds), 1);
  $("#potential-return").textContent = stake > 0 && state.selections.size ? currency((stake * combined).toFixed(2)) : "—";
}

function setView(view) {
  if (view === "admin" && (state.user?.username !== "zero5" || state.user?.role !== "admin")) return;
  if (view === "account" && state.user?.username !== "zero5") return;
  state.view = view;
  $$(".content-view").forEach((section) => section.classList.toggle("hidden", section.id !== `${view}-view`));
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $("#breadcrumb-current").textContent = view === "markets" ? (state.sport === "All" ? "All sports" : state.sport) : view === "tickets" ? "My tickets" : view === "account" ? "My account" : "Admin";
  if (view === "tickets") loadHistory();
  if (view === "admin") loadAdminUsers();
}

function closeMobileNav() {
  $(".sidebar").classList.remove("mobile-open");
}

async function loadHistory() {
  try {
    const { bets } = await api("/api/bets");
    $("#ticket-history").innerHTML = bets.length ? bets.map((bet) => `
      <article class="ticket-card"><div class="ticket-head"><div><div class="ticket-id">TICKET #${escapeHTML(bet.id)}</div><div class="ticket-meta">${new Date(bet.placed_at).toLocaleString()}</div></div><span class="ticket-status">${escapeHTML(bet.status)}</span></div>
        ${bet.selections.map((selection) => `<div class="ticket-selection"><span>${escapeHTML(selection.match)}<br><small>${escapeHTML(selection.market)}</small></span><strong>${escapeHTML(selection.selection)} @ ${Number(selection.odds).toFixed(2)}</strong></div>`).join("")}
        <div class="ticket-bottom"><div><span>STAKE</span><strong>${currency(bet.stake, bet.currency)}</strong></div><div><span>COMBINED ODDS</span><strong>${Number(bet.combined_odds).toFixed(2)}</strong></div><div><span>POTENTIAL RETURN</span><strong>${currency(bet.potential_return, bet.currency)}</strong></div></div></article>`).join("") : '<div class="history-empty">No tickets yet. Choose a market to build your first one.</div>';
  } catch (error) { showToast(error.message); }
}

async function loadAdminUsers() {
  try {
    const [userData, betData, transactionData, activityData] = await Promise.all([
      api("/api/admin/users"),
      api("/api/admin/bets"),
      api("/api/admin/transactions"),
      api("/api/admin/activity"),
    ]);
    const { users } = userData;
    $("#admin-users").innerHTML = users.map((user) => {
      const balanceControl = user.username === "zero5"
        ? '<span class="admin-note">Unlimited</span>'
        : `<form class="admin-adjust" data-username="${escapeHTML(user.username)}"><select aria-label="Adjustment type"><option value="add">Add</option><option value="remove">Remove</option></select><input type="number" min="0.01" step="0.01" placeholder="Amount" aria-label="Adjustment amount" required><button class="admin-adjust-button" type="submit">Apply</button></form>`;
      const passwordControl = user.username === "zero5"
        ? '<span class="admin-note">Use My account</span>'
        : `<form class="admin-reset-password" data-username="${escapeHTML(user.username)}"><input type="password" minlength="8" placeholder="New password" aria-label="New password for ${escapeHTML(user.username)}" required><button class="admin-adjust-button" type="submit">Set</button></form>`;
      return `<tr><td><span class="admin-user"><span class="avatar">${escapeHTML(user.display_name.charAt(0).toUpperCase())}</span>${escapeHTML(user.display_name)}<small>@${escapeHTML(user.username)}</small></span></td><td><span class="role-pill ${user.role === "admin" ? "admin" : ""}">${escapeHTML(user.role)}</span></td><td><strong>${currency(user.balance, user.currency)}</strong></td><td>${user.ticket_count}</td><td>${balanceControl}</td><td>${passwordControl}</td></tr>`;
    }).join("");
    $$(".admin-adjust").forEach((form) => form.addEventListener("submit", adjustBalance));
    $$(".admin-reset-password").forEach((form) => form.addEventListener("submit", resetAccountPassword));
    renderAdminBets(betData.bets);
    renderAdminTransactions(transactionData.transactions);
    renderAdminActivity(activityData.activity);
  } catch (error) { showToast(error.message); }
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function renderAdminBets(bets) {
  $("#admin-bet-count").textContent = `${bets.length} TICKET${bets.length === 1 ? "" : "S"}`;
  $("#admin-bets").innerHTML = bets.length ? bets.map((bet) => {
    const picks = bet.selections.map((selection) => `${selection.match}: ${selection.selection} @ ${Number(selection.odds).toFixed(2)}`).join("; ");
    return `<tr><td>${escapeHTML(bet.display_name)}<small>@${escapeHTML(bet.username)}</small></td><td>${escapeHTML(formatDateTime(bet.placed_at))}</td><td><span class="admin-detail" title="${escapeHTML(picks)}">${escapeHTML(picks)}</span></td><td>${currency(bet.stake, bet.currency)}</td><td>${Number(bet.combined_odds).toFixed(2)}</td><td>${currency(bet.potential_return, bet.currency)}</td><td>${escapeHTML(bet.status)}</td></tr>`;
  }).join("") : '<tr><td colspan="7">No tickets recorded.</td></tr>';
}

function renderAdminTransactions(transactions) {
  $("#admin-transaction-count").textContent = `${transactions.length} ENTR${transactions.length === 1 ? "Y" : "IES"}`;
  $("#admin-transactions").innerHTML = transactions.length ? transactions.map((entry) => {
    const change = entry.balance_before === null ? (entry.username === "zero5" ? "Unlimited authority" : "Historical balance not reconstructed") : `${currency(entry.balance_before, entry.currency)} → ${currency(entry.balance_after, entry.currency)}`;
    return `<tr><td>${escapeHTML(formatDateTime(entry.occurred_at))}</td><td>${escapeHTML(entry.type)}</td><td>@${escapeHTML(entry.username)}</td><td>${currency(entry.amount, entry.currency)}</td><td>${escapeHTML(change)}</td><td>${escapeHTML(entry.actor)}</td><td>${escapeHTML(entry.reference || "—")}</td></tr>`;
  }).join("") : '<tr><td colspan="7">No transactions recorded.</td></tr>';
}

function renderAdminActivity(activity) {
  $("#admin-activity-count").textContent = `${activity.length} EVENT${activity.length === 1 ? "" : "S"}`;
  $("#admin-activity").innerHTML = activity.length ? activity.map((entry) => `<tr><td>${escapeHTML(formatDateTime(entry.occurred_at))}</td><td>${escapeHTML(entry.actor)}</td><td>${escapeHTML(entry.action)}</td><td>${escapeHTML(entry.target || "—")}</td><td><span class="admin-detail" title="${escapeHTML(JSON.stringify(entry.details))}">${escapeHTML(JSON.stringify(entry.details))}</span></td></tr>`).join("") : '<tr><td colspan="5">No activity recorded.</td></tr>';
}

async function adjustBalance(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const amount = $("input", form).value;
  try {
    await api("/api/admin/balance", { method: "POST", body: JSON.stringify({ username: form.dataset.username, operation: $("select", form).value, amount }) });
    showToast("Balance updated.");
    await loadAdminUsers();
    await refreshAccount();
  } catch (error) { showToast(error.message); }
}

async function resetAccountPassword(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const newPassword = $("input", formElement).value;
  try {
    await api("/api/admin/password", {
      method: "POST",
      body: JSON.stringify({ username: formElement.dataset.username, new_password: newPassword }),
    });
    formElement.reset();
    showToast(`Password reset for @${formElement.dataset.username}.`);
  } catch (error) { showToast(error.message); }
}

async function createAccount(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  try {
    const result = await api("/api/admin/users", {
      method: "POST",
      body: JSON.stringify({
        username: form.get("username"),
        display_name: form.get("display_name"),
        password: form.get("password"),
        currency: form.get("currency"),
        age_confirmed: form.get("age_confirmed") === "on",
      }),
    });
    formElement.reset();
    showToast(`Account created for @${result.user.username}. Share its initial password securely.`);
    await loadAdminUsers();
  } catch (error) { showToast(error.message); }
}

async function changePassword(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const newPassword = form.get("new_password");
  if (newPassword !== form.get("confirm_password")) {
    $("#password-message").textContent = "The new passwords do not match.";
    return;
  }
  try {
    await api("/api/password", {
      method: "POST",
      body: JSON.stringify({ current_password: form.get("current_password"), new_password: newPassword }),
    });
    formElement.reset();
    $("#password-message").textContent = "Password changed.";
  } catch (error) { $("#password-message").textContent = error.message; }
}

async function refreshAccount() {
  const data = await api("/api/session");
  if (data.user) {
    state.user = data.user;
    $("#header-balance").textContent = currency();
  }
}

async function placeBet(event) {
  event.preventDefault();
  const stake = $("#stake-input").value;
  if (!state.selections.size) return;
  try {
    const response = await api("/api/bets", {
      method: "POST",
      body: JSON.stringify({ stake, selections: [...state.selections.values()].map(({ event_id, market_id, outcome_key }) => ({ event_id, market_id, outcome_key })) }),
    });
    state.user = response.user;
    state.selections.clear();
    $("#stake-input").value = "";
    $("#slip-panel").classList.remove("open");
    $("#header-balance").textContent = currency();
    renderSlip();
    updateOddStates();
    showToast(`Ticket ${response.ticket.id} placed.`);
    if (state.view === "tickets") loadHistory();
  } catch (error) { showToast(error.message); }
}

async function handleLogin(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const result = await api("/api/login", { method: "POST", body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
    state.user = result.user;
    await startApp();
  } catch (error) { $("#auth-error").textContent = error.message; }
}

async function startApp() {
  showApp();
  setView("markets");
  await refreshEvents();
}

async function logout() {
  try {
    await api("/api/logout", { method: "POST", body: "{}" });
    const anonymousSession = await api("/api/session");
    state.csrfToken = anonymousSession.csrf_token;
  } catch (_) { /* The local session may already have expired. */ }
  state.selections.clear();
  showAuth();
}

function init() {
  $("#login-form").addEventListener("submit", handleLogin);
  $("#admin-create-form").addEventListener("submit", createAccount);
  $("#password-form").addEventListener("submit", changePassword);
  $("#slip-form").addEventListener("submit", placeBet);
  $("#stake-input").addEventListener("input", updatePotentialReturn);
  $("#clear-slip").addEventListener("click", () => { state.selections.clear(); renderSlip(); updateOddStates(); });
  $("#max-stake").addEventListener("click", () => {
    const balance = state.user?.username === "zero5" ? 100000 : Number(state.user?.balance || 0);
    $("#stake-input").value = balance.toFixed(2);
    updatePotentialReturn();
  });
  $("#logout-button").addEventListener("click", logout);
  $("#slip-toggle").addEventListener("click", () => {
    if (window.matchMedia("(max-width: 900px)").matches) $("#slip-panel").classList.toggle("open");
    else $("#slip-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  $("#close-slip").addEventListener("click", () => $("#slip-panel").classList.remove("open"));
  $("#sidebar-backdrop").addEventListener("click", closeMobileNav);
  $("[data-home]").addEventListener("click", (event) => {
    event.preventDefault();
    closeMobileNav();
    selectSport("Football");
  });
  $("#account-menu").addEventListener("click", () => showToast(`${state.user.display_name} · ${state.user.role}`));
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $$(".filter-tab").forEach((button) => button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    state.sport = state.filter === "Football" ? "Football" : "All";
    $$(".filter-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
    $("#page-title").innerHTML = `${state.sport === "All" ? "All sports" : "Football"} <span>markets</span>`;
    $("#breadcrumb-current").textContent = state.sport === "All" ? "All sports" : "Football";
    refreshEvents().catch((error) => showToast(error.message));
  }));
  $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("mobile-open"));
  document.addEventListener("click", (event) => {
    if (event.target.closest(".sidebar .nav-item, .sidebar .sport-item")) closeMobileNav();
  });
  api("/api/session").then(async (data) => {
    state.user = data.user;
    if (!state.user) return showAuth();
    const markets = await api("/api/events?sport=Football");
    state.events = markets.events;
    state.sports = markets.sports;
    await startApp();
  }).catch((error) => {
    showAuth("Could not connect to GObet. Make sure the local server is running.");
    console.error(error);
  });
}

document.addEventListener("DOMContentLoaded", init);