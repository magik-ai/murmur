# Flock

The live flock. `Murmur.flock(canvas, options)` draws a murmuration on a canvas and returns a handle.

Every member is a bird: two curved wings on a small body. The motion follows the StarDisplay model of starling flocks (Hildenbrandt, Carere and Hemelrijk, 2010) and field measurements of real flocks:

- A bird keeps a nearly constant speed. It never changes direction by being pushed: it turns only by banking. It rolls into a bank twice as fast as it rolls out, so its turns are slow, smooth arcs.
- It follows its seven nearest neighbours and ignores the ones behind it. It keeps clear of the closest one and drifts toward the rest, more strongly at the edge of the flock than inside.
- It reacts about fifteen times a second, not every frame, so a turn passes through the flock from neighbour to neighbour.
- A banked bird shows more wing and looks darker, so each turn sends a dark band across the flock.
- Wings beat in short bursts, with glides between.
- The only random part of the steering is a slow drift in the bank each bird wants. The area the flock circles also drifts slowly.

One bird is lit by the lamp. The colours come from `--ink` and `--lamp` (and `--accent` for the inspector), so the flock follows the theme. It runs on a fixed clock, at the same pace on a 60 Hz and a 120 Hz screen. It stops when the canvas leaves the screen, and it draws one still frame when the reader asks for reduced motion.

## Options

| Option | What it does | Default |
| --- | --- | --- |
| `count` | Number of birds, 40 to 1400 | 420 |
| `speed` | 1 is the natural pace; 0.5 is calmer | 1 |
| `seed` | The same seed gives the same first frame | 7 |
| `spacing` | 1 is a dense winter flock, 2 an airy one | 1 |
| `birdScale` | Bird size; about 1.5 for a hero seen up close | 1 |
| `roostX`, `roostY` | Centre of the area the flock circles, as fractions of the canvas | 0.5, 0.5 |
| `roostReach` | Horizontal radius of that area, as a fraction of the canvas width | 0.3 |
| `hold` | How tightly the flock keeps to that area: 0.3 circles wide, 2 stays close | 0.3 |
| `avoid` | A box `{x0, y0, x1, y1}` in fractions of the canvas, or a list of boxes, that the flock flies around, such as the page's headline | none |
| `inspect` | Point at a bird to see lines to the seven birds it watches | off |
| `onInspect` | A function called with `true` when the pointer finds a bird and `false` when it leaves | none |

The handle has `pause()`, `play()`, `running()`, `stop()`, `birds()` (the number of birds) and `neighbours` (always 7). A pause holds until `play()`, even when the canvas scrolls back into view. `stop()` also stops watching whether the canvas is on screen. A hero flock must give the reader a way to pause it, because it moves for longer than five seconds (WCAG 2.2.2).

`Murmur.mount(root)` starts every `<canvas data-mm-flock>` under `root` (the whole document by default) and returns their handles. It reads `data-count`, `data-speed`, `data-seed`, `data-spacing`, `data-bird-scale`, `data-roost-x`, `data-roost-y`, `data-roost-reach` and `data-inspect`.

## Use

Show at most one flock in view at a time, for example in a landing page hero or an empty state. Put a plain readout next to it ("360 birds, each watching its 7 nearest"). Never put it behind text a person must read, and never use it as a spinner.
