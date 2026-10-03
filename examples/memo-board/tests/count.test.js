import { test } from "node:test";
import assert from "node:assert/strict";
import { countNotes } from "../count.js";

test("counts zero notes", () => {
  assert.equal(countNotes([]), 0);
});

test("counts two notes", () => {
  assert.equal(countNotes([{ id: "a", text: "하나" }, { id: "b", text: "둘" }]), 2);
});

test("returns 0 for a non-array", () => {
  assert.equal(countNotes(undefined), 0);
  assert.equal(countNotes(null), 0);
  assert.equal(countNotes({ length: 3 }), 0);
});
