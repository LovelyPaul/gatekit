import { addNote } from "./notes.js";

const STORAGE_KEY = "memo-board.notes";
const root = document;

const form = root.querySelector('[data-testid="add-form"]');
const input = root.querySelector('[data-testid="note-input"]');
const list = root.querySelector('[data-testid="note-list"]');
const empty = root.querySelector('[data-testid="empty-state"]');
const error = root.querySelector('[data-testid="error-state"]');

function load() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === null) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) throw new Error("not an array");
    return parsed.filter((n) => n && typeof n.text === "string");
  } catch {
    error.hidden = false;
    return [];
  }
}

let notes = load();
const renderHooks = [];

function save() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(notes));
}

function render() {
  list.replaceChildren(
    ...notes.map((note) => {
      const li = document.createElement("li");
      li.dataset.testid = "note-item";
      li.dataset.id = note.id;
      const span = document.createElement("span");
      span.dataset.testid = "note-text";
      span.textContent = note.text;
      const del = document.createElement("button");
      del.type = "button";
      del.dataset.testid = "delete-note";
      del.textContent = "삭제";
      li.append(span, del);
      return li;
    }),
  );
  empty.hidden = notes.length > 0;
  for (const fn of renderHooks) fn(root);
}

const board = {
  root,
  getNotes: () => notes,
  setNotes(next) {
    notes = next;
    save();
    render();
  },
  onRender(fn) {
    renderHooks.push(fn);
    fn(root);
  },
};

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const next = addNote(notes, input.value);
  input.value = "";
  if (next !== notes) board.setNotes(next);
});

render();

for (const m of ["./delete-ui.js", "./count-ui.js"]) {
  import(m).then((x) => x.install(board)).catch(() => {});
}
