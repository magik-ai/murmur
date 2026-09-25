# murmur.farm

The landing page for murmur: one static page with no build step.

## Files

| Path | What it is |
| --- | --- |
| `index.html` | The page |
| `assets/tokens.css` | The design system's colours, spacing, radii and fonts as CSS custom properties |
| `assets/murmur.css` | The design system's component classes (`mm-`) |
| `assets/flock.js` | The design system's animated flock |
| `assets/site.css` | This page's own layout |
| `assets/site.js` | This page's behaviour: the install tabs, the Copy buttons and the animations |
| `assets/shots/` | Screenshots of the plugin and the dashboard, light and dark |
| `assets/*.svg`, `assets/*.png`, `favicon.ico`, `site.webmanifest` | The marks, the icons and the social preview image |
| `.assetsignore` | Files kept off the published site, such as this README |
| `_headers` | The response headers every page and file gets. Wrangler reads it and does not publish it |

`murmur.css` and `flock.js` are copies of the files in
[`design/starling-almanac/components/`](../design/starling-almanac/components). Keep them
identical: change the design system first, then copy the files here.

`tokens.css` holds the same values as
[`design/starling-almanac/tokens.json`](../design/starling-almanac/tokens.json). There is no
script that generates it, so when you change a token, change it in both files.

## Look at it locally

Serve the folder from the repository root:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Then open <http://127.0.0.1:8000/>.

## Publish it

murmur.farm is the Cloudflare Worker `murmur`. The
[site deploy](../.github/workflows/site-deploy.yml) workflow publishes this folder on every
push to `main` that changes it, and on demand from the Actions tab;
[`wrangler.jsonc`](../wrangler.jsonc) at the repository root says what to publish. The
workflow needs two repository secrets: `CLOUDFLARE_API_TOKEN`, a token made from the "Edit
Cloudflare Workers" template, and `CLOUDFLARE_ACCOUNT_ID`.

To publish it elsewhere, serve the folder as it is at the root of a domain:
`site.webmanifest` points to its icons with absolute paths such as `/assets/icon-192.png`.
