# Starling Almanac

The Starling Almanac is murmur's design system. It covers colour, type, spacing, shape, motion, icons and components. The landing page uses copies of its files, and the dashboard uses the same colours. [`design/README.md`](../README.md) lists the files and how they are used.

murmur runs many coding agents as one team. The name comes from a murmuration, a flock of starlings that flies as one. So the system has one decoration, a flock of birds. Everything else is plain and exact: tables, figures in a monospaced font, warm paper colours and violet ink.

## Principles

- **Pair the flock with words.** The flock shows the team as many small things moving together. Always put the same facts next to it in words, as a table or a readout.
- **Warm colours, exact facts.** The colours are soft, but the facts are not. Figures are exact, a price is shown before anything is bought, and a state is always a mark and a word.
- **Birds, not dots.** Wherever the flock appears (the mark, the hero, the loader, a divider, a status), each member is a bird with wings.
- **No shadows, no square corners.** Depth comes only from paper steps and hairlines. Every surface, control and field has rounded corners from the radius scale.
- **One bold thing per view.** One flock, one lamp-lit bird and one primary button per view. Everything around them stays quiet.
- **Seven is the house number.** The mark and the loader show seven birds around the lit one. Each bird in the flock follows its seven nearest neighbours, close to the number measured on real starlings. An avatar stack shows at most seven.

## Voice

Write like a good lab notebook: plain verbs, short sentences, sentence case. No exclamation marks, no emoji, no em dash (use a comma or a colon). Never end a heading with a full stop.

Name things the way a person knows them ("Your SSH public key", "Machines"), not the way the code calls them. A control says exactly what it does. A control that spends money says how much: "Create, $48 a month until you destroy it". An error says what went wrong and what to do next, without apologising. An empty place invites action: "No machine but this one yet, add one to run a second farm".

## Colour

There are two themes. **Lamplight** is the light theme: `paper` is a warm cream and `ink` a plum-black. **Dusk** is the dark theme: `paper` is a warm violet charcoal, never black, and `ink` a warm off-white. Every colour token has a value for each theme. Use the token, never the hex value.

- Surfaces: `paper` for the page, `paper-raised` for cards, drawers and table bodies, `paper-sunk` for wells (table headers, command blocks, rails), and `paper-high` for the rare surface over a raised one. In both themes, `paper-raised` and `paper-high` are lighter than the page and `paper-sunk` is darker.
- Text is `ink`, and secondary text is `ink-muted`. Both are readable on every paper in both themes: `ink` has a contrast of 10.9 to 15.2 to 1, and `ink-muted` 5.0 to 7.9 to 1.
- `accent` (starling violet) is for links, the primary button, the selected tab and the focus ring. Text on an accent fill uses `on-accent`, never white.
- `lamp` is the one warm light: the live dot, the lit bird, the lamp button. In Lamplight it is decoration only (2.4 to 1 on paper), never text.
- The pastel fields (`field-mint`, `field-butter`, `field-rose`, `field-periwinkle`, `field-lilac`) are backgrounds: a banner, a finished step, a section of the landing page, an illustration. States use ink colours instead: `success`, `warning`, `danger` and `info`. Each reaches 4.5 to 1 or better on every paper and on its own field, in both themes. Each state also has its own mark, so colour never carries meaning alone.
- `line` is the decorative hairline. `line-strong` is for any border that means something (inputs, quiet buttons), at 3 to 1 or better.

## Type

Three typefaces, each with one job. The serif never appears inside the app.

- **Fraunces** (`display-xl`, `display`, `title`): headings outside the app only, such as the landing page and covers. Set it light (weight 360), at its softest (`SOFT` 100) and at its largest optical size. Its wonky letterforms (`WONK` 1) appear only in the wordmark. Fraunces is an open-source typeface by Undercase Type, served by Google Fonts. Never use it in the dashboard: not for section heads, dialog or drawer titles, or empty states.
- **Instrument Sans** (`heading`, `body`, `body-sm`, `label`): everything inside the app, headings included. Body text is 15 px on a 24 px line in documents, and 13 on 20 in the dashboard. Labels are 12 to 12.5 px at weight 550, in sentence case, never in capitals.
- **IBM Plex Mono** (`figure`, `data`, `data-sm`): what the machine prints. Use it for figures on tiles, commands, ids, paths, log lines, percentages and every number in a table column, always with tabular figures. A unit beside a figure ("a month", "GB") is set in the sans.

Keep running text near 65 characters a line.

## Space and shape

