# Local test harness (loopback XMPP, no account required)

`tools/xmpp_test_server.py` is a loopback XMPP c2s stub: STARTTLS → SASL PLAIN → resource bind →
legacy session, then it answers IQs addressed to the bound JID and can inject one inbound message
so the adapter's receive path is exercised. It is not a real server (no roster, no offline
storage, no MUC, no s2s) — keep it on `127.0.0.1`.

## Run it

```sh
# 1. throwaway CA + server cert (SAN localhost + 127.0.0.1)
python3 tools/gen_test_certs.py /tmp/xmppcerts

# 2. the stub
python3 tools/xmpp_test_server.py \
    --user bot --password testsecret \
    --cert /tmp/xmppcerts/server.pem --key /tmp/xmppcerts/server.key \
    --inject-from peer@localhost --verbose
```

Then point a client (or the real adapter) at `127.0.0.1:5222` with `SSL_CERT_FILE` set to
`/tmp/xmppcerts/ca.pem` — `ssl.create_default_context()` honours that variable, which is how a
self-signed test chain becomes trusted without touching the system store.

## Trap 1 — the leaf certificate needs an Authority Key Identifier

Without it, OpenSSL 3.6 refuses the chain at handshake time:

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Missing Authority Key Identifier
```

`gen_test_certs.py` therefore adds `SubjectKeyIdentifier` on the CA and
`AuthorityKeyIdentifier.from_issuer_public_key(ca)` (plus `KeyUsage` and `SERVER_AUTH` EKU) on the
leaf. A "modern" minimal cert that verifies elsewhere can still fail here.

## Trap 2 — an XMPP stream is not one XML document

A stream carries several root-level elements. Both `xml.parsers.expat` and
`ElementTree.XMLPullParser` reject that with `junk after document element`, and re-creating the
parser per element does not help because the error fires at the boundary. The stub therefore
scans its buffer itself (find tags, track depth, skip text inside quoted attribute values), slices
out one complete element at a time and hands each to `ET.fromstring`.

TLS upgrade on the server side is `loop.start_tls(transport, protocol, ctx, server_side=True)`
from an `asyncio.Protocol`. Write `<proceed/>` immediately before calling it; bytes that arrive
during the handshake are consumed by the TLS layer, not by your XML scanner. Set an `upgrading`
flag and ignore `data_received` while the handshake runs.

## Driving the real adapter against it

Use a throwaway `HERMES_HOME` so production config and credentials are untouched — `HERMES_HOME`
is honoured by `get_hermes_home()`, and the directory needs its own `config.yaml`, `.env`, and a
copy of the plugin under `plugins/`:

```sh
GH=~/scratch/xmpp-test-home
mkdir -p "$GH/plugins"
cp -a ~/XmppGateHermes "$GH/plugins/xmpp-platform"
# config.yaml: model block + plugins.enabled: [xmpp-platform]
# .env: XMPP_JID/XMPP_SERVER/XMPP_PASSWORD/XMPP_ALLOWED_USERS/…

SSL_CERT_FILE=/tmp/xmppcerts/ca.pem \
OPENAI_API_KEY="$(grep -m1 '^OPENAI_API_KEY=' ~/.hermes/.env | cut -d= -f2-)" \
HERMES_HOME="$GH" hermes gateway run --accept-hooks
```

Read the verdict from `$GH/gateway_state.json` (`platforms.xmpp.state`), which is the same fact
`status` displays. Export `OPENAI_API_KEY` in the process environment rather than copying the real
`.env` into the scratch home.

## `tools/join_probe.py` — the MUC diagnostic

Joins a room with the *same nick the bot uses* and prints every presence stanza the room sends
about that nick, with status codes and reasons, then reports a summary. This is what produced the
`available` → `unavailable` in 0.26 s pair that proves a silent room-side kick
(`docs/FIELD-NOTES-2026-10-20.md` §4). Join it from a **different resource** than the gateway's,
and only when you are willing to be seen entering and leaving the room.

## Things that are not possible from outside a room

On the service tested, both `disco#info` and `disco#items` addressed to a room answer
`feature-not-implemented (501)` when the requester is not an occupant, so room config and occupant
lists cannot be read from outside. Either be an occupant, or have the room owner report what their
client shows. Do not conclude anything from a failed disco query.
