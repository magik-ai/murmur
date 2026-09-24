murmur runs many coding agents as one team, the way a murmuration moves thousands of starlings: no leader, each bird watching its seven nearest neighbours, and a shape that no single bird draws. The system is called the Starling Almanac: an old almanac read by lamplight, with star charts, moon tables and engraved birds. The structure is scientific (tables, figures in mono, a rule you can state); the finish is warm and a little magical (candle paper, plum ink like a starling's sheen, one lamp-lit bird).

## Principles

- **The flock is the product.** Show the team as many small things moving together, and always beside a plain table that says the same thing in words. The flock is for feeling the work; the table is for reading it.
- **Warm, never soft on facts.** Candle paper and pastel fields, but figures are exact, prices are named before they are spent, and a state is always a mark and a word.
- **Birds, never dots.** Wherever the flock appears (the mark, the hero, the loader, a divider, a status), its members are birds with wings.
- **No shadows, no square corners.** Depth comes from the paper steps and hairlines only, and every surface, control and field is rounded from the radius scale.
- **Spend boldness once.** One flock, one lamp-lit bird, one primary button per view. Everything around them stays quiet.
- **Seven is the house number.** Seven birds round the lit one in the mark and the loader, seven neighbours in the flock, at most seven avatars in a stack. It is the rule measured on real starlings, and it is the one playful thing the system repeats.

## Voice

Write the way a good lab notebook reads: plain verbs, sentence case, no exclamation marks, no emoji, no em-dash (use a comma or a colon). Keep a thought in one flowing sentence rather than chopping it into two or three short ones, and never end a heading or a subheading with a full stop. Name things by what a person recognises ("Your SSH public key", "Machines and runners"), not by how the code calls them. Controls say exactly what happens, and a control that spends money says how much: "Create, $48 a month until you destroy it". Errors say what went wrong and what to do, never sorry. Empty places invite: "No machine but this one yet, add one to run a second farm".

## Colour

Two themes. **Lamplight** is day: `paper` candle ground, `ink` plum-black text. **Dusk** is the sky twenty minutes after sunset: `paper` a warm violet charcoal, never black, and `ink` moonpaper. Every token carries both values; use the token, never the hex.

- Grounds step toward the lamp: `paper` for the page, `paper-raised` for cards, drawers and table bodies, `paper-sunk` for wells (table headers, command blocks, rails), `paper-high` for the rare surface over a raised one.
- Text is `ink`; secondary text is `ink-muted`. Both read on every paper in both themes (ink 10.9 to 14.6 to 1, muted 5.1 to 7.9).
- `accent` (starling violet) is for links, the primary button, the selected tab and the focus ring. Text on an accent fill is `on-accent`, never white.
- `lamp` is the one warm light: the live dot, the lit bird, the lamp button. By day it is decoration only (2.4 to 1 on paper): never text.
- The pastel fields (`field-mint`, `field-butter`, `field-rose`, `field-periwinkle`, `field-lilac`) are grounds: a banner, a done step, a section of the landing page, an illustration plate. States themselves are ink: `success`, `warning`, `danger`, `info`, each 4.5 to 1 or better on every paper and on its own field in both themes, and each drawn with its own mark, so colour never works alone.
- `line` is the decorative hairline; `line-strong` is any border that means something (inputs, quiet buttons), 3 to 1 or better.

## Type

Three families, each with one job, and one hard line between the app and everything around it.

- **Fraunces** (`display-xl`, `display`, `title`): the almanac's voice, for accent headings OUTSIDE the app only: the landing page, the docs, the night report's cover, the cover of this system. Set light (360) at its softest (SOFT 100) and its largest optical size; the WONK letterforms only in the wordmark. It is an open Google font by Undercase Type, not any other product's face. Never inside the dashboard: not for section heads, dialog or drawer titles, or empty states.
- **Instrument Sans** (`heading`, `body`, `body-sm`, `label`): everything inside the app, headings included. Body 15 on 24 in documents, 13 on 20 in the dashboard. Labels are 12.5 in weight 550, sentence case, never capitals.
- **IBM Plex Mono** (`figure`, `data`, `data-sm`): what the instruments print. Figures on tiles, commands, ids, paths, log lines, percentages and every number in a table column. Always tabular. Units beside a figure ("a month", "GB") are in the sans.

Keep running text near 65 characters a line.

## Space and shape

Spacing runs `space-1` 4 to `space-8` 72. Pad cards and tiles with `space-4`, separate cards with `space-5`, sections with `space-6` in the dashboard and `space-7` in documents.

Nothing is square. Radii grow with the size of the thing: `radius-xs` (6) for inputs, checkboxes, wells and tags, `radius-sm` (7) for buttons, tiles and the banner, `radius-md` (12) for cards, tables, drawers and dialogs, `radius-lg` (20) for the hero plate and the landing page's large fields, `radius-pill` for switches and radios. A drawer is a floating sheet with all four corners rounded, never a panel glued to the edge.

There are no shadows in the product. A surface is set apart by its paper step (`paper-raised` on `paper`) and a `line` hairline; a selected thing by an `accent` border.

In the dashboard, read the swarm like an instrument: hairline tables, figures in mono, one line per cell, labels on the top edge and notes on the bottom edge of every tile so a row never jumps.

## The murmuration

- **Flock** (`Murmur.flock`): the live flock, once per page at most. The landing hero, an empty Board, the night report. It moves the way real starlings do (the StarDisplay model and the field measurements behind it): every bird holds a near constant speed and turns only by banking, at a limited roll rate, so turns are unhurried arcs of two or three seconds; it copies its seven nearest neighbours and reacts about fifteen times a second, so a turn rolls across the flock as a dark band; wings beat in short bursts and glide between. The only randomness is a slow drift in the bank each bird wants, never a twitch. One lamp-lit bird, a plain readout under it.
- **Gather**: the mark in motion, the lit bird in the middle and the seven wheeling round it, the loader for waits of a second or more, always beside words that say what is awaited.
- **Ribbon**: a section divider drawn as a thin ribbon of birds, for documents and reports.
- **Stipple** (`mm-stipple`): the engraving grain of the paper itself (not birds), 4 to 6 percent of ink, on heroes, plates and empty states. Never under body text in a table.
- **The mark**: the lamp-lit bird and the seven it watches, eight bold birds on an even ring, one drawing at every size from a browser tab to a cover. The loader, Gather, is the same mark in motion.
- **Status marks**: running is a small bird in flight; the other states have their own shapes (a check, a ring, a cross, a half moon, two bars).

## Motion

Motion answers a person or shows the flock; nothing else moves. Presses scale to 0.97 in 120 ms; hover changes a fill in 120 ms. Drawers and dialogs enter in 200 ms with ease-out (cubic-bezier 0.2, 0.8, 0.2, 1) and leave the same way; a switch slides its thumb in 160 ms. Keyboard actions never animate. The flock drifts at a natural pace and stops off screen. Under reduced motion the flock is one still frame and the loader rests in a ring.

## Icons

Line icons, 16 px, 1.4 to 1.6 px stroke in `currentColor`, round caps, drawn on a 24 grid. The Board icon is four birds. No emoji anywhere, no filled icon sets mixed in, except the bird, which is always a filled silhouette.

## Controls and states

Every field is 36 px tall on `paper-raised` inside a `line-strong` border (3 to 1); focus turns the border `accent` and adds the focus ring. A select draws its own 12 px chevron, inset 12 px, and its text stops 36 px short of it. Checkboxes are rounded squares (`radius-xs`), radios and switches round. Hover lifts a field to `paper-high` and a quiet button to `paper-sunk`; the primary button darkens to `accent-hover`. A state is never a coloured bubble: it is a mark and a word in the state's ink (`Status`).

The focus ring is a solid 2 px `accent` outline with a 2 px offset, 3 to 1 or better on every paper in both themes. A switched-off control stays visible at `opacity-disabled` with a title that says why. Every table cell is one line; a cut value carries its full text in its title.

## Do not

- Pure white or pure black anywhere, cold grey-blue darks, or a gradient that is not the dusk sky on a hero.
- Shadows of any kind, square corners, coloured left rails on cards, a card for every paragraph.
- Pastel bubbles for states, dots standing in for birds, invented shapes (blocks, circles) where the flock can speak.
- Capitals for labels, a middle-dot chain of metadata, arrows appended to links.
- More than one flock, more than one lamp button, or gold and violet over a twentieth of any screen.
- The serif inside the app.
- A state shown by colour alone.
