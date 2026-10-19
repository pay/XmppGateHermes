#!/usr/bin/env python3
"""Reproduce the room join exactly as the Hermes adapter does (same nick) and log
every presence stanza the room sends about us.

Usage: join_probe.py <jid-with-resource> <password> <server> <nick> <room>
Prints: self-presence, any rename/conflict/kick status codes, and whether the
room still considers us an occupant after N seconds.
"""
from __future__ import annotations

import asyncio
import sys
import time

import slixmpp

BEGIN = time.monotonic()


def stamp() -> str:
    return f"{time.monotonic() - BEGIN:6.2f}s"


class JoinProbe(slixmpp.ClientXMPP):
    def __init__(self, jid: str, password: str, nick: str, room: str) -> None:
        super().__init__(jid, password)
        self.nick = nick
        self.room = room
        self.self_presence = 0
        self.conflict = False
        self.add_event_handler("session_start", self.on_start)
        self.add_event_handler("group_presence", self.on_group_presence)
        self.add_event_handler("muc::%s::presence" % room, self.on_muc_presence)
        self.register_plugin("xep_0030")
        self.register_plugin("xep_0045")

    async def on_start(self, event) -> None:
        print(f"{stamp()} logged in as {self.boundjid}", flush=True)
        self.send_presence()
        await asyncio.sleep(1)
        print(f"{stamp()} joining {self.room} as nick '{self.nick}'", flush=True)
        try:
            await self.plugin["xep_0045"].join_muc_wait(
                self.room, self.nick, maxstanzas=0, timeout=15
            )
            print(f"{stamp()} join_muc_wait returned OK", flush=True)
        except Exception as exc:
            print(f"{stamp()} join_muc_wait raised {type(exc).__name__}: {exc}", flush=True)

    def _dump(self, presence) -> None:
        frm = str(presence["from"])
        typ = presence["type"] or "available"
        nick = frm.split("/", 1)[1] if "/" in frm else "?"
        codes = []
        try:
            for st in presence["muc"]["user"]["status"]:
                codes.append(st["code"])
        except Exception:
            pass
        reason = ""
        try:
            reason = presence["muc"]["user"]["reason"] or ""
        except Exception:
            pass
        if nick != self.nick:
            return  # someone else's presence: not our story
        print(
            f"{stamp()} PRESENCE(me) nick={nick} type={typ} codes={codes or '-'} reason={reason!r}",
            flush=True,
        )
        if typ == "available":
            self.self_presence += 1
        if "303" in codes:
            self.conflict = True
            print(f"{stamp()}   -> RENAMED by room (status 303)", flush=True)
        if "307" in codes or "301" in codes:
            self.conflict = True
            print(f"{stamp()}   -> KICKED/BANNED (status {'307' if '307' in codes else '301'})", flush=True)

    def on_group_presence(self, presence) -> None:
        self._dump(presence)

    def on_muc_presence(self, presence) -> None:
        self._dump(presence)


async def main() -> int:
    jid, password, server, nick, room = sys.argv[1:6]
    hp = server.split(":")
    host, port = hp[0], int(hp[1]) if len(hp) > 1 else 5222
    xmpp = JoinProbe(jid, password, nick, room)
    xmpp.enable_starttls = True
    xmpp.enable_direct_tls = False
    xmpp.enable_plaintext = False
    await xmpp.connect(host=host, port=port)
    await asyncio.sleep(28)
    print(
        f"{stamp()} SUMMARY self_presence={xmpp.self_presence} conflict={xmpp.conflict}",
        flush=True,
    )
    try:
        roster = xmpp.plugin["xep_0045"].rooms[room].roster
        print(f"{stamp()} our room roster now has {len(roster)} occupant(s): {sorted(roster)}", flush=True)
    except Exception as exc:
        print(f"{stamp()} roster read failed: {type(exc).__name__}: {exc}", flush=True)
    try:
        await xmpp.plugin["xep_0045"].leave_muc(room, nick)
    except Exception:
        pass
    await asyncio.sleep(1)
    xmpp.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
