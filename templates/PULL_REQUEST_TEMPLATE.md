<!-- Template: copy to .github/PULL_REQUEST_TEMPLATE.md. Keep one template, with
     no variants. The workflow it belongs to is in CLAUDE.md. -->

## Summary
<!-- One or two sentences: what changed and why. This becomes the body of the
     squash-merge commit, so write it for someone reading the history in six
     months. -->

## Slice
<!-- Which thin vertical slice is this? Link the parent task or issue.
     If this pull request is too big to review in one sitting, split it in two. -->

## Acceptance guide
<!-- Required when the owner will click through this change. Fill every
     subsection with steps a reader can follow. A docs-only pull request may
     write "N/A: docs only". -->

### What changed
<!-- Describe the change in product terms, so a non-engineer can act on it. -->

### Product features potentially affected
<!-- What else this change can reach, found by tracing the callers and importers
     of the changed code. Say how you found it, not just what you concluded. -->

### How to check
<!-- Concrete click paths and expected results on the preview environment.
     For a CI-only change, name the exact checks and results to look at. -->

### What could have broken
<!-- The real risks, and anything you could not verify. -->

## Checklist
- [ ] Branched from a fresh `main`; this pull request is one coherent batch.
- [ ] The house style rule from CLAUDE.md is followed in the code, the docs and this body.
- [ ] Lint clean and tests green locally; any flaky test that failed before this change is named here.
- [ ] Tests sit at the lowest level that proves the behavior, with stable
      locators, and any gap in coverage is documented.
- [ ] Schema: exactly one new migration, compatible with the deployed code
      (expand now, contract later). _(N/A if the schema is untouched.)_
- [ ] No secrets committed.
- [ ] Adversarial review ran on this head commit; findings fixed or filed.
- [ ] Docs in sync: the law file, the architecture file, the doc index, and the
      matching `docs/knowledge/` domain file, OR none of them applies.
- [ ] A `RELEASE_NOTES.d/<category>-<slug>.md` note is added, OR this body says
      "no user-visible change".

<!-- Add the checklist items that only your repository needs, for example:
- [ ] Layer rules respected: no import goes against the allowed dependency direction.
- [ ] The UI uses registered design-system parts only; the matching story or
      snapshot ships in this pull request.
- [ ] Anything touching prices, keys, enforcement or checkout has the owner's
      explicit approval, and the money checklist was run again.
- [ ] Sensitive user content goes through the encryption wrapper.
- [ ] Language ratchet: every file meaningfully changed here is in the target
      language, with no behavior change in the conversion.
-->

## Notes
<!-- Trade-offs, follow-ups, manual test steps. -->
