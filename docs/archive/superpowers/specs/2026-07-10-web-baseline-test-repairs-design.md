# Web Baseline Test Repairs Design

## Problem

The assistant-message consolidation change passes its focused tests and frontend build, but the complete Web suite exposes four unrelated baseline failures:

- Two deterministic `RouteStyleDisplayContract` failures caused by stale `layoutCenterFirst` expectations after the route adopted `layoutCompactDesktop`.
- Two image-component test timeouts caused by dynamic component imports running inside Vitest's default five-second per-test budget during the full parallel suite.

## Decisions

### Route style contract

Update the contract test to describe the current production composition:

- Treat `ChatCodingRoute.styles.ts:layoutCompactDesktop` as a composed grid-template modifier.
- Assert that `styles.layout` is composed with `styles.layoutCompactDesktop`.
- Do not modify `ChatCodingRoute.tsx` or `ChatCodingRoute.styles.ts`; the production class composition already provides the required grid display owner.

### Image component tests

Move `ConversationImagePreviewDialog` and `ConversationImageArtifactView` imports to module scope:

- Keep the existing server-render assertions unchanged.
- Remove the unnecessary asynchronous dynamic imports from the timed test bodies.
- Do not increase global or per-test timeout values.
- Do not modify the production image components or VUI import policy.

## Evidence

- The route-style failures reproduce identically on unmodified local `main`.
- The two image tests pass when run directly on local `main`, each taking about 3.8 seconds, but exceed five seconds under the complete parallel suite.
- Both image tests perform synchronous `renderToStaticMarkup`; their only asynchronous operation is module loading.

## Success Criteria

- The three affected test files pass together.
- The complete Web test suite passes without timeout overrides.
- The assistant-message focused and neighboring tests remain green.
- The frontend production build remains green.
- No production UI behavior changes are introduced by the baseline test repairs.
