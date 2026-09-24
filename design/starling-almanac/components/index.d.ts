// murmur, Starling Almanac. Most of the system is CSS classes (bundle.css, prefix mm-);
// two pieces move and live on window.Murmur.

export interface FlockOptions {
  /** Birds to draw, 40 to 1400. Default 420; the hero takes 900 at most. */
  count?: number;
  /** 1 is the natural pace; 0.5 for a quiet empty state. */
  speed?: number;
  /** Same seed, same first frame. */
  seed?: number;
}

export interface FlockHandle {
  stop(): void;
  birds(): number;
  /** Always 7: the topological rule measured on starlings. */
  neighbours: number;
}

export interface MurmurNamespace {
  /** Draw a murmuration on a canvas; colours from --ink and --lamp. */
  flock(canvas: HTMLCanvasElement, options?: FlockOptions): FlockHandle;
  /** Start every canvas[data-mm-flock] under root (data-count, data-speed, data-seed). */
  mount(root?: ParentNode): FlockHandle[];
  NEIGHBOURS: 7;
  version: string;
}

declare global {
  interface Window { Murmur: MurmurNamespace; }
}

// The CSS vocabulary, for reference:
// mm-root, mm-display, mm-stipple
// mm-button [--quiet | --small | --lamp]
// mm-status [data-tone = done | wait | fail | info | accent | live]  (a mark and a word, no fill)
// mm-tag, mm-bird, mm-segmented > button[aria-pressed], mm-tabs > [aria-selected], mm-iconbutton
// mm-selectwrap > select, mm-affix [--search] > mm-affix__part + input, mm-check, mm-radio, mm-switch
// mm-choices > mm-choice[aria-checked] > mm-choice__title, mm-choice__meta, mm-choice__note
// mm-link, mm-kbd, mm-inline-code
// mm-limit [data-tone = wait | fail] > mm-limit__name, mm-limit__rail > mm-limit__fill, mm-limit__pct
// mm-tiles > mm-tile > mm-tile__label, mm-tile__value, mm-tile__note
// mm-table-wrap > mm-table (td.mm-num for figures)
// mm-card > mm-card__head (mm-card__title, mm-spacer, mm-status), mm-card__meta, mm-card__body
// mm-field [data-state = error] > label, input | select, mm-field__hint
// mm-command > mm-command__prompt, code, mm-button--small
// mm-banner, mm-steps > mm-step [data-state = done] > mm-step__no, mm-step__title, mm-step__text, mm-step__body
// mm-drawer > mm-drawer__head (mm-drawer__title, mm-drawer__sub), mm-drawer__body
// mm-nav > a[aria-current=page] (svg, mm-count), mm-empty > mm-empty__title, mm-empty__body
// mm-wordmark, mm-gather (seven <i>, each a bird), mm-plate > canvas.mm-flock[data-mm-flock], mm-readout, mm-ribbon
export {};
