import { test } from "node:test";
import assert from "node:assert/strict";
import { removeNote } from "../remove.js";

const notes = [
  { id: "a", text: "하나" },
  { id: "b", text: "둘" },
];

test("removes only the note with the given id", () => {
  assert.deepEqual(removeNote(notes, "a"), [{ id: "b", text: "둘" }]);
});

test("does not mutate the original array", () => {
  const next = removeNote(notes, "a");
  assert.notEqual(next, notes);
  assert.equal(notes.length, 2);
});

test("returns a new array with the same contents for an unknown id", () => {
  const next = removeNote(notes, "zzz");
  assert.notEqual(next, notes);
  assert.deepEqual(next, notes);
});
