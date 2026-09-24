# Design

`starling-almanac/` holds murmur's design system, the Starling Almanac. It sets the colours,
type, spacing, components and motion of the landing page (`site/`) and the dashboard
(`fleet/dashboard/`). Start with [its README](starling-almanac/README.md), which has the rules.

| Path | What it holds |
| --- | --- |
| `starling-almanac/README.md` | The rules: principles, voice, colour, type, space, motion, icons, controls |
| `starling-almanac/tokens.json` | Every token, its value in the Lamplight (light) and Dusk (dark) themes, and what it is for |
| `starling-almanac/components/murmur.css` | The component classes, all prefixed `mm-` |
| `starling-almanac/components/flock.js` | The animated flock, as `window.Murmur` |
| `starling-almanac/components/index.d.ts` | TypeScript declarations for `window.Murmur`, and a list of the CSS classes |
| `starling-almanac/components/<Name>/` | One folder per component: `README.md` with its rules, and `preview.html`, a small example |
| `starling-almanac/logos/` | The mark for light and dark grounds, and the Python scripts that draw it |

How the files are used:

- The landing page uses copies of `murmur.css` and `flock.js`, in `site/assets/`. Change the
  design system first, then copy the files there.
- `site/assets/tokens.css` holds the values from `tokens.json` as CSS custom properties. No
  script generates it, so a token change goes into both files.
- The dashboard does not load these files. Its own stylesheet,
  `fleet/dashboard/static/app.css`, uses the same colour values under its own token names.
- The previews do not load a stylesheet or a script themselves. They expect the page around
  them to supply `tokens.css`, `murmur.css` and, for the flock, `flock.js`. The comment on the
  first line of each preview is metadata for a design-system viewer, such as the card's group,
  height and subtitle.
- `logos/draw_mark.py` draws `murmur-mark.svg` and `murmur-mark-dusk.svg`. Run it from
  `logos/` with `python3 draw_mark.py`.
