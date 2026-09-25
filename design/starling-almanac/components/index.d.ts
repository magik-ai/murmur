// murmur, Starling Almanac. Most of the system is CSS classes (murmur.css, prefix mm-);
// two pieces move and live on window.Murmur.

/** A box in fractions of the canvas, from 0 to 1. */
export interface FlockBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface FlockOptions {
  /** Birds to draw, 40 to 1400. Default 420. */
  count?: number;
  /** 1 is the natural pace; 0.5 is calmer. Default 1. */
  speed?: number;
  /** The same seed gives the same first frame. Default 7. */
  seed?: number;
  /** 1 is a dense winter flock, 2 an airy one. Default 1. */
  spacing?: number;
  /** Bird size; about 1.5 for a hero seen up close. Default 1. */
  birdScale?: number;
  /** Centre of the area the flock circles, as a fraction of the canvas width. Default 0.5. */
  roostX?: number;
  /** Centre of the area the flock circles, as a fraction of the canvas height. Default 0.5. */
  roostY?: number;
  /** Horizontal radius of that area, as a fraction of the canvas width. Default 0.3. */
  roostReach?: number;
  /** How tightly the flock keeps to that area: 0.3 circles wide, 2 stays close. Default 0.3. */
  hold?: number;
  /** A box, or a list of boxes, that the flock flies around, such as a headline. */
  avoid?: FlockBox | FlockBox[];
  /** Point at a bird to see lines to the seven birds it watches. Default off. */
  inspect?: boolean;
  /** Called with true when the pointer finds a bird and false when it leaves. */
  onInspect?: (found: boolean) => void;
}

export interface FlockHandle {
  /** Stop until play() is called, even when the canvas scrolls back into view. */
  pause(): void;
  play(): void;
  running(): boolean;
  /** Stop, and stop watching whether the canvas is on screen. */
  stop(): void;
  birds(): number;
  /** Always 7: the topological rule measured on starlings. */
  neighbours: number;
}

export interface MurmurNamespace {
  /** Draw a murmuration on a canvas; colours from --ink and --lamp. */
  flock(canvas: HTMLCanvasElement, options?: FlockOptions): FlockHandle;
  /** Start every canvas[data-mm-flock] under root (the whole document by default). Reads
      data-count, data-speed, data-seed, data-spacing, data-bird-scale, data-roost-x,
      data-roost-y, data-roost-reach and data-inspect. */
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
