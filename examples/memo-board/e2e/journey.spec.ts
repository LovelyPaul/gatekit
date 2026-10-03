import { test, expect } from "@playwright/test";

// 05-gate wiring criterion: F1 + F2 + F3 together (task-add-note, task-delete-note, task-note-count).
test("journey: add two notes, delete one, count shows 1", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.getByTestId("note-count")).toHaveText("메모 0개");

  await page.getByTestId("note-input").fill("첫 메모");
  await page.getByTestId("add-note").click();
  await page.getByTestId("note-input").fill("둘째 메모");
  await page.getByTestId("add-note").click();
  await expect(page.getByTestId("note-item")).toHaveCount(2);
  await expect(page.getByTestId("note-count")).toHaveText("메모 2개");

  await page.getByTestId("delete-note").first().click();
  await expect(page.getByTestId("note-item")).toHaveCount(1);
  await expect(page.getByTestId("note-text")).toHaveText(["둘째 메모"]);
  await expect(page.getByTestId("note-count")).toHaveText("메모 1개");

  await page.reload();
  await expect(page.getByTestId("note-item")).toHaveCount(1);
  await expect(page.getByTestId("note-count")).toHaveText("메모 1개");
});
