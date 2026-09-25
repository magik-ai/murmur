# ChoiceCard

Pick one of a few options that each need a line of detail, such as a provider or a machine size.

Each option is an `mm-choice` button with `role="radio"` and `aria-checked`, inside an `mm-choices` group with `role="radiogroup"`. It holds a title (`mm-choice__title`), one mono line of facts (`mm-choice__meta`) and one note (`mm-choice__note`). The chosen card gets a 2 px `accent` border and a small check in its corner. Nothing else changes, so the cards never jump.

The CSS only draws the states. Your code sets `aria-checked` and handles clicks and arrow keys.

Write money as "$48 a month".
