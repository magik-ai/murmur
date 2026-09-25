# Table

Rows of things of one kind: machines, accounts, projects, runs.

Put `mm-table` inside `mm-table-wrap`, which gives it a `radius-md` frame. Every cell is one line. A long value is cut with an ellipsis and carries its whole text in its `title`, so a row never grows a second line. Numbers are right-aligned in mono (`mm-num`). The header sits on `paper-sunk` in the `label` style, in sentence case. Rows are divided by a `line` hairline, and the row under the pointer lifts to `paper-high`.

Put at most one `Status` and at most three small buttons in a row. Never use a table for layout.
