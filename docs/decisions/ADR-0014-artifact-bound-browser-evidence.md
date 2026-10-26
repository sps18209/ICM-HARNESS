# ADR-0014: Bind acceptance to fresh built files and required binary evidence

Status: accepted for local development evaluation.

## Problem

Source fingerprints deliberately exclude ignored/generated outputs. That permits
an executable or bundle to change after testing while the source fingerprint
stays unchanged. API tests also cannot establish that a visible browser workflow
works. Merely generating screenshots does not connect them to accepted evidence.

## Decision

Profiles may name up to 64 explicit `artifact_paths`, each within generated_paths
or `.harness/runtime`. The local execution provider removes those outputs before
setup/reset/ready commands. Tracked product inputs and symlink outputs are refused.
Missing rebuilt outputs block acceptance. The candidate adapter hashes names,
bytes and executable bits immediately before checks and after cleanup; each file
has a 32 MiB limit and is preserved in the content-addressed store.

Approval and promotion recheck the live artifact identity and stored bytes. The
Git manager checks again before merge. Approval and promotion events bind the
verification run to the artifact digest. Promotion still merges source; it does
not deploy a service or copy ignored build outputs into the destination. Stored
artifact blob references identify the tested bytes for an eventual release adapter.

Checks may also declare required `attachments` mapping explicit output paths to
media types. These outputs are fresh for each command and archived by content
hash. Missing attachments reject acceptance. Approval checks them again.
Attachments cannot overwrite protected inputs, reports or built artifacts. A
provider lacking fresh-output support or an evidence store blocks before checks.
Old profiles omit these optional fields and retain their previous digest.

## Browser validation

The synthetic TypeScript fixture serves a real form and API. Native Playwright
runs the save/reload journey in desktop and mobile Chromium contexts, checks page
identity, visible content, console health and horizontal overflow, and creates
screenshots plus traces. Unique project-qualified test IDs are required in JUnit.
The combined experiment accepts the correct app, rejects an authorization defect,
and rejects a browser-only status defect despite passing API tests.

The Browser skill was read and its associated app control tool was searched for;
that control tool is not exposed in this session. The approved implementation
plan explicitly calls for native, repeatable Playwright/CI tests. This suite uses
that route without relying on a signed-in browser or user's browser state.

Playwright 1.64.1 and 1.62.1 browser downloads returned a 195-byte HTML response
instead of a ZIP in this environment. The fixture pins exercised release 1.56.1;
its official installer obtained Chromium Headless Shell 141.0.7390.37 (build 1194)
and FFMPEG from Microsoft's fallback mirror. This pin is for the synthetic
localhost fixture, not a recommendation about general web-browsing security.

## Limits

This is local integrity enforcement under one OS account. It does not defeat
hostile code that changes and restores files, falsifies an in-process oracle or
controls the evaluator account. Files not explicitly declared as artifacts are
not covered by the artifact digest. External deployment identity, isolated
evaluator authority, additional browser engines and live-model trials remain
separate gates. Mobile-sized Chromium is not a physical iOS/Safari device test.
