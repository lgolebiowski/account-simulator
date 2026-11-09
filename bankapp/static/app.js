"use strict";

// Plain JavaScript, no framework. All text from the server is put on the page with
// textContent (never as HTML), so a name like "<script>" can't run as code.

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "bank.token";
const ROLE_KEY = "bank.role"; // "customer" or "admin"

// sessionStorage can throw (blocked storage, private modes), so wrap it.
const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } },
  clear() { try { sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(ROLE_KEY); } catch { /* ignore */ } },
};

// ------------------------------------------------------------------ helpers

function showMessage(text, kind) {
  const el = $("message");
  if (!text) { el.hidden = true; el.textContent = ""; return; }
  el.textContent = text;
  el.className = "message " + (kind === "ok" ? "ok" : "err");
  el.hidden = false;
}

const VIEWS = ["view-guest", "view-admin-login", "view-customer", "view-admin"];
function showView(id) {
  for (const v of VIEWS) $(v).hidden = v !== id;
  $("logout").hidden = id !== "view-customer" && id !== "view-admin";
}

// "1500.35" -> "$1,500.35". String work only, so no floating-point surprises.
function money(value) {
  const text = String(value);
  const sign = text.startsWith("-") ? "-" : "";
  const [whole, cents = "00"] = text.replace("-", "").split(".");
  return sign + "$" + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + cents.padEnd(2, "0");
}

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = store.get(TOKEN_KEY);
  if (auth && token) headers["Authorization"] = "Bearer " + token;

  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new Error("Can't reach the bank. Check your connection and try again.");
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);

  if (!res.ok) {
    if (res.status === 401 && auth && token) {
      // The session ended (it expires after 30 minutes).
      endSession("Your session has ended. Please log in again.");
      throw new Error("");
    }
    // Our own errors carry a readable string; validation errors (422) are lists.
    const detail = data && typeof data.detail === "string" ? data.detail : "Please check what you entered and try again.";
    throw new Error(detail);
  }
  return data;
}

// Disable a form's button while its request runs; show any error as a message.
async function run(form, work) {
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  showMessage("");
  try {
    await work();
  } catch (err) {
    if (err.message) showMessage(err.message, "err");
  } finally {
    button.disabled = false;
  }
}

function endSession(message) {
  store.clear();
  showView("view-guest");
  showMessage(message || "", message ? "err" : "");
}

// Accept 12, 12.5, 12.50 - the server enforces the rest.
function checkAmount(raw) {
  const text = raw.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(text)) {
    throw new Error("Enter an amount like 25 or 25.50.");
  }
  return text;
}

// ---------------------------------------------------------------- customer

// "2026-03-10T12:00:00+11:00" -> "2026-03-10 12:00". The server already sends business-timezone
// time, so we cut the text instead of converting it with the browser's own timezone.
const stamp = (iso) => iso.slice(0, 10) + " " + iso.slice(11, 16);

function cell(row, text, className) {
  const td = row.insertCell();
  td.textContent = text;
  if (className) td.className = className;
}

function renderStatement(data) {
  const body = $("stmt-body");
  body.replaceChildren();
  const lines = [...data.transactions].reverse(); // newest first on screen
  for (const t of lines) {
    const row = body.insertRow();
    let details = t.type;
    if (t.other_account) details += (t.type === "Transfer out" ? " to " : " from ") + t.other_account;
    const incoming = !t.amount.startsWith("-");
    cell(row, stamp(t.time));
    cell(row, details);
    cell(row, (incoming ? "+" : "") + money(t.amount), "num " + (incoming ? "pos" : ""));
    cell(row, money(t.balance), "num");
  }
  $("stmt-table").hidden = lines.length === 0;
  $("stmt-empty").hidden = lines.length !== 0;
}

// useInputs=false asks the server for its default range (last 30 days) and fills the dates in.
async function loadStatement(useInputs) {
  let query = "";
  if (useInputs) {
    const start = $("stmt-start").value, end = $("stmt-end").value;
    if (!start || !end) throw new Error("Choose both a From and a To date.");
    query = "?start=" + encodeURIComponent(start) + "&end=" + encodeURIComponent(end);
  }
  const data = await api("/statement" + query);
  $("stmt-start").value = data.start;
  $("stmt-end").value = data.end;
  renderStatement(data);
}

