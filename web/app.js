export const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export function sortedJobs(crash, plea) {
  return [
    ...crash.map((j) => ({ ...j, kind: "crash" })),
    ...plea.map((j) => ({ ...j, kind: "plea", name: j.filename })),
  ]
    .filter((j) => !j.test)
    .sort(
      (a, b) =>
        (Date.parse(b.created) || 0) - (Date.parse(a.created) || 0) ||
        b.id.localeCompare(a.id),
    );
}
export function validateFile(file, kind) {
  if (!file || !file.name.toLowerCase().endsWith(".pdf"))
    return "Choose a PDF file.";
  if (file.size > (kind === "crash" ? 60 : 40) * 1024 * 1024)
    return `Choose a PDF smaller than ${kind === "crash" ? 60 : 40} MB.`;
  return "";
}
export function createApp(
  doc,
  {
    fetch: request = globalThis.fetch,
    url = globalThis.URL,
    now = () => Date.now(),
  } = {},
) {
  const $ = (id) => doc.getElementById(id);
  let jobs = [],
    filter = "all",
    busy = false,
    hours = 0;
  const kind = () => doc.querySelector("[name=kind]:checked").value;
  async function json(path, options) {
    const r = await request(path, options);
    let data;
    try {
      data = await r.json();
    } catch {
      throw Error("The processor could not respond. Please try again.");
    }
    if (!r.ok) throw Error(data.error || "Unable to process this request.");
    return data;
  }
  let lastMarkup = "";
  function render() {
    const visible = jobs.filter((j) => filter === "all" || j.kind === filter);
    $("count").textContent =
      `${visible.length} ${visible.length === 1 ? "document" : "documents"}`;
    const markup = visible.length
      ? visible
          .map((j) => {
            const created = Date.parse(j.created);
            const expires = created + hours * 3600000;
            const expired =
              hours > 0 && Number.isFinite(created) && expires <= now();
            const status = expired
              ? "Expired"
              : j.status === "ready"
                ? "Ready"
                : j.status === "extracting"
                  ? "Processing…"
                  : "Processing failed";
            return `<article class="job"><div><span class="job-type">${j.kind === "crash" ? "Crash report" : "Plea calendar"} · <span class="status ${j.status === "error" ? "error" : ""}">${status}</span></span><strong>${escapeHtml(j.name)}</strong><div class="job-meta"><span>${Number.isFinite(created) ? escapeHtml(new Date(created).toLocaleString()) : "Upload time unavailable"}</span>${hours && Number.isFinite(created) ? `<span>Deletes ${escapeHtml(new Date(expires).toLocaleString())}</span>` : ""}</div></div>${j.status === "ready" && !expired ? `<button class="download" data-download="${j.kind}/${escapeHtml(j.id)}">Download + proof sheet ↗</button>` : ""}</article>`;
          })
          .join("")
      : `<div class="empty"><span class="empty-number">${filter === "all" ? "01" : "—"}</span><h3>${filter === "all" ? "Ready when you are." : "No documents here yet."}</h3><p>${filter === "all" ? "Add a crash report or plea calendar.<br>Your prepared documents will appear here." : "Choose another filter or add a new document."}</p></div>`;
    if (markup === lastMarkup) return;
    lastMarkup = markup;
    $("jobs").innerHTML = markup;
    doc
      .querySelectorAll("[data-download]")
      .forEach((b) => (b.onclick = () => download(b)));
  }
  async function refresh() {
    const results = await Promise.allSettled([
      json("/crash/api/batches"),
      json("/plea/api/jobs"),
    ]);
    jobs = sortedJobs(
      ...results.map((r) => (r.status === "fulfilled" ? r.value : [])),
    );
    $("list-error").textContent = results
      .filter((r) => r.status === "rejected")
      .map((r) => r.reason.message)
      .join(" ");
    render();
  }
  async function download(button) {
    busy = true;
    button.disabled = true;
    button.textContent = "Preparing…";
    $("list-error").textContent = "";
    try {
      const r = await request(
        `/${button.dataset.download.split("/")[0]}/api/package/${button.dataset.download.split("/")[1]}`,
      );
      if (!r.ok) {
        const d = await r.json();
        throw Error(d.error || "Download failed.");
      }
      const href = url.createObjectURL(await r.blob());
      const a = doc.createElement("a");
      a.href = href;
      a.download =
        r.headers
          .get("Content-Disposition")
          ?.match(/filename="([^"]+)"/)?.[1] || `lawdocs-${now()}.zip`;
      a.click();
      setTimeout(() => url.revokeObjectURL(href), 60000);
      button.textContent = "Download again ↗";
    } catch (e) {
      $("list-error").textContent = e.message;
      button.textContent = "Try again";
    } finally {
      button.disabled = false;
      busy = false;
    }
  }
  async function upload(event) {
    event.preventDefault();
    const file = $("file").files[0];
    $("error").textContent = validateFile(file, kind());
    if ($("error").textContent) return;
    busy = true;
    $("submit").disabled = true;
    $("submit").textContent = "Uploading…";
    $("upload-status").textContent =
      "Keep this page open while your file uploads.";
    try {
      let options;
      if (kind() === "crash")
        options = {
          method: "POST",
          headers: {
            "X-Review-App": "1",
            "X-Filename": encodeURIComponent(file.name),
          },
          body: file,
        };
      else {
        const form = new FormData();
        form.append("file", file);
        options = { method: "POST", body: form };
      }
      await json(`/${kind()}/api/upload`, options);
      $("upload-status").textContent =
        "Upload received. Your document is being prepared.";
      await refresh();
    } catch (e) {
      $("error").textContent = e.message;
      $("upload-status").textContent = "";
    } finally {
      busy = false;
      $("submit").disabled = false;
      $("submit").innerHTML =
        'Prepare document <span aria-hidden="true">↗</span>';
    }
  }
  function fileChanged() {
    $("file-label").textContent = $("file").files[0]?.name || "Choose a PDF";
  }
  async function init() {
    $("upload-form").onsubmit = upload;
    $("file").onchange = fileChanged;
    doc.querySelectorAll("[data-filter]").forEach(
      (b) =>
        (b.onclick = () => {
          filter = b.dataset.filter;
          doc
            .querySelectorAll("[data-filter]")
            .forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
          render();
        }),
    );
    doc.querySelectorAll("[name=kind]").forEach(
      (r) =>
        (r.onchange = () => {
          $("limit").textContent =
            kind() === "crash"
              ? "Crash report PDFs up to 60 MB."
              : "Court calendar PDFs up to 40 MB and 60 pages.";
        }),
    );
    for (const event of ["dragover", "dragleave", "drop"])
      $("drop").addEventListener(event, (e) => {
        e.preventDefault();
        $("drop").classList.toggle("drag", event === "dragover");
        if (event === "drop" && e.dataTransfer.files.length) {
          $("file").files = e.dataTransfer.files;
          fileChanged();
        }
      });
    try {
      const health = await json("/api/health");
      hours = health.retention_hours || 0;
      if (hours)
        $("retention-note").textContent =
          `All files are deleted ${hours} hours after upload, including originals and results. Download what you need before then.`;
    } catch {
      $("list-error").textContent =
        "Service status is unavailable. Try refreshing.";
    }
    await refresh();
  }
  return { init, refresh, upload, download, render, isBusy: () => busy };
}
