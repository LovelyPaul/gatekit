import { countNotes } from "./count.js";

export function install(board) {
  board.onRender((root) => {
    const el = root.querySelector('[data-testid="note-count"]');
    if (el) el.textContent = `메모 ${countNotes(board.getNotes())}개`;
  });
}
