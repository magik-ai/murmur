# LimitBar

One usage window of a subscription: its name, a bar, and the percent in mono, on one line.

Use `mm-limit` with `mm-limit__name`, `mm-limit__rail` (holding an `mm-limit__fill` whose width is the percent) and `mm-limit__pct`. The fill is `accent` below 70 percent. From 70 percent, set `data-tone="wait"` (`warning`). From 95 percent, set `data-tone="fail"` (`danger`). The percent takes the same colour as the fill.

Show every window the account has, including windows that apply to one model only. If a spent window is hidden, the account looks fine when it is not.

You provide the name, the percent and the tone.
