import { removeNote } from "./remove.js";

export function install(board) {
  const list = board.root.querySelector('[data-testid="note-list"]');
  if (!list) return;
  list.addEventListener("click", (event) => {
    const button = event.target.closest('[data-testid="delete-note"]');
    if (!button) return;
    const item = button.closest('li[data-testid="note-item"]');
    if (!item) return;
    const notes = board.getNotes();
    let id = item.dataset.id;
    if (!id) {
      const index = [...list.querySelectorAll('li[data-testid="note-item"]')].indexOf(item);
      id = notes[index]?.id;
    }
    if (id === undefined) return;
    board.setNotes(removeNote(notes, id));
  });
}
