# Button

Buttons say exactly what they do, and the one that spends money says how much.

- Primary (`mm-button`): one per view, the action the page exists for. Accent fill, `on-accent` text, `accent-hover` under the pointer.
- Quiet (`mm-button mm-button--quiet`): every other action. A `line-strong` border, `ink` text, `paper-sunk` under the pointer.
- Small (`mm-button--small`): inside table rows and cards, where a row stays one line.
- Lamp (`mm-button--lamp`): the rare warm action that wakes something (resume the farm). Never more than one on a screen.
- Disabled: the `disabled` attribute plus a `title` that says why, in the server's own words. A switched-off control never hides.

Do write the price into a buying button ("Create, $48 a month until you destroy it") and repeat it on the confirm. Don't append arrows, don't write "Submit" or "OK", don't put two primaries side by side.

The consumer provides the label and the handler. Pressing scales to 0.97 for 120 ms; nothing else moves, and nothing casts a shadow.