// The CSV needs our login header, so a plain link won't do: fetch it, then save the blob.
async function downloadCsv() {
  const start = $("stmt-start").value, end = $("stmt-end").value;
  if (!start || !end) throw new Error("Choose both a From and a To date.");
  const res = await fetch("/statement.csv?start=" + encodeURIComponent(start) +
                          "&end=" + encodeURIComponent(end),
                          { headers: { Authorization: "Bearer " + store.get(TOKEN_KEY) } });
  if (!res.ok) {
    if (res.status === 401) { endSession("Your session has ended. Please log in again."); throw new Error(""); }
    const data = await res.json().catch(() => null);
    throw new Error(data && typeof data.detail === "string" ? data.detail : "Couldn't download the statement.");
  }
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "statement-" + start + "-to-" + end + ".csv";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function loadDashboard() {
  const [me, bal] = await Promise.all([api("/me"), api("/balance")]);
  $("who").textContent = me.owner + " · account " + me.number;
  $("balance").textContent = money(bal.balance);
  showView("view-customer");
  await loadStatement(false);
}

// After money moves, refresh the table. A failure here must not hide the success message.
async function refreshStatement() {
  try { await loadStatement(true); } catch { /* the table just stays as it was */ }
}

async function startSession(token, role) {
  store.set(TOKEN_KEY, token);
  store.set(ROLE_KEY, role);
  if (role === "admin") showView("view-admin");
  else await loadDashboard();
}

// ------------------------------------------------------------------- wiring

function selectTab(which) {
  const login = which === "login";
  $("tab-login").setAttribute("aria-selected", String(login));
  $("tab-open").setAttribute("aria-selected", String(!login));
  $("panel-login").hidden = !login;
  $("panel-open").hidden = login;
  showMessage("");
}
$("tab-login").addEventListener("click", () => selectTab("login"));
$("tab-open").addEventListener("click", () => selectTab("open"));

$("show-admin").addEventListener("click", () => { showMessage(""); showView("view-admin-login"); });
$("back-to-guest").addEventListener("click", () => { showMessage(""); showView("view-guest"); });

$("panel-login").addEventListener("submit", (e) => {
  e.preventDefault();
  run(e.target, async () => {
    const { token } = await api("/login", {
      method: "POST", auth: false,
      body: { number: $("login-number").value.trim(), pin: $("login-pin").value },
    });
    $("login-pin").value = "";
    await startSession(token, "customer");
  });
});

$("panel-open").addEventListener("submit", (e) => {
  e.preventDefault();
  run(e.target, async () => {
    const acct = await api("/accounts", {
      method: "POST", auth: false,
      body: { owner: $("open-owner").value, pin: $("open-pin").value },
    });
    $("open-owner").value = "";
    $("open-pin").value = "";
    $("login-number").value = acct.number;
    selectTab("login");
    showMessage("Account created. Your account number is " + acct.number +
                ". Keep it safe - you need it to log in.", "ok");
    $("login-pin").focus();
  });
});

$("admin-login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(e.target, async () => {
    const { token } = await api("/admin/login", {
      method: "POST", auth: false,
      body: { username: $("admin-user").value.trim(), password: $("admin-pass").value },
    });
    $("admin-pass").value = "";
    await startSession(token, "admin");
  });
});

function moneyForm(formId, inputId, path, verb) {
  $(formId).addEventListener("submit", (e) => {
    e.preventDefault();
    run(e.target, async () => {
      const amount = checkAmount($(inputId).value);
      const result = await api(path, { method: "POST", body: { amount } });
      $(inputId).value = "";
      $("balance").textContent = money(result.balance);
      showMessage(verb + " " + money(amount) + ".", "ok");
      await refreshStatement();
    });
  });
}
moneyForm("deposit-form", "deposit-amount", "/deposit", "Deposited");
moneyForm("withdraw-form", "withdraw-amount", "/withdraw", "Withdrew");

$("transfer-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(e.target, async () => {
    const to = $("transfer-to").value.trim();
    if (!/^\d{10}$/.test(to)) throw new Error("Enter the recipient's 10-digit account number.");
    const amount = checkAmount($("transfer-amount").value);
    const result = await api("/transfer", { method: "POST", body: { to, amount } });
    $("transfer-to").value = "";
    $("transfer-amount").value = "";
    $("balance").textContent = money(result.balance);
    showMessage("Sent " + money(amount) + " to account " + to + ".", "ok");
    await refreshStatement();
  });
});

$("statement-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(e.target, () => loadStatement(true));
});

$("stmt-csv").addEventListener("click", async (e) => {
  const button = e.currentTarget;
  button.disabled = true;
  showMessage("");
  try { await downloadCsv(); } catch (err) { if (err.message) showMessage(err.message, "err"); }
  finally { button.disabled = false; }
});

$("unlock-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(e.target, async () => {
    const number = $("unlock-number").value.trim();
    await api("/admin/accounts/" + encodeURIComponent(number) + "/unlock", { method: "POST" });
    $("unlock-number").value = "";
    showMessage("Account " + number + " is unlocked.", "ok");
  });
});

$("logout").addEventListener("click", async () => {
  try { await api("/logout", { method: "POST" }); } catch { /* the session is going away either way */ }
  endSession();
});

// -------------------------------------------------------------------- start

(async function init() {
  const token = store.get(TOKEN_KEY);
  const role = store.get(ROLE_KEY);
  if (!token || !role) return showView("view-guest");
  try {
    await startSession(token, role);
  } catch (err) {
    if (err.message) endSession(err.message);
  }
})();
