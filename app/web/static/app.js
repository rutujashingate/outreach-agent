"use strict";
const $ = (id) => document.getElementById(id);
let csrf = "",
  view = "overview",
  runId = null,
  page = 1,
  eventPage = 1,
  latest = null,
  currentRun = null,
  editing = null;
let loading = false,
  submittingRun = false;
function node(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (value !== undefined && value !== null) el.setAttribute(key, value);
  }
  for (const child of children.flat())
    if (child !== null && child !== undefined)
      el.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  return el;
}
const button = (text, action, cls = "") =>
  node(
    "button",
    { type: "button", class: cls, onclick: () => perform(action) },
    text,
  );
const badge = (text) =>
  node("span", { class: `badge ${text}` }, String(text).replaceAll("_", " "));
const date = (text) =>
  text
    ? new Date(text).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Unknown";
function link(url, text) {
  try {
    const u = new URL(url);
    if (!["http:", "https:"].includes(u.protocol)) throw Error();
    return node(
      "a",
      { href: u.href, target: "_blank", rel: "noopener noreferrer" },
      text || url,
    );
  } catch {
    return node("span", {}, text || url);
  }
}
function notice(text) {
  $("notice").textContent = text;
  $("notice").hidden = false;
}
async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrf,
    ...(options.headers || {}),
  };
  if (options.method && options.method !== "GET" && !headers["Idempotency-Key"])
    headers["Idempotency-Key"] = crypto.randomUUID();
  const response = await fetch(path, { ...options, headers });
  const data = await response.json();
  if (response.status === 401) {
    showLogin();
    throw Error("Sign in to continue.");
  }
  if (!response.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check the supplied information and try again.",
    );
  return data;
}
const post = (path, body = {}) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
async function perform(action) {
  try {
    await action();
  } catch (error) {
    notice(error.message);
  }
}
function showLogin() {
  $("login").hidden = false;
  $("shell").hidden = true;
  csrf = "";
}
function showShell(data) {
  csrf = data.csrf;
  $("login").hidden = true;
  $("shell").hidden = false;
  $("demo-label").textContent = data.demo ? "· SIMULATED DEMO" : "";
}
function panel(title, ...children) {
  return node(
    "section",
    { class: "panel" },
    node("h2", {}, title),
    ...children,
  );
}
function metric(label, value) {
  return node(
    "div",
    { class: "metric-row" },
    node("span", {}, label),
    node("strong", {}, value),
  );
}
function stat(label, value, description) {
  return node(
    "div",
    { class: "stat" },
    node("div", { class: "stat-label" }, label),
    node("div", { class: "stat-number" }, value),
    node("div", { class: "stat-detail" }, description),
  );
}
function runTable(data) {
  if (!data.items.length)
    return node(
      "div",
      { class: "empty" },
      "No runs yet. Start a goal in Telegram or create a new run here.",
    );
  return node(
    "div",
    { class: "table-wrap" },
    node(
      "table",
      {},
      node(
        "thead",
        {},
        node(
          "tr",
          {},
          ...["Goal", "Status", "Started", ""].map((t) => node("th", {}, t)),
        ),
      ),
      node(
        "tbody",
        {},
        ...data.items.map((r) =>
          node(
            "tr",
            {},
            node(
              "td",
              {},
              node("div", { class: "run-goal" }, r.goal),
              node("span", { class: "tiny" }, r.run_id),
            ),
            node(
              "td",
              {},
              badge(r.status),
              node(
                "span",
                { class: "tiny" },
                r.current_step.replaceAll("_", " "),
              ),
            ),
            node("td", {}, date(r.created_at)),
            node(
              "td",
              {},
              button("Open →", () => openRun(r.run_id)),
            ),
          ),
        ),
      ),
    ),
  );
}
async function changeView(next) {
  view = next;
  runId = null;
  page = 1;
  $("notice").hidden = true;
  await refresh();
  window.scrollTo(0, 0);
}
async function openRun(id) {
  view = "detail";
  runId = id;
  eventPage = 1;
  await refresh();
  window.scrollTo(0, 0);
}
function pagination(number, total, size, change) {
  return node(
    "div",
    { class: "pagination" },
    button("← Previous", () => change(Math.max(1, number - 1))),
    node(
      "span",
      { class: "muted" },
      `Page ${number} of ${Math.max(1, Math.ceil(total / size))}`,
    ),
    button("Next →", () =>
      change(Math.min(Math.max(1, Math.ceil(total / size)), number + 1)),
    ),
  );
}
async function refresh() {
  if (!csrf || loading) return;
  loading = true;
  try {
    document
      .querySelectorAll("nav button")
      .forEach((b) =>
        b.classList.toggle(
          "active",
          b.dataset.view === (view === "detail" ? "runs" : view),
        ),
      );
    let content;
    if (view === "detail") {
      currentRun = await api(`/api/runs/${runId}?event_page=${eventPage}`);
      content = renderDetail(currentRun);
      $("page-title").textContent = "Run details";
    } else if (view === "runs") {
      const data = await api(`/api/runs?page=${page}`);
      content = panel(
        "All outreach runs",
        runTable(data),
        pagination(page, data.total, 20, async (n) => {
          page = n;
          await refresh();
        }),
      );
      $("page-title").textContent = "Runs & approvals";
    } else {
      latest = await api("/api/overview");
      content =
        view === "connections"
          ? renderConnections(latest.connections)
          : renderOverview(latest);
      $("page-title").textContent =
        view === "connections" ? "Connections" : "Overview";
      $("sidebar-status").textContent = latest.queue_paused
        ? "Queue paused"
        : latest.worker_busy
          ? "Agent working"
          : "Agent ready";
    }
    $("content").replaceChildren(content);
    $("updated").textContent =
      "Updated " +
      new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } finally {
    loading = false;
  }
}
function renderOverview(data) {
  const s = data.stats;
  return node(
    "div",
    {},
    node(
      "div",
      { class: "stats" },
      stat(
        "Outreach runs",
        s.runs,
        `${s.running} running · ${s.queued} queued`,
      ),
      stat(
        "Needs your approval",
        s.pending_approvals,
        `${s.paused} paused runs`,
      ),
      stat("Gmail drafts created", s.drafts, "Confirmed Gmail actions"),
      stat("Emails sent", s.sent, "Confirmed Gmail actions"),
    ),
    node(
      "div",
      { class: "two-col" },
      panel(
        "Research & results",
        metric("Prospects found", s.prospects),
        metric("Qualified prospects", s.qualified),
        metric("Completed runs", s.completed),
        metric("Failed runs", s.failed),
        metric("Replies processed", s.replies),
      ),
      panel(
        "Usage & activity",
        metric("Model calls", s.model_calls),
        metric(
          "Search calls / browser pages",
          `${s.search_calls} / ${s.browser_pages}`,
        ),
        metric(
          "Reported tokens",
          s.token_usage_available ? s.tokens.toLocaleString() : "Not reported",
        ),
        metric("Estimated model cost", `$${s.estimated_cost.toFixed(2)}`),
        node(
          "p",
          { class: "muted" },
          "Estimates use your configured per-call reservation. They are not your provider’s bill.",
        ),
      ),
    ),
    node(
      "section",
      { class: "panel" },
      node(
        "div",
        { class: "panel-head" },
        node("h2", {}, "Recent runs"),
        node(
          "div",
          { class: "actions" },
          badge(data.queue_paused ? "paused" : "ready"),
          button(
            data.queue_paused ? "Resume queue" : "Pause queue",
            async () => {
              await api("/api/queue", {
                method: "PUT",
                body: JSON.stringify({ paused: !data.queue_paused }),
              });
              await refresh();
            },
          ),
        ),
      ),
      runTable(data.recent_runs),
    ),
    panel(
      "Recent background jobs",
      node(
        "p",
        { class: "muted" },
        `${data.job_counts.running || 0} running · ${data.job_counts.completed || 0} completed · ${data.job_counts.failed || 0} failed · ${data.job_counts.interrupted || 0} interrupted`,
      ),
      ...data.jobs
        .slice(0, 8)
        .map((j) =>
          node(
            "div",
            { class: "job-row" },
            node(
              "span",
              {},
              j.kind.replaceAll("_", " "),
              node("span", { class: "tiny" }, j.run_id || "Reply check"),
            ),
            node(
              "span",
              {},
              badge(j.status),
              j.error ? node("span", { class: "tiny" }, j.error) : null,
            ),
          ),
        ),
    ),
  );
}
function renderConnections(c) {
  const card = (icon, title, status, description, actions = []) =>
    panel(
      "",
      node(
        "div",
        { class: "connection" },
        node("div", { class: "connection-icon" }, icon),
        node(
          "div",
          { class: "connection-body" },
          node("h3", {}, title, badge(status)),
          node("p", {}, description),
          node("div", { class: "actions" }, ...actions),
        ),
      ),
    );
  const gmail = c.gmail;
  const gmailActions = c.demo
    ? []
    : [
        button(
          gmail.connected ? "Reconnect Google" : "Connect Google",
          async () => {
            const r = await post("/api/connectors/gmail/connect");
            location.assign(r.url);
          },
          "primary",
        ),
      ];
  if (gmail.connected && !c.demo)
    gmailActions.push(
      button(
        "Disconnect",
        async () => {
          if (
            confirm(
              "Disconnect Gmail and stop pending actions from using this account?",
            )
          ) {
            await post("/api/connectors/gmail/disconnect");
            await refresh();
          }
        },
        "danger",
      ),
    );
  if (gmail.connected)
    gmailActions.push(
      button("Check replies", async () => {
        await post("/api/replies/check");
        notice("Reply check queued.");
      }),
    );
  const profile = node(
    "form",
    {
      class: "panel form-card",
      onsubmit: async (e) => {
        e.preventDefault();
        await perform(async () => {
          const f = new FormData(e.target);
          await api("/api/profile", {
            method: "PUT",
            body: JSON.stringify({
              name: f.get("name"),
              email: f.get("email") || null,
              context: f.get("context"),
            }),
          });
          notice("Sender profile saved. Telegram will reuse it.");
        });
      },
    },
    node("h2", {}, "Your sender profile"),
    node(
      "p",
      { class: "muted" },
      "Facts the agent may use when writing. Gmail actions use the connected account.",
    ),
    node(
      "label",
      {},
      "Name",
      node("input", {
        name: "name",
        required: "",
        value: c.sender_profile.name || "User",
      }),
    ),
    node(
      "label",
      {},
      "Email",
      node("input", {
        name: "email",
        type: "email",
        value: gmail.email || c.sender_profile.email || "",
      }),
    ),
    node(
      "label",
      {},
      "Background or offering",
      node("textarea", { name: "context" }, c.sender_profile.context || ""),
    ),
    node("button", { class: "primary", type: "submit" }, "Save profile"),
  );
  return node(
    "div",
    {},
    card(
      "G",
      "Gmail",
      gmail.health || "disconnected",
      gmail.email ||
        "Connect your Google account to read conversations and create approved messages.",
      gmailActions,
    ),
    node(
      "div",
      { class: "two-col" },
      card(
        "T",
        "Telegram",
        c.telegram.health,
        c.telegram.username
          ? "@" + c.telegram.username
          : "Configure your bot token and owner ID to connect.",
      ),
      card(
        "↗",
        "Research tools",
        c.browser.available ? "connected" : "unavailable",
        `Browser: ${c.browser.available ? "ready" : "Chromium not available"}. Brave search: ${c.search.configured ? "configured" : "not configured"}.`,
      ),
    ),
    card(
      "M",
      "Model provider",
      c.model.configured ? "configured" : "not configured",
      c.model.provider +
        " · configuration presence only; credentials are checked when used",
    ),
    profile,
  );
}
function renderDetail(data) {
  const state = data.state;
  const controls = [];
  if (data.status === "failed")
    controls.push(
      button("Retry", async () => {
        await post(`/api/runs/${runId}/retry`);
        await refresh();
      }),
    );
  if (!["completed", "cancelled"].includes(data.status))
    controls.push(
      button(
        "Cancel run",
        async () => {
          if (
            confirm(
              "Stop further work on this run? An action already underway will record its result.",
            )
          ) {
            await post(`/api/runs/${runId}/cancel`);
            await refresh();
          }
        },
        "danger",
      ),
    );
  const cards = [
    node(
      "section",
      { class: "panel" },
      node(
        "div",
        { class: "run-header" },
        node(
          "div",
          {},
          node("p", { class: "eyebrow" }, state.run_id),
          node("h2", { class: "small-title" }, state.goal),
          node(
            "div",
            { class: "pill-row" },
            badge(data.status),
            badge(data.current_step),
          ),
        ),
        node("div", { class: "actions" }, ...controls),
      ),
      data.error ? node("p", {}, data.error) : null,
      node(
        "p",
        { class: "muted" },
        `${data.usage.model_calls} model calls · ${data.usage.search_calls} searches · ${data.metadata?.browser_calls || 0} browser pages · $${data.usage.estimated_cost.toFixed(2)} estimated`,
      ),
    ),
  ];
  if (data.awaiting_recipients) cards.push(recipientForm(state));
  for (const item of state.approval_requests) {
    if (!data.awaiting_approval) break;
    const choice = data.choices[item.prospect.id];
    const decision = (action) => ({
      prospect_id: item.prospect.id,
      version: item.version,
      fingerprint: item.fingerprint,
      action,
    });
    const select = async (action) => {
      await post(`/api/runs/${runId}/choices`, decision(action));
      await refresh();
    };
    cards.push(
      panel(
        item.prospect.company_name,
        node(
          "p",
          {},
          `From: ${state.sender.name} <${state.sender.email || "not configured"}>`,
        ),
        node(
          "p",
          {},
          `To: ${item.recipient.email} · Version ${item.version} · Action: ${state.gmail_action}`,
        ),
        node(
          "p",
          { class: "muted" },
          "Address source: ",
          link(item.recipient.source),
          item.recipient.evidence_quote
            ? node("span", {}, " — ", item.recipient.evidence_quote)
            : null,
        ),
        node("h3", {}, item.draft.subject),
        node("div", { class: "draft" }, item.draft.body),
        node(
          "p",
          { class: "muted" },
          `Automated review: ${state.reviews[item.prospect.id]?.approved ? "passed" : "needs attention"} · score ${state.reviews[item.prospect.id]?.score ?? "unavailable"}`,
        ),
        node("h3", {}, "Research evidence"),
        node(
          "ul",
          { class: "source-list" },
          ...item.research_summary.map((s) =>
            node("li", {}, s.startsWith("http") ? link(s) : s),
          ),
        ),
        node(
          "div",
          { class: "actions" },
          button(
            `Approve ${state.gmail_action}`,
            () => select("approve"),
            "primary",
          ),
          button("Reject", () => select("reject")),
          button("Edit", () => {
            editing = { runId, decision: decision("edit") };
            const form = $("edit-form");
            form.elements.subject.value = item.draft.subject;
            form.elements.body.value = item.draft.body;
            $("edit-dialog").showModal();
          }),
          choice
            ? badge(choice.action + " selected")
            : node("span", { class: "muted" }, "No decision yet"),
        ),
      ),
    );
  }
  if (data.awaiting_approval)
    cards.push(
      panel(
        "Submit your decisions",
        node(
          "p",
          {},
          `${Object.keys(data.choices).length} of ${state.approval_requests.length} drafts have a choice. Submitting resumes this same run. Approved messages use the action shown on each draft.`,
        ),
        button(
          "Submit decisions",
          async () => {
            await post(`/api/runs/${runId}/submit`);
            notice("Decisions submitted.");
            await refresh();
          },
          "primary",
        ),
      ),
    );
  if (Object.keys(state.outcomes).length)
    cards.push(
      panel(
        "Outcomes",
        ...Object.entries(state.outcomes).map(([pid, o]) =>
          node(
            "div",
            { class: "metric-row" },
            node(
              "span",
              {},
              state.prospects.find((p) => p.id === pid)?.company_name || pid,
            ),
            node(
              "div",
              {},
              badge(o.status),
              node(
                "span",
                { class: "tiny" },
                o.reason || o.external_id || "Recorded",
              ),
            ),
          ),
        ),
      ),
    );
  if (!data.awaiting_approval && Object.keys(state.drafts).length)
    cards.push(
      panel(
        "Saved messages and reviews",
        ...Object.entries(state.drafts).map(([pid, draft]) => {
          const review = state.reviews[pid],
            decision = state.human_decisions[pid];
          return node(
            "details",
            {},
            node("summary", {}, draft.subject),
            node(
              "p",
              {},
              `To: ${state.recipients[pid]?.email || "unresolved"} · Version ${state.draft_versions[pid]}`,
            ),
            node("div", { class: "draft" }, draft.body),
            node(
              "p",
              { class: "muted" },
              review
                ? `Review: ${review.approved ? "passed" : "needs attention"} · score ${review.score}`
                : "Review pending",
            ),
            node(
              "ul",
              {},
              ...(review?.issues || []).map((issue) => node("li", {}, issue)),
            ),
            node(
              "p",
              {},
              decision
                ? `Your decision: ${decision.action}`
                : "No final decision",
            ),
          );
        }),
      ),
    );
  cards.push(
    panel(
      "Prospects & sources",
      state.prospects.length
        ? node(
            "div",
            {},
            ...state.prospects.map((p) =>
              node(
                "div",
                {},
                node("h3", {}, p.company_name),
                node("p", { class: "muted" }, p.signals.join(" · ")),
                node(
                  "ul",
                  { class: "source-list" },
                  ...p.sources.map((s) => node("li", {}, link(s))),
                ),
              ),
            ),
          )
        : node("p", { class: "muted" }, "Research results will appear here."),
      ...state.pages.map((p) =>
        node(
          "details",
          {},
          node(
            "summary",
            {},
            p.title || p.url,
            p.error ? " · Unavailable" : "",
          ),
          node("p", {}, link(p.url)),
          node("p", { class: "muted" }, "Retrieved " + date(p.retrieved_at)),
          node("div", { class: "draft" }, p.error || p.text),
        ),
      ),
    ),
  );
  cards.push(
    panel(
      "Execution log",
      node(
        "div",
        { class: "log-list" },
        ...data.events.map((e) =>
          node(
            "details",
            { class: "log-row" },
            node(
              "summary",
              {},
              date(e.timestamp) +
                " · " +
                e.event.replaceAll("_", " ") +
                (e.node ? " · " + e.node.replaceAll("_", " ") : ""),
            ),
            node(
              "pre",
              { class: "log" },
              JSON.stringify(
                Object.fromEntries(
                  Object.entries(e).filter(
                    ([k]) => !["timestamp", "event"].includes(k),
                  ),
                ),
                null,
                2,
              ),
            ),
          ),
        ),
      ),
      pagination(eventPage, data.event_total, 50, async (n) => {
        eventPage = n;
        await refresh();
      }),
    ),
  );
  return node("div", {}, ...cards);
}
function recipientForm(state) {
  const form = node(
    "form",
    {
      class: "panel",
      onsubmit: async (e) => {
        e.preventDefault();
        await perform(async () => {
          const recipients = {};
          for (const pid of state.recipient_requests) {
            const selected = form.elements["choice-" + pid].value;
            const email =
              selected === "manual"
                ? form.elements["email-" + pid].value
                : selected;
            recipients[pid] =
              email === "skip"
                ? null
                : { email, source: "Explicitly selected by the owner" };
          }
          await post(`/api/runs/${runId}/recipients`, { recipients });
          await refresh();
        });
      },
    },
    node("h2", {}, "Choose recipients"),
    node(
      "p",
      {},
      "Choose a published address, enter one you know, or skip the prospect.",
    ),
  );
  for (const pid of state.recipient_requests) {
    const candidates = state.recipient_candidates[pid] || [];
    const select = node(
      "select",
      { name: "choice-" + pid },
      ...candidates.map((r) => node("option", { value: r.email }, r.email)),
      node("option", { value: "manual" }, "Enter an address"),
      node("option", { value: "skip" }, "Skip this prospect"),
    );
    form.append(
      node(
        "label",
        {},
        state.prospects.find((p) => p.id === pid)?.company_name || pid,
        select,
      ),
      node("input", {
        name: "email-" + pid,
        type: "email",
        placeholder: "Address you can explicitly supply",
      }),
      node(
        "ul",
        { class: "source-list" },
        ...candidates.map((r) =>
          node("li", {}, r.email + " — ", link(r.source)),
        ),
      ),
    );
  }
  form.append(
    node(
      "button",
      { class: "primary", type: "submit" },
      "Save recipients and continue",
    ),
  );
  return form;
}
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("password").value }),
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail);
    $("password").value = "";
    showShell(data);
    await refresh();
  } catch (e) {
    $("login-error").textContent = e.message;
  }
});
document
  .querySelectorAll("nav button")
  .forEach((b) =>
    b.addEventListener("click", () =>
      perform(() => changeView(b.dataset.view)),
    ),
  );
