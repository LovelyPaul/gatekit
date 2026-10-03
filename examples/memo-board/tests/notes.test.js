import { test } from "node:test";
import assert from "node:assert/strict";
import { addNote } from "../notes.js";

test("appends a note with an id and the text", () => {
  const next = addNote([], "장보기");
  assert.equal(next.length, 1);
  assert.equal(next[0].text, "장보기");
  assert.equal(typeof next[0].id, "string");
  assert.ok(next[0].id.length > 0);
});

test("trims surrounding whitespace", () => {
  const next = addNote([], "  장보기  ");
  assert.equal(next[0].text, "장보기");
});

test("rejects blank text and returns the same array", () => {
  const notes = [{ id: "a", text: "하나" }];
  assert.equal(addNote(notes, "   "), notes);
  assert.equal(addNote(notes, ""), notes);
});

test("does not mutate the original array", () => {
  const notes = [{ id: "a", text: "하나" }];
  const next = addNote(notes, "둘");
  assert.notEqual(next, notes);
  assert.equal(notes.length, 1);
  assert.deepEqual(next.map((n) => n.text), ["하나", "둘"]);
});

test("gives distinct ids to notes added in a row", () => {
  const next = addNote(addNote([], "하나"), "둘");
  assert.notEqual(next[0].id, next[1].id);
});
