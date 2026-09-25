# Status

A state is a mark and a word in the state's own colour. There is no bubble and no fill.

- `data-tone="done"`: a check in `success`. Ready, Delivered, Passed, Logged in.
- `data-tone="wait"`: a ring in `warning`. Needs your login, Waiting on a person, Not tested.
- `data-tone="fail"`: a cross in `danger`. Failing, Out of room.
- `data-tone="info"`: a small bird in flight, in `info`. Running, Preparing, Creating.
- `data-tone="accent"`: a half moon in `accent`. A limit that applies to one model only ("Fable used up"): it matters, but it is not a failure.
- `data-tone="live"`: a lamp dot beside a word in `ink`. The one live thing on a card.
- No tone: two bars in `ink-muted`. Off, Paused.

Every state has its own shape, so it reads without colour. Use one status per row or card, with two or three words in sentence case. Put the full sentence in the `title`.
