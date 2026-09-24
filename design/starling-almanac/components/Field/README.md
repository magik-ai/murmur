# Field

A labelled control with one line under it. The line is a hint until something is wrong, and then it is the error.

Use `mm-field` around a `label`, the control and an `mm-field__hint`. The controls are:

- a text input;
- a select, wrapped in `mm-selectwrap`, which draws a 12 px chevron 12 px from the right edge (the text stops 36 px from that edge);
- an input with a fixed part: `mm-affix` with an `mm-affix__part` before it (a currency) or after it (a unit), set in the sans;
- a search: `mm-affix mm-affix--search`;
- a textarea.

Inputs and selects are 36 px tall, and a textarea starts at 88 px. All of them sit on `paper-raised` inside a `line-strong` border. Focus turns the border `accent` and adds the focus ring. Hover lifts the control to `paper-high`. Disabled sinks it to `paper-sunk` at `opacity-disabled`. `data-state="error"` on the field turns the border and the hint `danger`. Figures typed into a field use the mono (`mm-mono`).

The label says what to type, in the person's words ("Your SSH public key", not "pubkey"). The hint says what a good answer looks like. The error says what was wrong and how to fix it, without apologising. A secret never goes into a field on a page.
