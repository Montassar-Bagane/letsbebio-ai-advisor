# Validation

22 realistic customer profiles, run against the live API.

```bash
python3 validate.py                  # run + rebuild review_sheet.pdf
python3 validate.py --save-baseline  # save the current run as the reference
python3 validate.py --compare        # show what changed since the reference
python3 validate.py --api http://... # non-default host
```

The API must be running. The script paces itself at just under one request per
second and retries when a free-tier rate limit is hit.

## Two purposes

**Expert review.** `review_sheet.pdf` is printed and marked up by a beauty
adviser: good / acceptable / poor for every recommended product, plus a comment
box per profile and five open questions at the end. The target is zero "poor" —
in cosmetic advice an unsuitable product is not a ranking error, it is a loss of
trust.

*This has not been done yet.* No adviser was available during the internship.
`docs/04-validation-fr.md` states the limitation and lists the products already
flagged during self-assessment.

**Regression test.** `baseline.json` holds a reference run. After any change to
scoring, `--compare` prints exactly which products entered or left each routine.
Change a weight, see the blast radius before shipping.

## Profiles

The 22 profiles cover the four domains and deliberately include thin segments.
A profile returning nothing is a finding about the catalogue, not a bug: C02
(dandruff with an oily scalp) returns zero products, which is a gap the client
should know about.
