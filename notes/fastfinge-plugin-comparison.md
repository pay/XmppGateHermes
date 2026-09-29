# fastfinge/hermes-xmpp-plugin comparison

Date: 2026-06-13

Compared repositories:

- Our plugin: `/home/thanos/Projects/hermes-xmpp`
- fastfinge plugin: `/home/thanos/Projects/review/hermes-xmpp-plugin-fastfinge`

Scope: static source review plus local syntax/unit checks. No live Hermes gateway, secrets, XMPP accounts, services, or remotes were touched.

## Executive summary

fastfinge's plugin is more ambitious and closer to a "first-class XMPP client" UX: reactions, threaded replies, data forms for clarify, ad-hoc commands, message markup, OMEMO, long-message chunking, and XEP-0447 voice metadata are all represented in source/tests/docs.

Our plugin is more conservative and, in several gateway-integration/security areas, safer for Thanos' deployment: password command/file support, explicit direct/MUC policy knobs, MUC mention gating by default, `enforces_own_access_policy`, `MEDIA_KINDS` compatibility for fail-closed media routing, XEP-0184/XEP-0333 receipt controls, local image/document/video/voice upload hooks, OOB URL companion stanzas, and a standalone sender that handles Hermes media tuples.

Recommendation: do not replace our plugin wholesale. Keep our adapter as the base and port selected fastfinge features behind conservative toggles, with tests first. The highest-value parity work is threaded replies + long-message chunking + clarify forms/reactions. OMEMO should be treated as a separate, higher-risk research/implementation track.

## Feature comparison

### Plugin metadata and config/env shape

Our plugin:

- `plugin.yaml` uses `name: xmpp-platform`, `label: XMPP`, `kind: platform`, `version: 0.1.0`.
- Requires `XMPP_JID` and `XMPP_SERVER`; password can come from `XMPP_PASSWORD`, `XMPP_PASSWORD_FILE`, or `XMPP_PASSWORD_COMMAND`.
- Has explicit policy/env controls: `XMPP_ALLOWED_USERS`, `XMPP_DM_POLICY`, `XMPP_ALLOW_ALL_USERS`, `XMPP_GROUP_POLICY`, `XMPP_ALLOWED_ROOMS`, `XMPP_GROUP_ALLOW_FROM`, `XMPP_MUC_REQUIRE_MENTION`, `XMPP_HOME_CHAT`, receipt/marker toggles.
- YAML shape follows `gateway.platforms.xmpp.extra` in docs and `_apply_yaml_config()`.

fastfinge plugin:

- `plugin.yaml` uses `name: hermes-xmpp-plugin`, `label: XMPP/Jabber`, `version: 0.3.0`.
- Requires only `XMPP_JID` and `XMPP_PASSWORD`; uses `XMPP_HOST` instead of our required `XMPP_SERVER`.
- Uses `XMPP_MUC_ROOMS`, `XMPP_MUC_NICK`, `XMPP_HOME_CHANNEL`, `XMPP_OMEMO_ENABLED`, `XMPP_OMEMO_STORAGE_PATH`, `XMPP_MAX_MESSAGE_LENGTH`.
- README documents a top-level `xmpp:` config block, not `gateway.platforms.xmpp.extra`; `_apply_yaml_config()` supports that shape.

Assessment:

- Our secret handling is better: password files/commands avoid embedding secrets in `.env` and match Thanos' pass/GPG pattern.
- fastfinge's env names may be easier for upstream/core XMPP docs (`XMPP_HOST`, `XMPP_MUC_ROOMS`, `XMPP_HOME_CHANNEL`) but conflict with our existing deployment shape.
- If we want compatibility, add aliases rather than renaming: accept `XMPP_HOST` as optional server override, `XMPP_MUC_ROOMS` as alias for `XMPP_ROOMS`, `XMPP_MUC_NICK` as alias for `XMPP_NICKNAME`, and `XMPP_HOME_CHANNEL` as alias for `XMPP_HOME_CHAT`.

### Adapter API compatibility with Hermes gateway conventions

Our plugin:

- Inherits `BasePlatformAdapter` with fallback test stubs when Hermes imports are absent.
- Handles `Platform("xmpp")` fallback via an object with `.value = "xmpp"` if Hermes' `Platform` enum does not know XMPP.
- Declares `MEDIA_KINDS` when Hermes exposes `MediaKind`; includes image, video, voice, and document.
- Implements `send()`, `send_image_file()`, `send_document()`, `send_voice()`, `send_video()`, `send_typing()`, `stop_typing()`, `get_chat_info()`.
- `register(ctx)` supplies `env_enablement_fn`, `apply_yaml_config_fn`, `cron_deliver_env_var`, `standalone_sender_fn`, `allowed_users_env`, `allow_all_env`, `max_message_length`, `platform_hint`, and `enforces_own_access_policy` via adapter property.

