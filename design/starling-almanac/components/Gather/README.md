# Gather

The loader: the mark in motion, for waits of a second or more.

`mm-gather` holds seven empty `<i>` elements, one per bird. The lamp-lit bird stays in the middle, and the seven circle around it every 2.8 s on an ellipse, like a flock circling overhead seen a little from the side. A bird never turns over: only its position moves. It grows larger and darker as it comes round the front, and smaller and paler behind.

Show it only when a wait will last a second or longer, and always beside words that say what is being waited for ("Asking the farm"). A shorter wait shows nothing. Give it `role="status"` and an `aria-label`.

Under reduced motion, the seven birds rest on the ellipse around the lit one, which is the mark itself.
