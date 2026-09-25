/* One code name, one mark. The glyph and the colour come from the server's registry, so an
   initiator looks the same on a card, in a mail thread and in the palette. Nothing about
   identity is decided here except what to do when the registry has never heard of a name. */

let registry = {};

export function setRegistry(payload) {
  registry = payload && typeof payload === "object" ? payload : {};
}

export function known(name) {
  return Boolean(name && registry[name]);
}

export function names() {
  return Object.keys(registry).sort();
}

function hash(text) {
  let value = 2166136261;
  for (const character of String(text)) {
    value ^= character.codePointAt(0);
    value = Math.imul(value, 16777619) >>> 0;
  }
  return value;
}

/** How many marks the page has. A name is given one of them, never a colour of its own. */
export const TONES = 12;

/** Which of the twelve a seed lands on. The same seed always lands on the same one. */
export function tone(seed) {
  return hash(String(seed || "")) % TONES;
}

/* A glyph is drawn as text, so a long one is a long line of text and not a decision the page
   has to make at layout time. Two characters is a mark; four hundred is a paragraph. */
function glyphOf(value, fallback) {
  const written = [...String(value ?? "").trim()].slice(0, 2).join("");
  return written || fallback;
}

/**
 * The mark for a code name: whatever the registry says, or a readable stand-in. The stand-in
 * is the first letter, never an invented emoji that later disagrees with the server. The
 * colour is a number, not a colour: a value that arrives from a server picks one of the
 * page's own twelve and nothing else, so a registry can never write a declaration into a page.
 */
export function mark(name) {
  const key = String(name || "").trim();
  const entry = registry[key];
  if (entry) {
    return {
      glyph: glyphOf(entry.icon || entry.glyph, key.slice(0, 1).toUpperCase() || "?"),
      tone: tone(entry.color || key),
      registered: true,
    };
  }
  if (!key) return { glyph: String.fromCharCode(183), tone: 0, registered: false };
  return { glyph: key.slice(0, 1).toUpperCase(), tone: tone(key), registered: false };
}
