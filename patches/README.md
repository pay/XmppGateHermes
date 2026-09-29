# Core patches

This repo is the XMPP **plugin**. One part of the fix, however, lives in the
Hermes core tree (`hermes_logging.py`) and cannot be carried inside a plugin.
The patch is kept here so it is never lost when `hermes update` overwrites core.

## `hermes_logging.py.patch`

**What it does.** Adds `"hermes_xmpp"` to the `COMPONENT_PREFIXES["gateway"]`
tuple used to route records into `gateway.log`.

**Why it is needed.** `gateway.log` is written through a `_ComponentFilter` that
only accepts records whose logger name starts with an allowed prefix:

```python
_COMPONENT_PREFIXES["gateway"] = ("gateway", "hermes_plugins", "plugins.platforms")
```

This plugin's `__init__.py` puts its own directory on `sys.path` and imports the
sibling package top-level, so any module logging under `hermes_xmpp.*` matched no
prefix and was dropped from `gateway.log` entirely. In practice a day of real
MUC join failures — 15 × `join NOT confirmed` — produced **zero** `gateway.log`
output, and were only findable in `errors.log` / `agent.log`.

The plugin-side fix (`hermes_xmpp/adapter.py`, pinning the logger to
`hermes_plugins.xmpp_platform.adapter`) is the load-bearing one. This core patch
is defence-in-depth for any code path that still imports `hermes_xmpp`
top-level.

## When you need to re-apply it

Any `hermes update` / `git pull` in the Hermes core tree will overwrite
`hermes_logging.py` and drop this change. Symptoms return: XMPP records vanish
from `gateway.log` again while remaining present in `errors.log`.

**Check first** (one line, expected to print several lines; zero means the patch
is gone):

```bash
grep hermes_plugins.xmpp_platform ~/.hermes/logs/gateway.log | tail
```

**Re-apply** from the Hermes core checkout:

```bash
cd <hermes-core-checkout>          # the dir containing hermes_logging.py
git apply /path/to/XmppGateHermes/patches/hermes_logging.py.patch
```

If the surrounding code has shifted, `git apply --3way` will retry with context
fuzz, and `patch -p1 --dry-run < …patch` will show whether it still fits.

**Then restart the gateway** — the component filter is read once at
`setup_logging(mode="gateway")` time, so a running gateway keeps the old filter:

```bash
hermes gateway restart
```

**Verify** — these lines should now appear in `gateway.log` (they did not before
the fix):

```
WARNING hermes_plugins.xmpp_platform.adapter: XMPP: joining MUC <room> as <nick> (resource <res>)
WARNING hermes_plugins.xmpp_platform.adapter: XMPP: MUC <room> join confirmed (<n> occupant(s))
ERROR   hermes_plugins.xmpp_platform.adapter: XMPP: MUC <room> join NOT confirmed - server sent no self-presence ...
```

## A related pitfall: verifying a logging patch in-process

`hermes_logging.py` does not attach its file handlers to the root logger. Every
handler is registered through a `queue.SimpleQueue` + `QueueListener`, so
records are written **asynchronously on a listener thread**. A test that emits a
record and immediately reads the log file back sees an empty file and wrongly
concludes the filter is still broken. Always drain first:

```python
from hermes_logging import setup_logging, flush_log_queue
setup_logging(hermes_home=tmp, mode="gateway")
logger.warning("...")
flush_log_queue()          # blocks until the record is on disk
print((tmp / "logs" / "gateway.log").read_text())
```

## General rule for platform plugins

Never rely on `logging.getLogger(__name__)` inside a Hermes plugin. The plugin
loader's namespace is not guaranteed to match the prefixes in
`COMPONENT_PREFIXES`, and a `sys.path` + top-level import breaks it outright.
Pin the dotted name explicitly — the bundled
`plugins/platforms/google_chat/adapter.py` does this and its comment is the
canonical statement of the rule.
