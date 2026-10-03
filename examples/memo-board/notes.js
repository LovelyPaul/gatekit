export function addNote(notes, text) {
  const trimmed = String(text ?? "").trim();
  if (!trimmed) return notes;
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  return [...notes, { id, text: trimmed }];
}
