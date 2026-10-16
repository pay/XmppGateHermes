# Testing

What was actually run, and what it proved. Nothing below is claimed without an observed
result.

## Test suite result

Run against the adapter in this repo, Python 3.14 on Termux, in an **isolated venv**
(separate from the gateway venv, so the live gateway was never touched):

```
$ pytest tests/ -q
125 passed, 2 skipped, 12 subtests passed in 0.93s
```

- `125 passed` — protocol parsing, receipts/markers/chat-states, reactions, MUC gating,
  chunking, media upload routing, standalone sender, packaging, and plugin registration.
- `2 skipped` — platform-conditional tests (not applicable on Android).

### Reproducing the suite safely

Do **not** install pytest into the gateway venv. Use a throwaway venv:

```sh
# (changes system, but isolated — does not touch the gateway)
SCRATCH=~/.hermes/cache/scratch/xmpptest
rm -rf "$SCRATCH" && mkdir -p "$SCRATCH" && cd "$SCRATCH"
uv venv --python "$PREFIX/bin/python3" .venv
uv pip install --python "$SCRATCH/.venv/bin/python3" 'pytest>=8' 'slixmpp[xep-0363]>=1.10,<2'

# (read-only)
cd ~/XmppGateHermes
PYTHONPATH="$PWD" "$SCRATCH/.venv/bin/python3" -m pytest tests/ -q
```

## Fixes applied to the test suite

Three defects in the committed tests were found and fixed. All three were test-side; the
adapter logic was not changed to make a test pass.

1. **Corrupted indentation (collection blocker).** `tests/test_adapter.py` had a
   `send_chat_state` body over-indented to 28 spaces and a following 3-line block at 20
   spaces, producing `IndentationError` at import. This aborted **the entire collection**,
   so no test could run at all. Fixed to the correct 16 / 8 spaces.

2. **Stale mock signature.** `test_prefers_join_muc_wait_when_available` defined
   `FakeMuc.join_muc_wait(self, room, nick)`, but the adapter calls it with
   `maxstanzas=0`. The `TypeError` was swallowed by the adapter's documented
   fall-back-to-`join_muc`, so `wait_called` stayed `False` and the assertion failed. The
   adapter is correct (its docstring states `maxstanzas=0` is intentional); the mock was
   stale. Fixed the mock to accept `**kwargs`.

3. **Hardcoded `/tmp` paths.** Three tests wrote fixtures to `/tmp/hermes-*.png|mp4|jpg`.
   On Android/Termux `/tmp` is not writable (`TMPDIR` is `~/tmp`), so they failed with
   `PermissionError: [Errno 13]`. Fixed to use `tempfile.gettempdir()`, which resolves to a
   writable directory on every platform.

Before these fixes the suite reported `4 failed` on a broken (un-runnable) base; after, it
is green. See `KNOWN-ISSUES.md` for why the same 4 appeared on both adapter versions.

## Live integration checks (real device)

These are end-to-end observations on Termux, not unit tests. They are the evidence that the
integration *works*, beyond the suite passing.

| Check | Method | Observed result |
| --- | --- | --- |
| Telegram adapter connects | `~/gate.sh status`, gateway log | `✓ telegram connected` |
| XMPP adapter connects | same | `✓ xmpp connected` |
| Both at once | same run | both `connected` simultaneously |
| MUC join (room 1) | gateway log | `join confirmed`, occupant JIDs mapped |
| MUC join (room 2) | gateway log | `join confirmed`, occupant JIDs mapped |
| Outbound message to a room | gateway log | response sent, `Sending response (N chars)` logged |
| Direct-message reply | manual DM to the bot | agent replied |
| Dependency versions | `import slixmpp` in gateway venv | `slixmpp 1.17.0` |

Rooms exercised on the authoring device were `tangerang@conference.jabber.ru` and
`code@conference.conversations.im`, with resource `flip4`. The specific room JIDs and the
account are environment details, not part of the repo.

## What was NOT tested

Stated plainly, so nobody assumes coverage that doesn't exist:

- **Reconnect/failover under real network loss.** Simulated drops were not run; the
  keepalive/ping config was set from documented behavior, not measured recovery times.
- **OMEMO / end-to-end encryption.** Not implemented in this adapter.
- **XEP-0333 read markers in MUCs.** Groupchat marker sending is intentionally disabled
  (XEP-0359 stanza-ID caution), so there is nothing to test there yet.
- **Multi-account / multi-resource concurrency.** One account, one resource was exercised.
- **Desktop Linux / macOS installs.** Every result here is from Android/Termux. The suite
  should pass elsewhere, but it has not been run there by this author.
- **Load / long-run stability.** No soak test. The longest observed run is a single session.

## Adding a test

Tests use `unittest.IsolatedAsyncioTestCase` and stub the slixmpp client (no network). Keep
fixtures on `tempfile.gettempdir()`, never a hardcoded `/tmp`. If a test needs to assert an
adapter calls a slixmpp method, make the stub accept the same signature the adapter uses
(including keyword args like `maxstanzas`), or you'll reproduce bug #2 above.
