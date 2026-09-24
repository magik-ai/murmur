# murmur.farm

The landing page: one static page, no build step. `index.html` plus `assets/`: the design
system's tokens (`tokens.css`, generated from `design/starling-almanac/tokens.json`), its
components (`murmur.css`) and its flock (`flock.js`), this page's own layout (`site.css`) and
small behaviours (`site.js`), and the marks.

Open `index.html` in a browser to see it. Publish the folder as it is to any static host.

The copies of `murmur.css` and `flock.js` here must match `design/starling-almanac/components/`;
change the design system first, then copy.
