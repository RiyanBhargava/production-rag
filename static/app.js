"use strict";
const el = (id) => document.getElementById(id);
let selectedFile = null;
let lastAnswer = "";
let busy = false;

function status(id, message, kind = "") {
  el(id).textContent = message;
  el(id).className = `inline-status ${kind}`;
}

async function api(path, options = {}, responseType = "json") {
  if (!el("key").value.trim())
    throw new Error("Enter your application API key and connect first.");
  const response = await fetch(path, {
    ...options,
    headers: { "X-API-Key": el("key").value.trim(), ...options.headers },
  });
  if (response.ok && responseType === "text") return response.text();
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      `The service returned an unexpected response (${response.status}).`,
    );
  }
  if (!response.ok) {
    if (response.status === 401)
      throw new Error(
        "That API key was not accepted. Check your application key.",
      );
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check your input and try again.",
    );
  }
  return data;
}

async function run(buttonId, statusId, work) {
  if (busy) return;
  busy = true;
  const button = el(buttonId),
    original = button.textContent;
  ["connect", "upload", "ask", "list", "check-health", "load-metrics"].forEach((id) => {
    el(id).disabled = true;
  });
  document.querySelectorAll("[data-document-action]").forEach((action) => { action.disabled = true; });
  el("key").disabled = true;
  button.textContent = "Working…";
  status(statusId, "Working…");
  try {
    await work();
  } catch (error) {
    status(statusId, error.message, "error");
  } finally {
    busy = false;
    button.textContent = original;
    ["connect", "upload", "ask", "list", "check-health", "load-metrics"].forEach((id) => {
      el(id).disabled = false;
    });
    document.querySelectorAll("[data-document-action]").forEach((action) => { action.disabled = false; });
    el("key").disabled = false;
  }
}

function chooseFile(file) {
  selectedFile = file || null;
  el("file-label").textContent = file ? file.name : "Choose a document";
  el("file-description").textContent = file
    ? `${(file.size / 1024).toFixed(1)} KiB · selected, not yet uploaded`
    : "or drop a file here";
  status(
    "upload-status",
    file
      ? `Selected ${file.name}. Click Upload document to store it.`
      : "Choose a document to begin.",
  );
}

