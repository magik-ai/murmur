/* Reading the stylesheet's palette the way a browser does, so contrast can be measured rather
   than eyeballed. A colour that looks fine to whoever picked it is not evidence. */

import fs from "node:fs";

const CSS = fs.readFileSync(new URL("./static/app.css", import.meta.url), "utf8");
const SUPPORTS = CSS.indexOf("@supports (color: oklch(");

/** oklch to sRGB, the same path a browser takes to paint it. */
export function oklchToRgb(lightness, chroma, hueDegrees) {
  const hue = (hueDegrees * Math.PI) / 180;
  const a = chroma * Math.cos(hue);
  const b = chroma * Math.sin(hue);
  const long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [
    4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short,
    -1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short,
    -0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short,
  ].map((value) => {
    const clamped = Math.min(1, Math.max(0, value));
    return clamped <= 0.0031308 ? 12.92 * clamped : 1.055 * clamped ** (1 / 2.4) - 0.055;
  });
}

export function parseColour(value) {
  const hex = String(value).trim().match(/^#([0-9a-f]{6})$/i);
  if (hex) return [0, 2, 4].map((index) => parseInt(hex[1].slice(index, index + 2), 16) / 255);
  const ok = String(value).trim().match(/^oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)$/);
  return ok ? oklchToRgb(Number(ok[1]), Number(ok[2]), Number(ok[3])) : null;
}

function luminance(rgb) {
  const [red, green, blue] = rgb.map((value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** The WCAG 2 contrast ratio between two colours, lighter over darker. */
export function contrast(one, other) {
  const [lighter, darker] = [luminance(one), luminance(other)].sort((left, right) => right - left);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Every token in force for one theme in one gamut, layered in source order the way the cascade
 * layers them. The sRGB fallbacks and the wide gamut refinements are both real palettes, and
 * a reader gets whichever their browser supports, so both are measured.
 */
export function tokens(theme = "light", gamut = "srgb") {
  const found = {};
  const blocks = [...CSS.matchAll(/(^|\n)\s*(:root(?:\[data-theme="dark"\])?(?::not\(\[data-theme="light"\]\))?)\s*\{([^}]*)\}/g)];
  for (const block of blocks) {
    const isDark = block[2].includes("dark") || block[2].includes("not(");
    if (isDark !== (theme === "dark")) continue;
    const refined = block.index > SUPPORTS && SUPPORTS >= 0;
    if (gamut === "srgb" && refined) continue;
    for (const declaration of block[3].match(/--[a-z0-9-]+:\s*[^;]+;/g) || []) {
      const [, name, value] = declaration.match(/--([a-z0-9-]+):\s*([^;]+);/);
      found[name] = value.trim();
    }
  }
  return found;
}
