import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
});

test("adds a note and keeps it after reload", async ({ page }) => {
  await expect(page.getByTestId("empty-state")).toBeVisible();

  await page.getByTestId("note-input").fill("장보기");
  await page.getByTestId("add-note").click();

  await expect(page.getByTestId("note-item")).toHaveCount(1);
  await expect(page.getByTestId("note-text")).toHaveText("장보기");
  await expect(page.getByTestId("note-input")).toHaveValue("");
  await expect(page.getByTestId("empty-state")).toBeHidden();

  await page.reload();
  await expect(page.getByTestId("note-item")).toHaveCount(1);
  await expect(page.getByTestId("note-text")).toHaveText("장보기");
});

test("adds a note with Enter", async ({ page }) => {
  await page.getByTestId("note-input").fill("장보기");
  await page.getByTestId("note-input").press("Enter");
  await expect(page.getByTestId("note-item")).toHaveCount(1);
});

test("ignores whitespace-only input", async ({ page }) => {
  await page.getByTestId("note-input").fill("장보기");
  await page.getByTestId("add-note").click();
  await expect(page.getByTestId("note-item")).toHaveCount(1);

  await page.getByTestId("note-input").fill("   ");
  await page.getByTestId("add-note").click();
  await expect(page.getByTestId("note-item")).toHaveCount(1);
});

test("shows the error state when stored notes are corrupt", async ({ page }) => {
  await page.evaluate(() => localStorage.setItem("memo-board.notes", "{not json"));
  await page.reload();
  await expect(page.getByTestId("error-state")).toBeVisible();
  await expect(page.getByTestId("empty-state")).toBeVisible();
});
