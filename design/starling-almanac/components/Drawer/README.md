# Drawer

The panel a row opens: the details the table left out, and their actions.

`mm-drawer` is a floating sheet on `paper-raised`, `space-3` in from the edge of the window, with `radius-md` on all four corners and a `line` border. It has no shadow. Its head (`mm-drawer__head`) holds the title (`mm-drawer__title`, Instrument Sans at 18 px, never the serif), a one-line subtitle (`mm-drawer__sub`) and a Close button. The content goes in `mm-drawer__body`.

Animate it in over 200 ms with ease-out, and out the same way. Nothing else inside it animates. The CSS does not animate it for you.
