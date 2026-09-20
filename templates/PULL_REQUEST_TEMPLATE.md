<!-- Template: copy to .github/PULL_REQUEST_TEMPLATE.md. One template, no variants.
     Workflow: see CLAUDE.md. -->

## Summary
<!-- One or two sentences: what and why. This becomes the squash-merge commit
     body, so write it for someone reading the history in six months. -->

## Slice
<!-- Which thin vertical slice is this? Link the parent task or issue.
     If this PR is too hard to review in one sitting, it should be two PRs. -->

## Acceptance guide
<!-- Required when the owner will click through this change. Fill every
     subsection with actionable guidance; a docs-only PR may write
     "N/A: docs only". -->

### What changed
<!-- Describe the change in product terms, so a non-engineer can act on it. -->

### Product features potentially affected
<!-- The blast radius, derived by tracing callers and importers of the changed
     code. Say how you derived it, not just what you concluded. -->

### How to check
<!-- Concrete click-paths and expected outcomes on the preview environment.
     For CI-only changes, name the exact checks and outcomes to inspect here. -->

### What could have broken
<!-- Honest risks, and anything you could not verify. -->

## Checklist
- [ ] Branched off fresh `main`; this PR is one coherent batch.
- [ ] House style rule respected in the code, the docs and this PR body (for us:).
- [ ] Lint clean and tests green locally; any pre-existing flake is named here.
- [ ] Tests sit at the lowest tier that proves the behavior, with stable
      locators, and any coverage exception is documented.
- [ ] Schema: exactly one new migration, backward-compatible with the deployed
      code (expand now, contract later). _(N/A if untouched.)_
- [ ] No secrets committed.
- [ ] Adversarial review ran on this head commit; findings addressed or filed.
- [ ] Docs in sync: the law file, the architecture file, the doc index, and the
      matching `docs/knowledge/` domain file, OR nothing applies.
- [ ] `RELEASE_NOTES.d/<category>-<slug>.md` note added, OR "no user-visible
      change".

<!-- repo-specific checklist items go here, for example:
- [ ] Layer rules respected: no import crosses the allowed dependency direction.
- [ ] UI composes registered design-system primitives only; the matching story
      or snapshot ships in this PR.
- [ ] Anything touching prices, keys, enforcement or checkout carries the
      owner's explicit approval, and the money checklist was re-run.
- [ ] Sensitive user content goes through the encryption wrapper.
- [ ] Language ratchet: every file meaningfully changed here is in the target
      language, with no behavior change in the conversion.
-->

## Notes
<!-- Trade-offs, follow-ups, manual test steps. -->
