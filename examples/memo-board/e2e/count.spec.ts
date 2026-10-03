import { test, expect } from "@playwright/test";

test("shows the note count", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  await expect(page.getByTestId("note-count")).toHaveText("메모 0개");

  for (const text of ["하나", "둘"]) {
    await page.getByTestId("note-input").fill(text);
    await page.getByTestId("add-note").click();
  }
  await expect(page.getByTestId("note-count")).toHaveText("메모 2개");
});
