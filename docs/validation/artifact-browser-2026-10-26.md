# Built artifact and browser acceptance validation

Base: main `0c46fbd558dfd6c790fcb15a3ce3945c85872d66` (PR 20).
Scope: local built-file identity, binary attachments and a real browser fixture.

## Summary and environment

The flow under test is: local app -> fill Item value -> Save item -> persisted
list entry -> reload -> the same entry remains visible. The TypeScript HTTP
server runs on isolated ephemeral 127.0.0.1 ports in each test worker and closes
after the journey. No public service is deployed.

The Browser skill is available, but its associated control tool was not exposed.
The approved native Playwright/CI workflow was used. The fixture pins Playwright
1.56.1 and its matching Chromium Headless Shell 141.0.7390.37 (build 1194).
Desktop viewport: 1280x800. Mobile-sized Chromium viewport: 390x844 with touch.
This is not physical iOS/Safari validation. Local Node is 24.22.1; CI uses Node 20.
Newer attempted Playwright browser archives returned HTML instead of ZIP bytes;
the exercised release downloaded successfully from Microsoft's official mirror.
A readiness hook launches/closes Chromium and records its version before checks,
so a missing browser blocks as an environment failure.

## Changes verified

Profiles declare explicit fresh build outputs and required evidence attachments.
The verifier stores built bytes, screenshots and traces by content hash. Approval
checks the live built digest and archived evidence; promotion checks the digest
again and records it alongside the source commit and verification run.

The existing Git source promotion continues to exclude generated outputs. This
change does not automatically deliver a binary to an external deployment. It
provides identity and immutable byte references for a later release adapter.

| Check | Result and evidence |
| --- | --- |
| Page identity | PASS: expected title, root URL and Saved items heading |
| Nonblank page / overlay | PASS: form, action and saved list rendered; inspected mobile screenshot has no overlay |
| Console health | PASS: no page error/warning messages during the correct journey |
| Screenshot evidence | PASS: desktop/mobile PNG files collected and hashed |
| Interaction / API integration | PASS: real POST then GET, rendered entry, reload persistence |
| Responsive layout | PASS: no horizontal overflow at either viewport; mobile screenshot visually inspected |
| Correct application | ACCEPTED: 3 API tests and 2 browser tests |
| Authorization defect | REJECTED: unauthorized response deliberately changed from 401 to 200 |
| Browser-only defect | REJECTED: success status changed to Saving while all API tests still passed |
| Freshness / artifact integrity | PASS: stale, missing, modified, symlinked and tracked-input cases covered |
| Approval evidence | PASS: corrupted built blob or screenshot attachment blocks approval |

## Commands and results

- `npm ci --ignore-scripts --prefix fixtures/typescript_api`
- `npx --prefix fixtures/typescript_api playwright install --with-deps --only-shell chromium`
- `python scripts/verify_typescript_fixture.py`
- `python scripts/verify_project.py`
- Extension `npm test` and `npm run package`

The browser interaction uses scoped role/label locators, title/URL assertions,
console/page-error observation, post-reload state assertions, a width check, PNG
capture and context tracing. The combined experiment creates independent Git
candidates for the correct application and the two intentional defects.

Local Python acceptance: 270 passed, one named optional authenticated live Codex
smoke skipped (271 collected). Architecture, layout and Ruff passed. All 18
extension tests, TypeScript compilation and VSIX packaging passed. CI independently
runs the Python matrix and browser/API experiment; its results are recorded on
this change's pull request before merge.

The updated manifest adds 18 mandatory regression cases. No previous obligation
was removed. Old profiles without artifact/attachment fields preserve their
previous digest. Python dependencies are unchanged. The fixture npm audit returned zero reported
advisories at validation; this is not an independent security review. The npm lock adds the
Apache-2.0 Playwright test/runtime packages and their declared optional platform
dependencies; source implementations are not copied into the repository. Test
inputs, tokens and displayed items are synthetic. No live model or client data
is used.

## Evidence and remaining risk

Raw JUnit, compiled file blobs, PNGs, traces and the sealed verification snapshots
live in the verification evidence store. The CI artifact is named
`browser-acceptance-evidence`. Passing examples are copied to
`.harness/runtime/browser-qa/desktop.png` and `mobile.png`; they show the saved
item after reload. Intentional failure runs retain their own screenshots/traces.

The native fixture validates its stated journey only. Additional browsers,
keyboard/accessibility audits, hostile-process isolation, external deployment
identity, direct API agents, independent review and live-model comparison remain
separate gates. Local receipts do not authenticate authority against another
process running as the same OS user.
