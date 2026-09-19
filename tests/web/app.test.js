import { readFileSync } from "node:fs";
import { beforeEach, afterEach, expect, test, vi } from "vitest";
import {
  escapeHtml,
  sortedJobs,
  validateFile,
  createApp,
} from "../../web/app.js";
const html = readFileSync("web/index.html", "utf8");
const response = (value, ok = true) => ({
  ok,
  json: async () => value,
  blob: async () => new Blob(["zip"]),
  headers: new Headers({
    "Content-Disposition": 'attachment; filename="test.zip"',
  }),
});
let request, app;
beforeEach(() => {
  document.documentElement.innerHTML = html;
  request = vi.fn(async (path) =>
    response(path.includes("health") ? { retention_hours: 48 } : []),
  );
  app = createApp(document, {
    fetch: request,
    url: { createObjectURL: () => "blob:test", revokeObjectURL: vi.fn() },
    now: () => Date.parse("2026-09-18T12:00:00Z"),
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
function file(name = "test.pdf", size = 10) {
  const f = new File(["test"], name, { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: size });
  Object.defineProperty(document.getElementById("file"), "files", {
    configurable: true,
    value: [f],
  });
  return f;
}
test("escaping, stable ordering and file limits", () => {
  expect(escapeHtml("<&\"'")).toBe("&lt;&amp;&quot;&#39;");
  expect(escapeHtml(null)).toBe("");
  expect(
    sortedJobs(
      [
        { id: "a", created: "2026-01-01" },
        { id: "z", test: true },
      ],
      [{ id: "b", created: "2026-02-01", filename: "b.pdf" }],
    ).map((x) => x.id),
  ).toEqual(["b", "a"]);
  expect(sortedJobs([{ id: "a" }, { id: "b" }], [])[0].id).toBe("b");
  expect(validateFile(null, "crash")).toContain("Choose");
  expect(validateFile({ name: "bad.txt" }, "plea")).toContain("PDF");
  expect(
    validateFile({ name: "x.pdf", size: 61 * 1024 * 1024 }, "crash"),
  ).toContain("60");
  expect(
    validateFile({ name: "x.PDF", size: 41 * 1024 * 1024 }, "plea"),
  ).toContain("40");
  expect(validateFile({ name: "x.pdf", size: 1 }, "plea")).toBe("");
});
test("empty states, filters, file selection and document types", async () => {
  await app.init();
  expect(document.body.textContent).toContain("Ready when you are.");
  expect(document.body.textContent).toContain("48 hours");
  document.querySelector("[data-filter=plea]").click();
  expect(document.body.textContent).toContain("No documents here yet.");
  const radio = document.querySelector("[value=plea]");
  radio.checked = true;
  radio.onchange();
  expect(document.getElementById("limit").textContent).toContain("40 MB");
  document.querySelector("[value=crash]").checked = true;
  radio.onchange();
  expect(document.getElementById("limit").textContent).toContain("60 MB");
  file("long.pdf");
  document.getElementById("file").onchange();
  expect(document.getElementById("file-label").textContent).toBe("long.pdf");
  Object.defineProperty(document.getElementById("file"), "files", {
    value: [],
  });
  document.getElementById("file").onchange();
  for (const type of ["dragover", "dragleave", "drop"]) {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: { files: [] } });
    document.getElementById("drop").dispatchEvent(event);
  }
});
test("results show expiry, processing, error, unknown dates and escaped names", async () => {
  request.mockImplementation(async (path) =>
    response(
      path.includes("health")
        ? { retention_hours: 48 }
        : path.includes("batches")
          ? [
              {
                id: "a",
                name: "<script>name</script>",
                created: "2026-09-18T00:00:00Z",
                status: "ready",
              },
              {
                id: "b",
                name: "old",
                created: "2026-09-01T00:00:00Z",
                status: "ready",
              },
              { id: "c", name: "processing", status: "extracting" },
              { id: "d", name: "bad", status: "error" },
            ]
          : [],
    ),
  );
  await app.init();
  expect(document.querySelectorAll("[data-download]")).toHaveLength(1);
  expect(document.querySelector("#jobs script")).toBeNull();
  expect(document.body.textContent).toContain("Expired");
  expect(document.body.textContent).toContain("Processing…");
  expect(document.body.textContent).toContain("Processing failed");
});
test("both upload paths and failed uploads", async () => {
  await app.init();
  await app.upload({ preventDefault() {} });
  expect(document.getElementById("error").textContent).toContain("PDF");
  file();
  await app.upload({ preventDefault() {} });
  expect(request).toHaveBeenCalledWith(
    "/crash/api/upload",
    expect.objectContaining({ method: "POST" }),
  );
  document.querySelector("[value=plea]").checked = true;
  await app.upload({ preventDefault() {} });
  expect(request).toHaveBeenCalledWith(
    "/plea/api/upload",
    expect.objectContaining({ body: expect.any(FormData) }),
  );
  request.mockResolvedValue(response({ error: "No space" }, false));
  await app.upload({ preventDefault() {} });
  expect(document.body.textContent).toContain("No space");
  expect(app.isBusy()).toBe(false);
});
test("download success, filename fallback, expiry and network failures", async () => {
  await app.init();
  const b = document.createElement("button");
  b.dataset.download = "plea/a";
  vi.useFakeTimers();
  await app.download(b);
  expect(b.textContent).toContain("again");
  vi.runAllTimers();
  request.mockResolvedValue({ ...response({}), headers: new Headers() });
  await app.download(b);
  vi.runAllTimers();
  request.mockResolvedValue(response({ error: "Expired" }, false));
  await app.download(b);
  expect(document.body.textContent).toContain("Expired");
  request.mockResolvedValue(response({}, false));
  await app.download(b);
  expect(document.body.textContent).toContain("Download failed");
  request.mockRejectedValue(Error("Offline"));
  await app.download(b);
  expect(b.disabled).toBe(false);
});
test("invalid JSON, partial API failures and missing health", async () => {
  request.mockResolvedValue({
    ok: false,
    json: async () => {
      throw Error("bad JSON");
    },
  });
  await app.init();
  expect(document.body.textContent).toContain("could not respond");
  request.mockResolvedValue(response({}, false));
  await app.refresh();
  expect(document.body.textContent).toContain("Unable to process");
  request.mockImplementation(async (path) =>
    response(path.includes("health") ? {} : []),
  );
  await app.init();
  expect(document.querySelectorAll(".job")).toHaveLength(0);
});