fastfinge plugin:

- Imports Hermes gateway types at module import time; tests patch `sys.modules` to make this work outside Hermes.
- Implements many BasePlatformAdapter methods/hooks, including processing lifecycle hooks `on_processing_start()` and `on_processing_complete()` for reactions.
- Generic `send()` accepts old/legacy media parameters (`image_paths`, `voice_path`, `document_path`, etc.) and forwards them.
- Exposes `MAX_MESSAGE_LENGTH = 10000` and chunks long messages itself.
- Does not declare `MEDIA_KINDS` in the reviewed source, so it may not satisfy newer fail-closed media routing conventions without adaptation.
- Does not expose `enforces_own_access_policy`; whether Hermes double-filters or assumes adapter filtering depends on core behavior.

Assessment:

- Our plugin is currently more aligned with recent Hermes media-routing conventions.
- fastfinge has useful lifecycle hooks and long-message behavior we should port, but not its import shape or direct assumptions about Hermes internals.

### Media delivery

Our plugin:

- Registers `xep_0363` and `xep_0066`.
- Uploads image/document/video/voice through HTTP Upload (XEP-0363), sends a body containing the URL, and attaches XEP-0066 OOB URL on the same stanza.
- Implements dedicated media methods and `MEDIA_KINDS`.
- Standalone sender routes image/audio/video/document by extension and supports Hermes media tuple shape `(path, is_voice)`.
- Classifies deterministic upload failures (`UploadServiceNotFound`, `FileTooBig`, `HTTPError`) as non-retryable.

fastfinge plugin:

- Registers `xep_0363`, `xep_0446`, and `xep_0447`.
- Uploads image/document/video using XEP-0363 URL body.
- Sends voice with XEP-0447 Stateless File Sharing when available, falling back to XEP-0363 URL body.
- Standalone sender sends `message` first, then treats every `media_files` item as a document; it does not distinguish image/video/voice/document or tuple `(path, is_voice)` in the reviewed source.
- Retryability is broad: upload exceptions return retryable true.

Assessment:

- Our current media support is stronger for Hermes gateway integration, especially `MEDIA_KINDS`, dedicated methods, voice tuple routing, and OOB compatibility.
- fastfinge's XEP-0447/SFS voice path is a worthwhile enhancement, but should be added on top of our existing upload/OOB path rather than replacing it.

### XMPP UX features

Our plugin already has:

- XEP-0085 typing indicators (`composing`/`active`) for DMs, targeted to the last full resource JID.
- XEP-0184 delivery receipts for authorized DMs.
- XEP-0333 received/displayed chat markers for authorized DMs, with displayed/read markers disabled by default.
- XEP-0066 OOB URL extraction on inbound messages and OOB URL on outbound media messages.
- Conservative MUC mention stripping.

fastfinge has additional first-class features:

- XEP-0444 reactions: sends 👀 while processing, ✅ on success, ❌ on failure.
- XEP-0461 threaded replies: extracts inbound reply context and sends outbound replies tied to original message IDs.
- XEP-0394 message markup: tries to encode bold/code/block-code spans from Markdown-like text.
- XEP-0004 data forms for clarify prompts.
- XEP-0050 ad-hoc command registration.
- XEP-0447 Stateless File Sharing for voice messages.
- OMEMO via `slixmpp-omemo`/`omemo`, including JSON storage and oldmemo fallback logic.
- Long-message splitting before send/encryption.

Missing from both or not complete enough:

- Robust inbound data-form response handling for clarify is claimed in fastfinge docs, but the reviewed adapter source mainly implements `send_clarify()`; I did not find a complete `message_xform` handler that maps submitted forms back into Hermes clarify state.
- Reactions received from users are not converted into Hermes events/tools in either adapter.
- Message markup implementation in fastfinge looks prototype-level; it appends markup after `send_message()` may already have sent the stanza, depending on slixmpp return behavior. Needs careful tests against real stanza construction before porting.
- OMEMO is substantial and should not be mixed into a routine parity patch.
- Neither adapter supports live Jingle voice calls; fastfinge docs correctly recommend deferring live calls.

### Security and privacy

Our plugin strengths:

- Password command/file support.
- Direct-chat allowlist default.
- MUC group policy default allowlist plus room allowlist and sender allowlist.
- MUC mention required by default.
- Public-room platform hint warns the model not to reveal private memory/secrets/hidden instructions.
- Receipts/markers only after authorization; groupchat receipt sending disabled for now.
- Read/display markers disabled by default.

fastfinge strengths:

- Explicit STARTTLS enforcement (`client.use_starttls = True`, `client.force_starttls = True`).
- Optional OMEMO end-to-end encryption.
- Direct-message allowlist.

fastfinge concerns:

- No password file/command support in reviewed plugin metadata/source.
- MUC authorization is mostly room-membership based: if the bot joins a configured room, all messages in that room are accepted. There is no mention-required default like ours.
- OMEMO appears enabled by default via env fallback `XMPP_OMEMO_ENABLED` -> `"true"`; if optional deps are missing it logs and continues plaintext. That is an unsafe surprise unless documented and tested very clearly.
- README examples include personal-looking `/home/fastfinge/...` paths; harmless in their repo, but we should avoid personal defaults in ours.

Recommendation:

- Port fastfinge's explicit STARTTLS setting immediately; it is low risk and improves security.
- Keep our conservative allowlist/MUC defaults.
- Treat OMEMO as opt-in, not default-on, until live interoperability and failure behavior are tested.

### Tests and docs

Our repo:

- `python3 -m unittest discover -s tests -v`: 24 tests pass.
- `python3 -m compileall -q __init__.py hermes_xmpp tests`: pass.
- Tests cover config/env/password command, allowlists, MUC mention policy, receipts/markers, chat states, media upload/OOB, `MEDIA_KINDS`, standalone media routing.
- README is concise and deployment-oriented.

fastfinge repo:

- `python3 -m compileall -q adapter.py __init__.py tests`: pass.
- `python3 -m pytest -q`: not runnable with system Python in this environment because pytest is not installed.
- Tests are broader and pytest-based: first-class UX features, end-to-end mock flows, config helpers, OMEMO, regression checks, plugin registration.
- Docs are much richer: README, changelog, attribution, slixmpp XEP API reference, upstream doc draft, Jingle investigation.

Assessment:

- Our tests are cleaner for current Hermes plugin compatibility and do not require pytest.
- fastfinge has better feature coverage docs/tests but several tests rely on heavy mocking and `sys.modules` patching; treat them as design guidance, not proof of live interop.

## Prioritized roadmap

### P0: safe gateway-parity fixes

1. Add explicit STARTTLS enforcement in our `_SlixmppClient` connect path if compatible with current slixmpp version.
2. Add config aliases for fastfinge/upstream env names while preserving our current names:
   - `XMPP_HOST` -> optional server host override / alias for `XMPP_SERVER`
   - `XMPP_MUC_ROOMS` -> `XMPP_ROOMS`
   - `XMPP_MUC_NICK` -> `XMPP_NICKNAME`
   - `XMPP_HOME_CHANNEL` -> `XMPP_HOME_CHAT`
   - `XMPP_MAX_MESSAGE_LENGTH` -> existing `XMPP_TEXT_CHUNK_LIMIT` or a renamed unified setting
3. Add long-message chunking with tests. Use Hermes `truncate_message` when available, otherwise a simple newline/space boundary splitter. Return continuation IDs when possible.

### P1: high-value XMPP UX parity

4. Implement XEP-0461 threaded replies:
   - register `xep_0461` plus any required fallback plugin if available
   - parse inbound reply ID/text into `MessageEvent(reply_to_message_id=..., reply_to_text=...)` when Hermes supports those fields
   - send outbound `reply_to` as an XEP-0461 reply for the first chunk only
5. Implement XEP-0444 processing reactions behind `XMPP_REACTIONS` default true for DMs and conservative for MUCs:
   - 👀 on start
   - ✅/❌ on completion
   - no reaction to unauthorized senders
6. Implement `send_clarify()` using XEP-0004 data forms with text fallback. Only claim full clarify-form support after inbound form submissions are mapped back into Hermes' clarify state.

### P2: nice-to-have polish

7. Add XEP-0447/XEP-0446 for voice/file metadata while keeping our XEP-0363+OOB fallback.
8. Add XEP-0394 markup only after verifying stanza mutation order and client rendering. Keep plain text as canonical body.
9. Add a minimal XEP-0050 ad-hoc command listing only if Hermes has a stable command surface worth exposing.

### P3: separate research/implementation track

10. OMEMO:
    - opt-in only
    - password/secret-safe storage path
    - clear warning/failure semantics
    - live interop testing with Thanos' actual XMPP clients before activation
    - do not enable by default on the production account

## Follow-up cards

Existing child cards are appropriate and should consume this report:

- `t_1776365a` — implementation placeholder for Python changes.
- `t_f99d4250` — picoder review before any activation.

No additional cards are needed from this parent unless the implementer decides to split OMEMO into its own research track.

## Validation performed

From `/home/thanos/Projects/hermes-xmpp`:

```bash
python3 -m unittest discover -s tests -v
# Ran 24 tests in 0.032s — OK

python3 -m compileall -q __init__.py hermes_xmpp tests
# pass
```

From `/home/thanos/Projects/review/hermes-xmpp-plugin-fastfinge`:

```bash
python3 -m pytest -q
# failed: /usr/bin/python3: No module named pytest

python3 -m compileall -q adapter.py __init__.py tests
# pass
```