function renderDocuments(documents) {
  el("documents").replaceChildren();
  el("document-count").textContent = String(documents.length);
  for (const doc of documents) {
    const row = document.createElement("div");
    row.className = "document-row";
    const icon = document.createElement("span");
    icon.className = "document-icon";
    icon.textContent = doc.filename.split(".").pop().slice(0, 3).toUpperCase();
    const info = document.createElement("div");
    const name = document.createElement("div");
    name.className = "document-name";
    name.textContent = doc.filename;
    const meta = document.createElement("div");
    meta.className = "document-meta";
    meta.textContent = `Version ${doc.version} · ${doc.category} · ${new Date(doc.created_at).toLocaleDateString()}`;
    info.append(name, meta);
    const actions = document.createElement("div");
    actions.className = "document-actions";
    const active = document.createElement("span");
    active.className = "document-active";
    active.textContent = doc.active ? "Active" : "Historical";
    const focus = document.createElement("button");
    focus.type = "button";
    focus.className = "button quiet";
    focus.textContent = doc.active ? "Ask about this" : "Ask this version";
    focus.dataset.documentAction = "query";
    focus.addEventListener("click", () => {
      el("filename-filter").value = doc.filename;
      el("filter").value = doc.category;
      el("version-filter").value = doc.active ? "" : doc.version;
      el("question").focus();
      el("query-form").scrollIntoView({ behavior: "smooth", block: "center" });
      status(
        "status",
        `Search focused on ${doc.filename}, ${doc.active ? "latest upload" : `version ${doc.version}`}.`,
      );
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button quiet danger";
    remove.dataset.documentAction = "delete";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => {
      if (busy || !window.confirm(`Delete ${doc.filename}, version ${doc.version}? This removes this document version and its stored passages.`)) return;
      run("list", "library-status", async () => {
        await api(`/documents/${encodeURIComponent(doc.id)}`, { method: "DELETE" });
        await refreshLibrary();
        clearAnswer();
        if (el("filename-filter").value === doc.filename && el("version-filter").value === doc.version) el("version-filter").value = "";
        status("library-status", `Deleted ${doc.filename}, version ${doc.version}.`, "success");
        status("status", "Document removed. Ask again to use the remaining evidence.");
      });
    });
    actions.append(active, focus, remove);
    row.append(icon, info, actions);
    el("documents").append(row);
  }
  status(
    "library-status",
    documents.length
      ? `${documents.length} document version${documents.length === 1 ? "" : "s"} in this workspace.`
      : "No documents yet. Upload your first source above.",
  );
}
async function refreshLibrary() {
  renderDocuments(await api("/documents"));
}

el("connect-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run("connect", "connection-status", async () => {
    await refreshLibrary();
    status(
      "connection-status",
      "Connected. Your document library is ready.",
      "success",
    );
  });
});
el("key").addEventListener("input", () => {
  el("documents").replaceChildren();
  el("document-count").textContent = "0";
  clearAnswer();
  el("metrics-output").textContent = "";
  el("metrics-output").hidden = true;
  status("metrics-status", "Connect first to view request counts and latency.");
  status("connection-status", "Key changed. Connect to load this workspace.");
  status("library-status", "Connect to see your documents.");
  status("status", "");
  el("filter").value = "";
  el("filename-filter").value = "";
  el("version-filter").value = "";
});
el("file").addEventListener("change", () => chooseFile(el("file").files[0]));
["dragenter", "dragover"].forEach((name) =>
  el("dropzone").addEventListener(name, (event) => {
    event.preventDefault();
    el("dropzone").classList.add("drag-over");
  }),
);
["dragleave", "drop"].forEach((name) =>
  el("dropzone").addEventListener(name, (event) => {
    event.preventDefault();
    el("dropzone").classList.remove("drag-over");
    if (name === "drop") chooseFile(event.dataTransfer.files[0]);
  }),
);
el("upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run("upload", "upload-status", async () => {
    if (!selectedFile) throw new Error("Choose a document first.");
    if (!/\.(pdf|txt|md)$/i.test(selectedFile.name))
      throw new Error("Choose a PDF, TXT, or Markdown file.");
    if (selectedFile.size > 10 * 1024 * 1024)
      throw new Error("The default upload limit is 10 MiB.");
    const body = new FormData();
    body.append("file", selectedFile);
    body.append("version", el("version").value.trim());
    body.append("category", el("category").value.trim());
    const result = await api("/documents", { method: "POST", body });
    status(
      "upload-status",
      `${result.deduplicated ? "Already stored" : "Uploaded"}: ${result.filename} · version ${result.version} · ${result.category}${result.deduplicated ? "" : ` · ${result.chunks} chunks`}.`,
      "success",
    );
    el("filename-filter").value = result.filename;
    el("filter").value = result.category;
    el("version-filter").value = "";
    el("file-description").textContent = "Stored in your workspace";
    try {
      await refreshLibrary();
    } catch {
      status(
        "library-status",
        "Upload succeeded. Refresh the library to view it.",
      );
    }
  });
});
el("list").addEventListener("click", () =>
  run("list", "library-status", refreshLibrary),
);
el("question").addEventListener("input", () => {
  el("character-count").textContent = `${el("question").value.length} / 2000`;
});
document.querySelectorAll("[data-question]").forEach((button) =>
  button.addEventListener("click", () => {
    el("question").value = button.dataset.question;
    el("question").dispatchEvent(new Event("input"));
    el("question").focus();
  }),
);

function clearAnswer() {
  el("answer").textContent = "";
  el("answer").hidden = true;
  el("sources").replaceChildren();
  el("answer-empty").hidden = false;
  el("answer-meta").hidden = true;
  el("routing-panel").hidden = true;
  el("query-details").hidden = true;
  el("query-request").textContent = "";
  el("query-response").textContent = "";
  el("copy").disabled = true;
  lastAnswer = "";
}