Spacing runs from `space-1` (4 px) to `space-8` (72 px). Pad cards and tiles with `space-4`. Separate cards with `space-5`, and sections with `space-6` in the dashboard and `space-7` in documents.

Nothing is square. Bigger things get bigger corners:

- `radius-xs` (6 px): inputs, checkboxes, wells and tags;
- `radius-sm` (7 px): buttons, tiles and the banner;
- `radius-md` (12 px): cards, tables, drawers and dialogs;
- `radius-lg` (20 px): the hero plate and the landing page's large fields;
- `radius-pill`: switches and radios.

A drawer is a floating sheet with all four corners rounded, never a panel stuck to the edge of the window.

The product has no shadows. A surface stands apart by its paper step (`paper-raised` on `paper`) and a `line` hairline. A selected thing gets an `accent` border.

In the dashboard, show data plainly: hairline tables, figures in mono, one line per cell. In a tile, the label and the value sit at the top and the note at the bottom, so a row of tiles lines up whatever the notes say.

## The flock and the mark

- **Flock** (`Murmur.flock`): the live flock. Show at most one in view at a time, for example in a landing page hero or an empty state. Each bird keeps a nearly constant speed and turns only by banking, so its turns are slow, smooth arcs. It follows its seven nearest neighbours and reacts about fifteen times a second, so a turn spreads across the flock as a dark band. Wings beat in short bursts, with glides between. One bird is lit by the lamp. Put a plain readout under the flock. [Flock](components/Flock/README.md) has the details and the options.
- **Gather**: the mark in motion, used as the loader for waits of a second or more. The lit bird stays in the middle and the seven circle around it. Always show it beside words that say what is being waited for.
- **Ribbon**: a section divider drawn as a thin row of birds, for documents and reports.
- **Stipple** (`mm-stipple`): a fine dot texture, like the grain of an engraving (dots, not birds). It is 4 to 6 percent of `ink`, for heroes, plates and empty states. Never put it under body text or in a table.
- **The mark**: the lamp-lit bird in the middle and the seven it watches on an even ring around it. The same drawing works at every size, from a browser tab to a cover. The loader, Gather, is the mark in motion.
- **Status marks**: running is a small bird in flight. The other states have their own shapes: a check, a ring, a cross, a half moon, a lamp dot and two bars.

## Motion

Motion answers a person or shows the flock. Nothing else moves.

- A press scales the control to 0.97 in 120 ms. A hover changes a fill in 120 to 160 ms.
- Drawers and dialogs enter in 200 ms with ease-out (`cubic-bezier(0.2, 0.8, 0.2, 1)`) and leave the same way.
- A switch slides its thumb in 160 ms.
- Keyboard actions never animate.
- The flock flies at a natural pace and stops when it is off screen.
- Under reduced motion, the flock is one still frame and the loader's birds rest on their ring.

## Icons

Line icons, 16 px, with a 1.4 to 1.6 px stroke in `currentColor` and round caps. The Board icon is four birds. No emoji in the interface's own words or icons, and no filled icon sets mixed in. The one exception is the bird, which is always a filled silhouette.

## Controls and states

Inputs and selects are 36 px tall, on `paper-raised`, inside a `line-strong` border (3 to 1). Focus turns the border `accent` and adds the focus ring. A select draws its own 12 px chevron, 12 px from the right edge, and its text stops 36 px from that edge, so the two never touch. Checkboxes are rounded squares (`radius-xs`); radios and switches are round. Hover lifts a field to `paper-high` and a quiet button to `paper-sunk`, and the primary button darkens to `accent-hover`. A state is never a coloured bubble: it is a mark and a word in the state's colour ([Status](components/Status/README.md)).

The focus ring is a solid 2 px `accent` outline just outside the control. It reaches 3 to 1 or better on every paper in both themes. A disabled control stays visible at `opacity-disabled`, with a `title` that says why. Every table cell is one line, and a cut value carries its full text in its `title`.

## Do not

- Use pure white or pure black, cold grey-blue darks, or gradients. The one exception is a sky in an illustration.
- Use shadows of any kind, square corners, coloured left rails on cards, or a card for every paragraph.
- Use pastel bubbles for states, dots in place of birds, or other shapes (blocks, circles) where a bird would do.
- Write labels in capitals, chain metadata with middle dots, or add arrows to links.
- Show more than one flock or more than one lamp button in view, or let gold (`lamp`) and violet (`accent`) cover more than a twentieth of a screen.
- Use the serif inside the app.
- Show a state by colour alone.
