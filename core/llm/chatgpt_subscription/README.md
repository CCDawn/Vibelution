# ChatGPT subscription inference

This pack adapts the official Sign in with ChatGPT plan-usage contract to the
existing Vibelution LLM pipeline. It does not run Codex or own sessions, tool
execution, transcripts, permissions, or Launcher lifecycle.

## Ownership

- `auth.py`, `callback.py`, `identity.py`: public-client OAuth, bounded loopback
  callback, verified OIDC identity, refresh, cancellation, and revocation.
- `storage.py`: Windows current-user DPAPI, existing cross-process file locks,
  strict atomic replacement, and a persistent installation host identifier.
- `transport.py`: bounded authentication/model-catalog HTTP; no upstream body
  or credential text in public errors.
- `wire.py`: canonical Responses adapter specialization, full-history replay,
  local tool namespaces, and fixed subscription errors.
- `inference.py`: fixed public Responses destination, final body filtering,
  sync collection of SSE, cancellation, and terminal validation.
- `__init__.py`: one process-local account manager; independent Workbench and
  Launcher Python processes share only the encrypted credential store.

Provider configuration belongs to the normal operator config draft/apply flow.
`oauth:chatgpt` is a reference, not a token. The store is resolved beside the
operator config at `credentials/chatgpt`; no Codex auth cache is imported.
Reading credential metadata never refreshes a token. Runtime resolution must
explicitly request the secret, which is sent only to the fixed OpenAI resource.

Windows is the initial supported credential backend. Other platforms fail
closed until an OS-protected store is supplied; there is no plaintext fallback.
A locally connected account or model catalog is not proof of Pro entitlement
or successful inference. Only a completed native turn establishes that request.

## Subscription protocol constraints

The wire uses `store: false`, `stream: true`, developer instructions and complete
input history. Generic unsupported sampling, output-limit, continuation and
retention fields are removed after composition and checked again at HTTP send.
Hard token-budget admission is rejected before provider I/O because this route
cannot enforce a provider output-token cap. Existing API providers are unchanged.
Only `response.completed` with completed status is success. Partial output or
tool deltas followed by failure cannot cause automatic replay or tool execution.
An explicit 401 invalidates only the access token used by that request, so a
late failure cannot invalidate a newly connected account.

Sources: [official registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[account lifecycle](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions),
[inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[preview limits](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

Tests: `test_chatgpt_subscription_{auth,storage,config,wire,transport,client}.py`
and `test_web_chatgpt_subscription_routes.py`. Tests use synthetic credentials;
the storage suite also exercises real Windows DPAPI across hidden processes.
