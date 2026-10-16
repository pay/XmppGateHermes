# Known issues & compatibility

Bugs, environment quirks, and limitations found on the authoring device. Everything here is
**a finding about that environment** unless marked otherwise — do not read any of it as a
universal Hermes defect.

## Environment context

- Hermes Agent `v0.22.0+canary`, APT/bundle payload under `$PREFIX/lib/hermes-agent`.
- Python 3.14, `sys.platform == "android"` (Termux, aarch64).
- Telegram gateway + XMPP adapter confirmed working concurrently in this environment.

---

## 1. Plugin manager admission fails on this Termux build

**Severity: blocks the normal enable path. Workaround documented.**

`hermes plugins enable <any-plugin>` (not just XMPP) fails during the dependency-admission
step:

```
uv lock exited 1 … playwright==1.62.0 has no `python_full_version >= '3.14'`-compatible wheels
hermes-agent[google-meet]'s requirements are unsatisfiable
```

**Root cause (bisected on-device).** The admission step generates a temporary uv workspace —
the core `pyproject.toml` plus the plugin as a workspace member — and re-resolves the entire
graph. The core's `google-meet` extra pins `playwright==1.62.0`, which publishes only
platform wheels (macos/linux/win) and **zero sdists**. On `sys_platform == "android"` there
is no compatible artifact, so resolution fails.

Confirmed by experiment: a pristine `pyproject.toml` + `uv.lock` with **no** workspace member
re-validates fine (`uv lock` exits 0). Adding **any** member — including an empty one with
zero dependencies — triggers the full re-resolve and the playwright failure. So the trigger
is workspace membership itself, not XMPP.

**Not XMPP-specific.** Any plugin enable/disable hits it. The same install also has
`hermes pm doctor` crashing with `KeyError: 'sha256'`. `exclude-newer` is irrelevant (fails
with and without).

**Workaround.** Enable by editing `config.yaml` directly after a backup — see
`INSTALLATION.md` §4b. The payload is identical to what `cmd_enable` writes post-admission.
`hermes plugins info <key>` confirms `Status: enabled`.

**Status:** unresolved upstream; local workaround only.

---

## 2. `hermes gateway status` / `stop` are false negatives on Termux

**Severity: confusing, but harmless once known.**

Both commands probe systemd/launchd to detect a running gateway. Android has neither, so a
perfectly healthy gateway is reported as "not running", and `hermes gateway stop` reports
"No gateway running for this profile" for a live process.

**Workaround.** Use `~/gate.sh status|stop|restart`, which read
`~/.hermes/gateway_state.json` and validate the pid against `/proc/<pid>/cmdline` (rejecting
stale/zombie pids), and send `SIGTERM` directly on stop. Or read `gateway_state.json` by
hand. The helper is a local convenience script, not part of Hermes.

**Status:** environmental; upstream detection doesn't cover Termux.

---

## 3. PM sync evicts manually-installed packages

**Severity: high — can kill both messaging platforms at once.**

The PM syncs with `uv sync --frozen --all-packages` and **no `--inexact`** — exact mode.
Anything installed outside the lockfile via `uv pip` is removed. On this install that is
`slixmpp` **and** `python-telegram-bot`, so a single `hermes pm install` / repair /
*successful* admission can take down Telegram **and** XMPP together.

**Workaround.** Don't run PM install/sync while manual uv-pip installs carry the platforms.
The failed admission in #1 accidentally protects you here (it never reaches the sync). If
both platforms die right after a PM operation, reinstall both and restart — see
`TROUBLESHOOTING.md` §3.

**Status:** environmental design consequence; upstream PM assumes lockfile-managed deps.

---

## 4. Two adapter versions exist (repo copy is newer than the installed copy)

**Severity: cosmetic/observability, not functional.**

This repo's `hermes_xmpp/adapter.py` (2459 lines) is **newer** than the copy installed on the
authoring device (2428 lines). The 41-line delta is two improvements present in the repo but
not in the installed runtime:

1. **Pinned logger name** — repo uses
   `logging.getLogger("hermes_plugins.xmpp_platform.adapter")`; the installed copy uses
   `__name__` (which resolves to `hermes_xmpp.adapter` and gets filtered out of
   `gateway.log`, see `patches/README.md`).
2. **Stricter MUC join confirmation** — repo requires a real self-presence + non-empty
   occupant mapping before logging `join confirmed`, and emits a descriptive error otherwise.
   The installed copy uses the looser `room in muc.rooms[None]`.

**Both versions pass the same tests** (the 4 pre-fix failures were identical on both — see
`TESTING.md`). The repo version is kept because it is the more correct of the two. The
installed runtime copy is simply one revision behind; a reinstall from this repo would
converge it.

**Status:** expected; not a fault.

---

## 5. `hermes pm doctor` crashes

**Severity: diagnostic tooling unavailable.**

```
KeyError: 'sha256'
```

Same install as #1. `pm doctor` checks managed tools and is a *different* interface from
Python extras; it is broken on this build, so it can't be used to sanity-check the PM state.

**Status:** unresolved upstream; work around by reading `hermes pm status` output and
`gateway_state.json` directly.

---

## 6. A new platform adapter never hot-loads

**Severity: operational constraint, by design.**

A platform adapter connects **only at gateway startup**. The control-socket `reload-plugins`
verb rewires handlers on already-live adapters; it never constructs or connects a new
adapter. Enabling XMPP therefore always requires a restart, and the restart drops both
platforms for ~25–30 s. Because the Telegram adapter sets `drop_pending_on_cold_boot: true`,
messages arriving in that window are **discarded**, not queued.

**Workaround.** Restart only when chats are quiet. This is a design property of the Hermes
gateway, documented here so the downtime isn't a surprise.

---

## 7. Groupchat delivery receipts / read markers are disabled

**Severity: intentional limitation.**

XEP-0333 chat markers in MUCs need careful handling of stanza IDs (XEP-0359), so the adapter
sends markers/receipts for **direct messages only** and disables them in groupchats. Not a
bug — a deliberate conservative choice, flagged so nobody expects read receipts in rooms.

---

## 8. OMEMO / E2E encryption not implemented

**Severity: feature gap.**

This adapter does end-to-end encryption only insofar as the server's TLS provides it
transport-level. There is no OMEMO support. If you need E2E in direct messages, this adapter
is not sufficient on its own.

---

## Third-party code & licensing

- The adapter, manifest and tests derive from the upstream **hermes-xmpp** plugin by
  Emma Apollo, **MIT** (`LICENSE`).
- `slixmpp` is **MIT**. Hermes Agent (Nous Research) is **MIT**.
- No third-party source was copied into this repo beyond the MIT-licensed plugin this repo
  *is*. The optional core patch in `patches/` modifies one tuple in Hermes' own
  `hermes_logging.py`; it carries no new code and stays MIT.

If you redistribute, keep the MIT license file and the upstream attribution.
