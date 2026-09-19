import { test, expect } from "@playwright/test";
test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { retention_hours: 48 } }),
  );
  await page.route("**/crash/api/batches", (route) =>
    route.fulfill({
      json: [
        {
          id: "a".repeat(32),
          name: "Example municipal report — September review.pdf",
          created: new Date().toISOString(),
          status: "ready",
        },
        {
          id: "b".repeat(32),
          name: "Second report.pdf",
          created: new Date().toISOString(),
          status: "extracting",
        },
      ],
    }),
  );
  await page.route("**/plea/api/jobs", (route) =>
    route.fulfill({
      json: [
        {
          id: "c".repeat(32),
          filename: "Example court calendar.pdf",
          created: new Date(Date.now() - 3600000).toISOString(),
          status: "error",
        },
      ],
    }),
  );
});
test("documents, filters, focus and download", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Document workspace." }),
  ).toBeVisible();
  await expect(page.getByText("48 hours", { exact: false })).toBeVisible();
  await expect(page.locator(".job")).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "Download + proof sheet" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Plea calendars", exact: true })
    .click();
  await expect(page.locator(".job")).toHaveCount(1);
  await page.getByRole("button", { name: "All documents" }).click();
  await page.route("**/crash/api/package/*", (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="synthetic.zip"',
      },
      body: "PKsynthetic",
    }),
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download + proof sheet" }).click();
  expect((await download).suggestedFilename()).toBe("synthetic.zip");
  await page.screenshot({
    path: `test-results/workspace-${test.info().project.name}.png`,
    fullPage: true,
  });
  await page.locator("#file").focus();
  await page.keyboard.press("Tab");
  await expect(page.locator("#submit")).toBeFocused();
});
test("upload receipt and error state", async ({ page }) => {
  await page.route("**/crash/api/upload", (route) =>
    route.fulfill({ status: 202, json: { id: "d".repeat(32) } }),
  );
  await page.goto("/");
  await page.locator("#file").setInputFiles({
    name: "synthetic.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 synthetic"),
  });
  await page.getByRole("button", { name: "Prepare document" }).click();
  await expect(page.getByRole("status")).toContainText("Upload received");
  await page.route("**/crash/api/upload", (route) =>
    route.fulfill({
      status: 400,
      json: { error: "Unsupported PDF. Please try another document." },
    }),
  );
  await page.getByRole("button", { name: "Prepare document" }).click();
  await expect(page.locator("#error")).toContainText("Unsupported PDF");
});
