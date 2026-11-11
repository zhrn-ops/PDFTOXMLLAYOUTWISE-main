# Audit remediation — 2026-11-11

This update supersedes the remaining-finding statuses in the audit spreadsheet
and earlier reports. It does not change the historical reports or the source
spreadsheet.

| Finding | Current outcome |
|---|---|
| C01–C07, C12, N02, N03 | Existing fixes retained and covered by the full regression suite. |
| C08 | Classify button and signal connection removed at the user's request. The synchronous helper remains for programmatic callers; it must not be reconnected to a GUI action. |
| C09 | File-stored credentials are ignored with a migration warning that contains no key. Environment credentials remain supported. Legacy explicit plaintext writes now raise before writing. Existing files are not deleted automatically. |
| C10 | Provider transport and response failures have typed exceptions. Programming errors propagate instead of triggering provider/heuristic fallback. The asynchronous finish boundary stops draft generation on unexpected errors. Fallback provenance is recorded for classification and failed finish requests. Broad worker catches that deliver errors to the UI remain intentional. |
| C11 | Removed the nonexistent implicit JATS schema default. Explicit JATS paths remain compatible; ANI requires an explicitly selected ANI profile. Authoritative publisher validity remains blocked on a trusted ANI/CAR XSD bundle and its licensing/provenance. |
| N01 | Export, title reordering, and language changes retain scientific superscripts/subscripts in every language. XML correction allows scripts in non-English titles. Existing mixed markup and original-language attributes remain intact. This preserves scientific meaning without asserting publisher acceptance. |
| R07 | Provider fallback progress/log messages no longer include arbitrary exception text; OpenRouter HTTP errors omit response bodies. Sentinel tests cover those paths. This is not an exhaustive privacy review of every application log site. |

## Verification

Regression tests cover expected transport fallback, propagation of serialization
and programming errors, malformed provider JSON and response structures,
credential migration, rejection of legacy secret writes, scientific title
markup, absence of the Classify button, and stopping draft generation on internal
parser errors. Tests mock providers; no live services or credentials are used.

The initial sandbox test attempts encountered Windows temporary-directory access
errors. The full suite is run with permissions that allow pytest's temporary
files, using `python -m pytest -q -p no:cacheprovider --basetemp .test-alt-review-remediation-verified`.

Final result: **634 passed in 30.09 seconds**. Python syntax checks passed for
109 source/test files; `git diff --check` passed. An existing viewer test's fixed
350 ms rendering delay was replaced with a bounded wait for actual completion
after it failed intermittently during the full run.

## Remaining evidence gaps

R01 (real-paper accuracy), R02 (representative performance/RSS), R03 (systematic
draft fuzzing), R04 (live provider contracts), R05 (dependency vulnerability
scan), R06 (bilingual corpus review), and R08 (exhaustive dirty-state sequences)
remain unverified risks, not demonstrated defects fixed by this change.
R09 (publisher title-order/original-language rules) and C11 require the
authoritative publisher schema/profile. Existing synthetic tests do not resolve
these evidence gaps. No schema or reviewed PDF corpus was supplied with the audit.
