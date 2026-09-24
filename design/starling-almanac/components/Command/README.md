# Command

A command a person runs in their own terminal, with a Copy button.

Use `mm-command` with a muted `$` (`mm-command__prompt`), a `code` element and a small quiet button. The block is mono on `paper-sunk`, one command per line. A long command scrolls inside the block and never wraps in the middle of an argument.

Show a command the farm plans to run the same way: as one shell line, never as a list of words.

The Copy button must copy exactly the text shown. Your code wires it up.
