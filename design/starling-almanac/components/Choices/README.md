# Choices

Checkbox, radio and switch.

- Checkbox (`mm-check`): several independent yes-or-no choices, applied when the form is sent. A rounded square that fills with `accent` when checked. It shows a dash when only some of a group are checked (`indeterminate`).
- Radio (`mm-radio`): one of a few options, all visible, applied when the form is sent. For more than five options, use a select. For options that need detail, use `ChoiceCard`.
- Switch (`mm-switch`, with `role="switch"` on the input): something that is on or off right now. It applies at once, with no Save button.

Put the input inside its label, so the whole label is the click target. The label says what is on when the control is on.
