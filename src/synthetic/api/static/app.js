// Minimal web UI for Synthetic. It only calls the public /v1 API with the user's key,
// so everything here is also possible from the SDK, CLI and MCP server (PRD G4).
"use strict";

const EXAMPLE_DDL = `CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  first_name VARCHAR(80) NOT NULL,
  last_name VARCHAR(80) NOT NULL,
  city VARCHAR(80),
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE orders (
  id BIGSERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers (id),
  status VARCHAR(20) NOT NULL CHECK (status IN ('placed', 'shipped', 'refunded')),
  total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount > 0),
  is_fraud BOOLEAN NOT NULL DEFAULT FALSE,
  ordered_at TIMESTAMP NOT NULL,
  shipped_at TIMESTAMP,
  CHECK (shipped_at > ordered_at)
);`;

const $ = (id) => document.getElementById(id);
const state = { key: sessionStorage.getItem("synthetic_key") || "", schemaId: null, datasetId: null };
$("api-key").value = state.key;

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
}

function showError(target, err) {
  target.replaceChildren(el("p", err.message || String(err), "error"));
}

async function api(method, path, body) {
  if (!state.key) throw new Error("Paste an API key first.");
  const headers = { Authorization: `Bearer ${state.key}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method === "POST") headers["Idempotency-Key"] = crypto.randomUUID();
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const e = data.error || {};
    throw new Error(`${res.status} ${e.code || ""}: ${e.message || "request failed"} (request ${e.request_id || "?"})`);
  }
  return data;
}

function parseRows(text) {
  const rows = {};
  for (const part of text.split(",").map((p) => p.trim()).filter(Boolean)) {
    const [name, value] = part.split("=");
    if (!name || !value || isNaN(Number(value))) throw new Error(`Rows must look like table=count, got "${part}"`);
    rows[name.trim()] = Number(value);
  }
  return rows;
}

function parseScenario(text) {
  if (!text.trim()) return [];
  const idx = text.lastIndexOf("=");
  if (idx < 0) throw new Error("Rare event must look like table.column=rate, e.g. orders.is_fraud=0.02");
  return [{ type: "rare_event", column: text.slice(0, idx).trim(), rate: Number(text.slice(idx + 1)) }];
}

function badge(status) { return el("span", (status || "").replace("_", " "), `badge ${status}`); }

function renderTable(name, table) {
  const wrap = el("div", null, "table-wrap");
  wrap.append(el("h3", `${name} (${table.rows.length} rows)`));
  const t = el("table");
  const head = el("tr");
  table.columns.forEach((c) => head.append(el("th", c)));
  t.append(el("thead")); t.tHead.append(head);
  const body = el("tbody");
  table.rows.slice(0, 10).forEach((row) => {
    const tr = el("tr");
    table.columns.forEach((c) => tr.append(el("td", row[c] === null ? "" : row[c])));
    body.append(tr);
  });
  t.append(body);
  wrap.append(t);
  return wrap;
}

$("save-key").addEventListener("click", () => {
  state.key = $("api-key").value.trim();
  sessionStorage.setItem("synthetic_key", state.key);
  $("status").replaceChildren(el("p", state.key ? "Key saved for this tab." : "Key cleared."));
});

$("load-example").addEventListener("click", () => { $("ddl").value = EXAMPLE_DDL; });

$("create-schema").addEventListener("click", async () => {
  const out = $("schema-out");
  try {
    const s = await api("POST", "/v1/schemas", { ddl: $("ddl").value, dialect: $("dialect").value });
    state.schemaId = s.id;
    const list = el("ul");
    s.tables.forEach((t) => list.append(el("li", `${t.name}: ${t.columns} columns` +
      (t.foreign_keys.length ? `; FKs ${t.foreign_keys.join(", ")}` : ""))));
    out.replaceChildren(el("p", `Schema ${s.id} (version ${s.version}) created.`), list);
    s.warnings.forEach((w) => out.append(el("p", `Warning: ${w}`, "hint")));
  } catch (err) { showError(out, err); }
});

$("preview").addEventListener("click", async () => {
  const out = $("preview-out");
  try {
    if (!state.schemaId) throw new Error("Create a schema first.");
    const p = await api("POST", "/v1/previews", { schema_id: state.schemaId, seed: Number($("seed").value) || 0,
      scenarios: parseScenario($("scenario").value) });
    out.replaceChildren(...Object.entries(p.tables).map(([name, t]) => renderTable(name, t)));
  } catch (err) { showError(out, err); }
});

$("generate").addEventListener("click", async () => {
  const status = $("status");
  const button = $("generate");
  try {
    if (!state.schemaId) throw new Error("Create a schema first.");
    const formats = [...document.querySelectorAll("input[name=fmt]:checked")].map((i) => i.value);
    button.disabled = true;
    const ds = await api("POST", "/v1/datasets", { schema_id: state.schemaId, rows: parseRows($("rows").value),
      seed: Number($("seed").value) || 0, scenarios: parseScenario($("scenario").value), formats });
    state.datasetId = ds.id;
    $("progress").hidden = false;
    await poll(ds.id);
  } catch (err) { showError(status, err); } finally { button.disabled = false; }
});

async function poll(id) {
  const status = $("status");
  for (;;) {
    const ds = await api("GET", `/v1/datasets/${id}`);
    $("progress").value = ds.progress;
    status.replaceChildren(el("p", `Dataset ${ds.id}: ${ds.status} (${ds.progress}%) · seed ${ds.seed} · engine ${ds.engine_version}`));
    if (ds.status === "succeeded") { await showResults(ds); return; }
    if (ds.status === "failed") { throw new Error(`Job failed: ${ds.error.code}: ${ds.error.message}`); }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

async function showResults(ds) {
  const report = await api("GET", `/v1/datasets/${ds.id}/report`);
  const out = $("report-out");
  const head = el("p");
  head.append(el("strong", "Overall "), badge(report.overall.status),
    el("span", `  Fidelity ${report.fidelity.score}/100 `), badge(report.fidelity.status),
    el("span", "  Integrity "), badge(report.integrity.status),
    el("span", "  Privacy "), badge(report.privacy.status));
  out.replaceChildren(head, el("p", report.summary, "summary"));
  const files = await api("GET", `/v1/datasets/${ds.id}/files`);
  const list = $("files");
  list.replaceChildren();
  files.data.forEach((f) => {
    const li = el("li");
    const a = el("a", f.filename);
    a.href = f.url;
    if (f.format === "report_html") a.target = "_blank"; else a.setAttribute("download", f.filename);
    const size = f.bytes ? ` · ${(f.bytes / 1024).toFixed(1)} KB` : "";
    li.append(a, el("span", `${f.rows !== undefined ? ` · ${f.rows.toLocaleString()} rows` : ""}${size}`));
    list.append(li);
  });
}
