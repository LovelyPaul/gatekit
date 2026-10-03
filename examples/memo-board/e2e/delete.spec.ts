import { test, expect } from "@playwright/test";

test("deletes a note and keeps the deletion after reload", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  for (const text of ["하나", "둘"]) {
    await page.getByTestId("note-input").fill(text);
    await page.getByTestId("add-note").click();
  }
  await expect(page.getByTestId("note-item")).toHaveCount(2);

  await page.getByTestId("delete-note").first().click();
  await expect(page.getByTestId("note-item")).toHaveCount(1);
  await expect(page.getByTestId("note-text")).toHaveText("둘");

  await page.reload();
  await expect(page.getByTestId("note-item")).toHaveCount(1);
  await expect(page.getByTestId("note-text")).toHaveText("둘");
});
