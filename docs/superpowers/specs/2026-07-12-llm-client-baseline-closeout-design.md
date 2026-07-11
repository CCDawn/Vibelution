# LLM Client Baseline Closeout Design

Date: 2026-07-12

## Status

Approved direction: repair supported Chat/Responses behavior and preserve the existing pre-provider hard failure for unimplemented native Anthropic/Gemini wire protocols.

## Problem

The provider-scoped configuration branch is code-reviewed, but aggregate closeout reaches a legacy LLM-client command with 14 failures. The same command has 16 failures on local `main`; the branch has no current-only failure, but policy still requires the selected command to pass. Read-only diagnosis groups the 14 failures into four contract gaps left by the outbound semantic-adapter cutover:

1. GPT-5 Chat receives explicit `tool_choice` although its resolved capabilities forbid it.
2. The canonical runtime payload composer omits disabled-mode cache-control stripping and Qwen explicit-cache history checkpoints.
3. Eight legacy tests still assume native Anthropic can travel through an OpenAI/LiteLLM-shaped wire path, contradicting the approved hard-fail boundary.
4. The Chat wire assembler emits cumulative reasoning prefixes as deltas and replaces the provider reasoning source with the generic value `canonical`.

## Goals

- Make the aggregate LLM-client validation command pass without excluding tests or weakening the closeout gate.
- Keep one semantic request and runtime payload owner.
- Preserve the pre-provider `unsupported_native_adapter` failure for native Anthropic/Gemini until a separate transport design exists.
- Restore supported Chat behavior for explicit tool choice, prompt-cache policy, and reasoning streaming.
- Preserve secret-safe and bounded logging summaries.

## Non-goals

- Implementing or registering an `anthropic_messages` or Gemini native wire adapter.
- Changing provider identity, schema v2, discovery, operator config, Launcher, or version files.
- Restoring the removed legacy/LiteLLM payload path.
- Deleting failing tests or excluding them from selectors.

## Design

### Capability-aware tool choice

`LLMClient._build_payload()` remains the semantic request owner. It emits `tool_choice="auto"` only when all three conditions are true:

- the immutable route policy permits explicit tool choice;
- route compatibility does not require omission;
- resolved model capabilities support explicit tool choice.

Otherwise it emits the semantic sentinel `omit`, and the Chat wire encoder leaves `tool_choice` out while still encoding tools.

### Prompt-cache policy in the canonical composer

`compose_runtime_wire_payload()` remains the only post-wire payload composer. It gains the two behaviors lost during cutover:

- `disabled`: remove `cache_control` from bounded message content blocks before provider I/O;
- Qwen `explicit_cache_control`: reuse the existing marker helper to add the history checkpoint while preserving the four-marker limit.

The composer continues to own `unsupported` rejection and automatic cache-key behavior. The old `build_llm_payload()` path is not reactivated. Cache stripping must copy affected message/block dictionaries rather than mutate caller-owned input.

### Canonical Chat reasoning deltas and source

`_ChatTurnAssembler` tracks the last reasoning text per `(choice_index, reasoning_source)`. When a provider sends cumulative prefixes, it emits only the unseen suffix. If the next value is not a prefix extension, it emits the new value as a fresh delta so output is not silently lost.

The canonical reasoning event carries a bounded `reasoningSource` diagnostic derived from the extractor's known alias (`reasoning`, `reasoning_content`, `thinking`, or equivalent normalized identifier). `LLMClient` projects that diagnostic into `StreamChunk.provider_payload.reasoning_source`; it does not expose raw provider payload and does not replace the source with `canonical`.

### Anthropic test ownership

Native Anthropic remains unavailable in the canonical wire registry and must fail before provider I/O.

- Anthropic sampling/thinking behavior is tested at `AnthropicAdapter` unit scope, where it is actually owned.
- Generic usage, cache telemetry, redaction, and structured semantic-content behavior is tested through a supported Chat route.
- Chat-shaped reasoning chunks are tested through a supported DeepSeek/OpenAI-compatible route.
- The outbound wire bridge keeps an explicit regression asserting native Anthropic hard-fails before backend invocation.

Tests may change provider fixtures to match the real owner, but assertions about usage accuracy, redaction, structured content, or reasoning deltas must not be weakened.

## Error and safety behavior

- Unsupported native protocols continue to raise a non-retryable `unsupported_wire_protocol`/native-adapter error before backend access.
- Prompt-cache `unsupported` mode continues to reject cache-control input before backend access.
- Diagnostic events contain counts, hashes, normalized source identifiers, and token totals only; no prompt text, cache content, credential, or raw provider response is added.
- Reasoning accumulator state is per stream assembler and per choice/source, so it cannot leak between requests.

## Verification

TDD order:

1. Keep the GPT-5 failure red, then add the capability gate.
2. Keep the three cache failures red, then add canonical composer behavior and adjacent marker-limit/unsupported coverage.
3. Add supported-Chat cumulative reasoning/source failures, then implement assembler state and source projection.
4. Re-home the eight obsolete Anthropic fixtures while keeping the native hard-fail bridge green.

Required validation:

- the diagnosed 109-test subset becomes fully green;
- complete `tests/test_llm_client.py` passes;
- outbound wire bridge, protocol resolver, payload builder, adapters, and invocation-context tests pass;
- the aggregate closeout command that previously reported 14 failures passes;
- Ruff and `git diff --check` pass;
- aggregate local quality closeout is rerun from a clean committed worktree.

## Acceptance criteria

- Tools remain present for GPT-5 while explicit `tool_choice` is omitted.
- Disabled prompt cache strips all message-level content-block markers without mutating the caller input.
- Qwen explicit caching marks the intended history checkpoint and never exceeds four markers.
- Cumulative reasoning `A`, `AB`, `ABC` yields deltas `A`, `B`, `C` and records the normalized provider source.
- Native Anthropic attempts fail before backend I/O; no fake native adapter is registered.
- No selected closeout test is deleted, skipped, xfailed, or removed from the selector.
