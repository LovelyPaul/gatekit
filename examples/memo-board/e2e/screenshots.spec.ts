import { test, expect } from "@playwright/test";

// 05-gate screenshot criterion: one capture per UI task (ADR-0017 decision 9).
test("screenshots: build-<task-id>.png for every UI task", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  await page.getByTestId("note-input").fill("장보기");
  await page.getByTestId("add-note").click();
  await page.getByTestId("note-input").fill("회의록 정리");
  await page.getByTestId("add-note").click();
  await expect(page.getByTestId("note-item")).toHaveCount(2);
  await page.screenshot({ path: "spec/design/build-task-add-note.png", fullPage: true });

  await expect(page.getByTestId("note-count")).toHaveText("메모 2개");
  await page.screenshot({ path: "spec/design/build-task-note-count.png", fullPage: true });

  await page.getByTestId("delete-note").first().click();
  await expect(page.getByTestId("note-item")).toHaveCount(1);
  await page.screenshot({ path: "spec/design/build-task-delete-note.png", fullPage: true });
});