function renderAnswer(data, seconds) {
  lastAnswer = data.answer;
  el("answer-empty").hidden = true;
  el("answer").hidden = false;
  el("answer").textContent = data.answer;
  el("copy").disabled = false;
  el("answer-meta").hidden = false;
  el("answer-meta").className =
    `badge ${data.insufficient_evidence ? "neutral" : "success"}`;
  el("answer-meta").textContent =
    `${data.mode === "demo" ? "Demo excerpts" : data.mode === "ollama" ? "Local model" : data.mode === "gemini" ? "Gemini" : "Hosted model"} · ${data.cached ? "cached" : `${seconds.toFixed(1)}s`}`;
  if (data.model_used) {
    el("answer-meta").textContent += ` \u00b7 ${data.model_used}`;
    el("answer-meta").title = data.routing?.enabled
      ? `Route: ${data.routing.reason}${data.routing.fallback ? ` \u00b7 fallback: ${data.routing.fallback_reason}` : ""}`
      : "Configured answer model";
  }
  const routing = data.routing || {};
  const reasons = {
    factual_lookup: "Factual lookup",
    synthesis_or_reasoning: "Comparison, synthesis, or reasoning",
    multiple_documents: "Evidence from multiple documents",
    large_context: "Large evidence context",
    conservative_default: "Conservative model selection",
    no_evidence: "No evidence available",
    malformed_output: "The initial model returned an invalid response",
    abstention_with_positive_retrieval: "The initial model abstained despite positive retrieval",
  };
  el("routing-panel").hidden = false;
  el("routing-policy").textContent = routing.enabled ? "Automatic selection" : "Configured model";
  el("routing-initial").textContent = routing.enabled
    ? `${routing.tier === "light" ? "Lightweight" : routing.tier === "strong" ? "Larger" : "No generation"} \u00b7 ${routing.model || "None"}`
    : data.model_used || "Default";
  el("routing-final").textContent = data.model_used || "None";
  el("routing-request").textContent = data.cached ? "Cache hit" : `Fresh \u00b7 ${seconds.toFixed(1)}s`;
  const reason = reasons[routing.reason] || routing.reason || "Using the configured answer model";
  const fallback = routing.fallback ? ` Escalated: ${reasons[routing.fallback_reason] || routing.fallback_reason}.` : "";
  el("routing-reason").textContent = `${reason}.${fallback}${data.cached ? " Reused a previous answer; no model ran for this request." : ""}`;
  el("sources").replaceChildren();
  if (data.citations.length) {
    const title = document.createElement("p");
    title.className = "sources-title";
    title.textContent = `SUPPORTING SOURCES · ${data.citations.length}`;
    el("sources").append(title);
  }
  for (const citation of data.citations) {
    const source = document.createElement("details");
    source.className = "source";
    const summary = document.createElement("summary");
    summary.textContent = `[${citation.source_id}] ${citation.filename}`;
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = `Page ${citation.page} · ${citation.section.trim() || "Section unspecified"} · version ${citation.version}`;
    const excerpt = document.createElement("pre");
    excerpt.textContent = citation.excerpt;
    summary.append(meta);
    source.append(summary, excerpt);
    el("sources").append(source);
  }
  status(
    "status",
    data.insufficient_evidence
      ? "No supported answer was produced. Check the selected document and filters, or ask a more specific question."
      : "Answer ready. Expand a source to inspect the supporting passage.",
    data.insufficient_evidence ? "" : "success",
  );
}
el("query-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run("ask", "status", async () => {
    const question = el("question").value.trim();
    if (question.length < 3)
      throw new Error("Enter a question with at least three characters.");
    const filters = {};
    if (el("filter").value.trim()) filters.category = el("filter").value.trim();
    if (el("filename-filter").value.trim())
      filters.filename = el("filename-filter").value.trim();
    if (el("version-filter").value.trim()) filters.version = el("version-filter").value.trim();
    clearAnswer();
    el("answer-empty").hidden = true;
    status(
      "status",
      "Searching your documents and preparing a grounded answer…",
    );
    const start = performance.now();
    const request = { question, filters };
    const data = await api("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    renderAnswer(data, (performance.now() - start) / 1000);
    el("query-request").textContent = JSON.stringify(request, null, 2);
    el("query-response").textContent = JSON.stringify(data, null, 2);
    el("query-details").hidden = false;
  });
});
el("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(lastAnswer);
    status("status", "Answer copied.", "success");
  } catch {
    status(
      "status",
      "Clipboard access was denied. Select the answer text to copy it.",
    );
  }
});
(async () => {
  try {
    const response = await fetch("/health/ready");
    if (!response.ok) throw new Error("Unavailable");
    const health = await response.json();
    el("service-status").className = "badge success";
    el("service-status").textContent =
      `${health.mode === "ollama" ? "Local AI" : health.mode === "demo" ? "Demo" : health.mode === "gemini" ? "Gemini" : "Hosted AI"} · ${health.storage === "postgres" ? "PostgreSQL" : "Chroma"} · Ready`;
  } catch {
    el("service-status").className = "badge error";
    el("service-status").textContent = "Service unavailable";
  }
})();


el("check-health").addEventListener("click", () =>
  run("check-health", "health-status", async () => {
    el("health-output").hidden = true;
    const results = {};
    let ready = true;
    for (const name of ["live", "ready"]) {
      const response = await fetch(`/health/${name}`);
      results[name] = { http_status: response.status, ...await response.json() };
      if (!response.ok) ready = false;
    }
    el("health-output").textContent = JSON.stringify(results, null, 2);
    el("health-output").hidden = false;
    status("health-status", ready ? "Process and dependencies are available." : "A health check failed. Inspect the response below.", ready ? "success" : "error");
  }),
);
el("load-metrics").addEventListener("click", () =>
  run("load-metrics", "metrics-status", async () => {
    el("metrics-output").hidden = true;
    const metrics = await api("/metrics", {}, "text");
    const appMetrics = metrics.split("\n").filter((line) => line.startsWith("rag_") || line.startsWith("# HELP rag_")).join("\n");
    el("metrics-output").textContent = appMetrics || "No application metrics yet.";
    el("metrics-output").hidden = false;
    status("metrics-status", "Request counts and latency buckets from the API process. Reload after more requests.", "success");
  }),
);
