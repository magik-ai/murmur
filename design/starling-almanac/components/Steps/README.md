# Steps

A dialog that walks through a real sequence, such as: where, log in, review, create.

Use `mm-steps` with one `mm-step` per step. Each step has a number (`mm-step__no`), a title (`mm-step__title`), one line about what happens (`mm-step__text`) and its content (`mm-step__body`). The steps carry numbers because the order matters. A finished step (`data-state="done"`) turns mint.

The title is a verb or a noun the person knows. The step that spends money shows the price in its button and repeats it on a confirm.
