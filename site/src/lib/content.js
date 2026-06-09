import data from "../data/thesis.json";

export const meta = data.meta;
export const sections = data.sections;

/** Prefix a path with the configured base URL (handles GitHub Pages subpath). */
export function url(path = "") {
  const base = import.meta.env.BASE_URL; // e.g. "/angelo-tese/"
  return base.replace(/\/$/, "") + "/" + String(path).replace(/^\//, "");
}

/** Path to an extracted figure/equation/cover image. */
export function figure(src) {
  return url(`figures/${src}`);
}

/**
 * Group the flat section list into reader "chapters" (one page each).
 * Returns [{ slug, number, title, head, sections: [...] }] in document order.
 * - The Preface (chapter_idx === -1) becomes its own page.
 * - Each numbered chapter collects all of its sub-sections.
 */
export function getChapters() {
  const byChapter = new Map();
  for (const s of sections) {
    const key = s.chapter_idx;
    if (!byChapter.has(key)) byChapter.set(key, []);
    byChapter.get(key).push(s);
  }
  const chapters = [];
  for (const [, group] of byChapter) {
    group.sort((a, b) => a.idx - b.idx);
    const head = group[0];
    chapters.push({
      slug: head.slug,
      number: head.number,
      title: head.title,
      head,
      sections: group,
    });
  }
  chapters.sort((a, b) => a.head.idx - b.head.idx);
  return chapters;
}

/** Adjacent-chapter navigation (prev/next). */
export function getChapterNav() {
  const chapters = getChapters();
  return chapters.map((c, i) => ({
    ...c,
    prev: i > 0 ? chapters[i - 1] : null,
    next: i < chapters.length - 1 ? chapters[i + 1] : null,
  }));
}

/** A short label like "2" or "Preface" for a chapter. */
export function chapterLabel(c) {
  return c.number ? c.number : c.title;
}
