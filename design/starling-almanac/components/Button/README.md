# Button

A button says exactly what it does. A button that spends money says how much.

- Primary (`mm-button`): the action the view exists for, one per view. `accent` fill, `on-accent` text, `accent-hover` under the pointer.
- Quiet (`mm-button mm-button--quiet`): every other action. A `line-strong` border, `ink` text, `paper-sunk` under the pointer.
- Small (`mm-button--small`): inside table rows and cards, so the row stays one line.
- Lamp (`mm-button--lamp`): a rare warm action that wakes something, such as resuming the farm. At most one on a screen.
- Disabled: the `disabled` attribute plus a `title` that says why, in the server's own words. A switched-off control stays visible.

Write the price into a button that buys something ("Create, $48 a month until you destroy it"), and repeat it on the confirm step. Do not add arrows, do not write "Submit" or "OK", and do not put two primary buttons side by side.

You provide the label and the click handler. A press scales the button to 0.97 in 120 ms. Nothing else moves, and nothing casts a shadow.