$("logout").addEventListener("click", () =>
  perform(async () => {
    await post("/auth/logout");
    showLogin();
  }),
);
$("new-run").addEventListener("click", () =>
  perform(async () => {
    const c = await api("/api/connectors");
    const form = $("run-form");
    form.elements.name.value = c.sender_profile.name || "User";
    form.elements.email.value = c.gmail.email || c.sender_profile.email || "";
    form.elements.context.value = c.sender_profile.context || "";
    form.elements.search.checked = c.search.configured;
    form.elements.browser.checked = c.browser.available;
    form.elements.action.querySelector("[value=send]").disabled =
      !c.gmail.sending_enabled;
    if (c.demo) {
      form.elements.goal.value =
        "Find professors studying AI observability for PhD outreach.";
      form.elements.urls.value = "https://example.com/lab";
    }
    $("run-error").textContent = "";
    $("run-dialog").showModal();
  }),
);
$("close-run").addEventListener("click", () => $("run-dialog").close());
$("close-edit").addEventListener("click", () => $("edit-dialog").close());
// Keep the request key when a response is lost, so trying again finds the
// same saved job. Editing the request creates a new intentional submission.
let pendingRun = null;
$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submittingRun) return;
  submittingRun = true;
  const submit = event.target.querySelector("[type=submit]");
  submit.disabled = true;
  try {
    const f = event.target.elements;
    const recipients = {};
    for (const line of f.recipients.value
      .split("\n")
      .filter((line) => line.trim())) {
      const [target, email, extra] = line
        .split("|")
        .map((value) => value.trim());
      if (!target || !email || extra !== undefined)
        throw Error("Use Target | email for each known recipient.");
      recipients[target] = { email };
    }
    const body = JSON.stringify({
      recipients,
      goal: f.goal.value,
      sender: {
        name: f.name.value,
        email: f.email.value || null,
        context: f.context.value,
      },
      seed_urls: f.urls.value.split(/\s+/).filter(Boolean),
      research_material: f.notes.value,
      use_search: f.search.checked,
      use_browser: f.browser.checked,
      discover_emails: f.discover.checked,
      gmail_action: f.action.value,
    });
    if (!pendingRun || pendingRun.body !== body)
      pendingRun = { body, key: crypto.randomUUID() };
    const job = await api("/api/runs", {
      method: "POST",
      body,
      headers: { "Idempotency-Key": pendingRun.key },
    });
    pendingRun = null;
    $("run-dialog").close();
    await openRun(job.run_id);
    notice("Run queued. You can follow its progress here or in Telegram.");
  } catch (e) {
    $("run-error").textContent = e.message;
  } finally {
    submittingRun = false;
    submit.disabled = false;
  }
});
$("edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await perform(async () => {
    const f = event.target.elements;
    await post(`/api/runs/${editing.runId}/choices`, {
      ...editing.decision,
      edited_draft: {
        prospect_id: editing.decision.prospect_id,
        subject: f.subject.value,
        body: f.body.value,
      },
    });
    $("edit-dialog").close();
    await refresh();
  });
});
setInterval(() => {
  if (
    !document.hidden &&
    !$("run-dialog").open &&
    !$("edit-dialog").open &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)
  )
    perform(refresh);
}, 5000);
(async () => {
  try {
    const data = await api("/auth/session");
    showShell(data);
    await refresh();
  } catch {
    showLogin();
  }
})();
