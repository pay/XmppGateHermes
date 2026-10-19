#!/usr/bin/env python3
"""Minimal loopback XMPP c2s test server (RFC 6120 subset).

Purpose: give the Hermes XMPP adapter a *real* socket peer so the transport
stack (TCP -> STARTTLS -> SASL PLAIN -> resource bind -> session) can be
exercised end to end on a device with no XMPP account and no local server
package.

Implements just enough for slixmpp's client:
  - stream header / <stream:features> with <starttls><required/>
  - STARTTLS upgrade with an operator-supplied cert
  - SASL PLAIN against credentials from the command line
  - resource binding + legacy session IQ
  - replies to IQ get/set addressed to the bound full JID (ping/disco)
  - optional inbound <message> injection after the client is bound

Not a real XMPP server: no roster, no offline storage, no MUC, no MAM,
no server-to-server, no real authentication backend. Do not expose it.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import ssl
import sys
import time
from xml.etree import ElementTree as ET

NS_STREAM = "http://etherx.jabber.org/streams"
NS_TLS = "urn:ietf:params:xml:ns:xmpp-tls"
NS_SASL = "urn:ietf:params:xml:ns:xmpp-sasl"
NS_BIND = "urn:ietf:params:xml:ns:xmpp-bind"
NS_SESSION = "urn:ietf:params:xml:ns:xmpp-session"
NS_CLIENT = "jabber:client"

log = logging.getLogger("xmpp-test-server")
_serial = 0


def next_id() -> str:
    global _serial
    _serial += 1
    return f"srv{_serial}"


class Session(asyncio.Protocol):
    def __init__(self, opts: argparse.Namespace) -> None:
        self.opts = opts
        self.transport: asyncio.Transport | None = None
        self.buffer = ""
        self.stream_open = False
        self.secure = False
        self.authed = False
        self.bound_jid: str | None = None
        self.username: str | None = None
        self.upgrading = False
        self.peer = "?"

    # ---- plumbing -------------------------------------------------------
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        peer = transport.get_extra_info("peername")
        self.peer = f"{peer[0]}:{peer[1]}" if peer else "?"
        log.info("connection from %s", self.peer)

    def connection_lost(self, exc: Exception | None) -> None:
        log.info("connection closed by %s (exc=%r)", self.peer, exc)

    def send(self, raw: str) -> None:
        log.debug("S->C %s", raw.replace("\n", " "))
        if self.transport is not None:
            self.transport.write(raw.encode())

    def stream_header(self) -> None:
        self.send(
            "<?xml version='1.0'?>"
            f"<stream:stream xmlns='{NS_CLIENT}' xmlns:stream='{NS_STREAM}' "
            f"id='hermes-test-{next_id()}' from='{self.opts.domain}' version='1.0' xml:lang='en'>"
        )

    def reset_stream(self) -> None:
        self.stream_open = False
        self.buffer = ""

    def features(self) -> None:
        if not self.secure:
            body = f"<starttls xmlns='{NS_TLS}'><required/></starttls>"
        elif not self.authed:
            body = (
                f"<mechanisms xmlns='{NS_SASL}'>"
                "<mechanism>PLAIN</mechanism>"
                "</mechanisms>"
            )
        else:
            body = (
                f"<bind xmlns='{NS_BIND}'/>"
                f"<session xmlns='{NS_SESSION}'/>"
            )
        self.send(f"<stream:features>{body}</stream:features>")

    # ---- inbound --------------------------------------------------------
    def _extract_stanzas(self, buf: str) -> tuple[list[ET.Element], str]:
        """Pull complete top-level elements out of an XMPP stream buffer.

        Neither expat nor ElementTree accept a document with several root
        elements, and an XMPP stream is exactly that. So do the cheap
        well-formedness scan ourselves (client output has no comments/CDATA and
        '>' never appears inside an escaped attribute value) and hand each
        complete element to ElementTree on its own.
        """
        out: list[ET.Element] = []
        i = 0
        start: int | None = None
        depth = 0
        n = len(buf)
        while i < n:
            lt = buf.find("<", i)
            if lt == -1:
                break
            if buf.startswith("<?", lt) or buf.startswith("<!", lt):
                end = buf.find(">", lt)
                if end == -1:
                    break
                i = end + 1
                continue
            closing = buf.startswith("</", lt)
            # find end of tag, ignoring '>' inside quoted attribute values
            j = lt + 1
            quote = ""
            while j < n:
                ch = buf[j]
                if quote:
                    if ch == quote:
                        quote = ""
                elif ch in "\"'":
                    quote = ch
                elif ch == ">":
                    break
                j += 1
            if j >= n:
                break  # tag incomplete, wait for more bytes
            self_closing = buf.startswith("/>", j - 1)
            if closing:
                depth -= 1
                if depth == 0 and start is not None:
                    out.append(ET.fromstring(buf[start : j + 1]))
                    start = None
            elif self_closing:
                if depth == 0:
                    out.append(ET.fromstring(buf[lt : j + 1]))
                # nested self-closing tag: depth unchanged
            else:
                if depth == 0:
                    start = lt
                depth += 1
            i = j + 1
        rest = buf[start:] if start is not None else buf[i:]
        return out, rest

    def data_received(self, data: bytes) -> None:
        if self.upgrading:
            log.debug("pre-TLS bytes seen during upgrade: %d", len(data))
            return
        self.buffer += data.decode("utf-8", "replace")
        if not self.stream_open:
            end = self.buffer.find(">")
            if end == -1:
                return
            header, self.buffer = self.buffer[: end + 1], self.buffer[end + 1 :]
            if "stream:stream" not in header:
                log.warning("expected stream header, got %r", header)
                if self.transport is not None:
                    self.transport.close()
                return
            self.stream_open = True
            self.stream_header()
            self.features()
        if not self.buffer.strip():
            self.buffer = ""
            return
        log.debug("C->S %s", self.buffer.replace("\n", " "))
        try:
            stanzas, self.buffer = self._extract_stanzas(self.buffer)
        except ET.ParseError as exc:
            log.error("parse error: %s", exc)
            if self.transport is not None:
                self.transport.close()
            return
        for elem in stanzas:
            asyncio.ensure_future(self.handle(elem))

    # ---- stanza handling ------------------------------------------------
    def qname(self, elem: ET.Element) -> tuple[str, str]:
        tag = elem.tag
        if tag.startswith("{"):
            uri, local = tag[1:].split("}", 1)
            return uri, local
        return "", tag

    async def handle(self, elem: ET.Element) -> None:
        uri, local = self.qname(elem)
        log.info("stanza <%s> xmlns=%s from=%s", local, uri or "-", self.peer)
        if not self.secure and local == "starttls":
            self.upgrading = True
            self.send(f"<proceed xmlns='{NS_TLS}'/>")
            self.reset_stream()
            assert self.transport is not None
            loop = asyncio.get_running_loop()
            self.transport = await loop.start_tls(
                self.transport, self, self.opts.ssl_context, server_side=True
            )
            self.upgrading = False
            self.secure = True
            log.info("STARTTLS negotiated with %s (%s)", self.peer, self.opts.tls_version)
            return
        if local == "auth" and uri == NS_SASL:
            await self.handle_auth(elem)
            return
        if local == "iq":
            await self.handle_iq(elem)
            return
        if local == "presence":
            if self.bound_jid:
                self.send(
                    f"<presence from='{self.bound_jid}' to='{elem.get('to', self.bound_jid)}'/>"
                )
            return
        if local == "message":
            return  # client-originated chat: nothing to echo in this harness

    async def handle_auth(self, elem: ET.Element) -> None:
        mechanism = (elem.get("mechanism") or "").upper()
        payload = (elem.text or "").strip()
        if mechanism != "PLAIN":
            self.send(f"<failure xmlns='{NS_SASL}'><invalid-mechanism/></failure>")
            return
        try:
            decoded = base64.b64decode(payload).decode("utf-8", "replace")
            _authzid, authcid, password = decoded.split("\x00", 2)
        except Exception:
            self.send(f"<failure xmlns='{NS_SASL}'><malformed-request/></failure>")
            return
        if authcid != self.opts.user or password != self.opts.password:
            log.warning("auth FAILED for user=%r", authcid)
            self.send(f"<failure xmlns='{NS_SASL}'><not-authorized/></failure>")
            return
        self.username = authcid
        self.authed = True
        self.reset_stream()
        self.send(f"<success xmlns='{NS_SASL}'/>")
        log.info("SASL PLAIN succeeded for %s@%s", authcid, self.opts.domain)

    async def handle_iq(self, elem: ET.Element) -> None:
        iq_type = elem.get("type")
        iq_id = elem.get("id") or next_id()
        frm = elem.get("to") or self.bound_jid or self.opts.domain
        children = [self.qname(c) for c in elem]
        child_ns = children[0][0] if children else ""
        child_local = children[0][1] if children else ""
        if iq_type in ("get", "set") and child_local == "bind":
            resource = None
            for c in elem:
                for sub in c:
                    if self.qname(sub)[1] == "resource":
                        resource = sub.text or "hermes"
            resource = resource or "hermes"
            self.bound_jid = f"{self.username}@{self.opts.domain}/{resource}"
            self.send(
                f"<iq type='result' id='{iq_id}' to='{elem.get('from', self.bound_jid)}'>"
                f"<bind xmlns='{NS_BIND}'><jid>{self.bound_jid}</jid></bind></iq>"
            )
            log.info("resource bound: %s", self.bound_jid)
            await self.after_bind()
            return
        if iq_type in ("get", "set") and child_local == "session":
            self.send(f"<iq type='result' id='{iq_id}' to='{self.bound_jid}'/>")
            log.info("legacy session established")
            return
        if iq_type in ("get", "set") and child_local == "query" and child_ns == "http://jabber.org/protocol/disco#info":
            self.send(
                f"<iq type='result' id='{iq_id}' from='{frm}' to='{self.bound_jid}'>"
                f"<query xmlns='http://jabber.org/protocol/disco#info'>"
                f"<identity category='server' type='im' name='Hermes XMPP Test Server'/>"
                f"<feature var='http://jabber.org/protocol/disco#info'/>"
                f"<feature var='urn:xmpp:ping'/>"
                f"</query></iq>"
            )
            return
        if iq_type in ("get", "set"):
            self.send(f"<iq type='result' id='{iq_id}' from='{frm}' to='{self.bound_jid}'/>")
            log.info("answered IQ <%s> from %s", child_local or "?", frm)

    async def after_bind(self) -> None:
        if not self.opts.inject_from:
            return
        await asyncio.sleep(self.opts.inject_delay)
        text = self.opts.inject_text
        log.info("injecting inbound message from %s", self.opts.inject_from)
        self.send(
            f"<message from='{self.opts.inject_from}' to='{self.bound_jid}' type='chat' id='inj-1'>"
            f"<body>{text}</body>"
            f"<request xmlns='urn:xmpp:receipts'/></message>"
        )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5222)
    ap.add_argument("--domain", default="localhost")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--inject-from", default="")
    ap.add_argument("--inject-text", default="ping from the test peer")
    ap.add_argument("--inject-delay", type=float, default=3.0)
    ap.add_argument("--verbose", action="store_true")
    opts = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(opts.cert, opts.key)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    opts.ssl_context = ctx
    opts.tls_version = "TLSv1.2+"

    loop = asyncio.get_running_loop()
    server = await loop.create_server(lambda: Session(opts), opts.host, opts.port)
    log.info("test XMPP server listening on %s:%d (domain=%s)", opts.host, opts.port, opts.domain)
    async with server:
        await server.serve_forever()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
