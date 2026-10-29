## Summary

<!-- What does this change and why? -->

Closes #

<!-- Every PR links an issue, typo and docs fixes included. Use "Refs #N" for partial work. -->

## Checklist

- [ ] The linked issue is on an open milestone and a maintainer agreed to the change.
- [ ] I understand every change in this PR and can answer review questions about it.
- [ ] The change ships with a test, or a stated reason why a test is impractical plus a manual repro.
- [ ] The architecture overview, ADRs or threat model are updated if this changes what they describe.
- [ ] My commits are signed off (`git commit -s`).
- [ ] I ran `nox -s gate`.
- [ ] I ran `nox -s applier` / `nox -s live` (only if this touches the book process or paperless; Docker test environment, synthetic data).
- [ ] Documentation has been updated if this changes a CLI flag, a config key, a JSON contract field, a staging column, or a disposition.
- [ ] No real transaction data, IBANs, or credentials are in the diff.
