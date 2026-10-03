export function removeNote(notes, id) {
  return notes.filter((note) => note.id !== id);
}
