# Card

One lane: one agent working on one task on its own branch.

A card (`mm-card`) shows:

- a head (`mm-card__head`): the lane's name (`mm-card__title`, one line, cut with an ellipsis), then `mm-spacer` and one `Status`;
- a meta line in mono (`mm-card__meta`): project, branch, model;
- at most two lines about what the agent is doing (`mm-card__body`);
- a footer of figures, as a second `mm-card__meta`.

The card is `paper-raised` with a `line` border and `radius-md`. It has no coloured rail and no shadow: the status shows the state.

Cards sit in a grid that fills its row. A card never stretches over empty space, and never stands alone in a row it could share.
