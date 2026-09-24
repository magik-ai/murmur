# Field

A labelled control with one line under it that is a hint until something is wrong, and then the error.

Controls: a text input, a select (`mm-selectwrap` around a `select` draws the chevron, inset 12 px, with the text stopping 36 px short), an input with a fixed part (`mm-affix` with `mm-affix__part`: a currency before, a unit after, in the sans), a search (`mm-affix mm-affix--search`), a textarea. Every one is 36 px tall on `paper-raised` inside a `line-strong` border; focus turns the border `accent` and adds the ring; hover lifts it to `paper-high`; disabled sinks it to `paper-sunk` at `opacity-disabled`; error turns the border and the hint `danger`. Figures typed into a field use the mono (`mm-mono`).

The label says what to type in the person's words ("Your SSH public key", not "pubkey"). The hint says what a good answer looks like; the error says what was wrong and how to fix it, with no apology. A secret never goes into a field on a page.
