"""Offline regressions against real slixmpp stanzas and retry machinery."""
import asyncio
import os
import types
import unittest
from unittest.mock import AsyncMock, patch

from slixmpp import Message
from slixmpp.stanza import Iq
from slixmpp.xmlstream import ET

from hermes_xmpp import adapter


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("XMPP_")}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "bot@example.org/old-resource", "password": "secret",
            "server": "example.org", "resource": "configured-resource",
            "dm_policy": "open", "send_read_receipts": True,
        }))
        self.thin = adapter._SlixmppClient(self.xmpp)

    def message(self, kind="chat", *, body: str | None = "hello", extra="", mid="m1"):
        xml = ET.Element("{jabber:client}message", {
            "from": "friend@example.org/phone", "to": "bot@example.org",
            "type": kind, "id": mid,
        })
        if body is not None:
            ET.SubElement(xml, "{jabber:client}body").text = body
        if extra:
            xml.append(ET.fromstring(extra))
        return Message(xml=xml, stream=self.thin.client, recv=True)

    async def test_bind_requests_configured_resource_in_real_iq(self):
        sent = []

        async def capture(iq, **kwargs):
            sent.append(ET.tostring(iq.xml))

        with patch.object(Iq, "send", capture):
            await self.thin.client.plugin["feature_bind"]._handle_bind_resource(None)
        xml = ET.fromstring(sent[0])
        resource = xml.find("{urn:ietf:params:xml:ns:xmpp-bind}bind/{urn:ietf:params:xml:ns:xmpp-bind}resource")
        assert resource is not None
        self.assertEqual(resource.text, "configured-resource")

    async def test_error_and_headline_are_not_dispatched(self):
        self.xmpp.handle_message = AsyncMock()
        for kind in ("error", "headline"):
            msg = self.message(kind)
            self.assertIsNone(adapter.parse_xmpp_message(msg, self.xmpp.settings))
            im = next(h for h in self.thin.client._XMLStream__handlers if h.name == "IM")
            self.assertTrue(im.match(msg))
            events = []
            with patch.object(self.thin.client, "event", side_effect=lambda name, stanza: events.append((name, stanza))):
                self.thin.client._handle_message(msg)
            self.assertEqual(events, [("message", msg)])
            await self.thin._on_message(events[0][1])
        self.xmpp.handle_message.assert_not_awaited()
        for kind in ("normal", "chat", "groupchat"):
            self.assertIsNotNone(adapter.parse_xmpp_message(self.message(kind), self.xmpp.settings))

    async def test_parser_preserves_xml_and_only_acknowledges_requested_markers(self):
        for extra, expected in (("", False), ('<markable xmlns="urn:xmpp:chat-markers:0"/>', True)):
            for mid in ("m1", ""):
                msg = self.message(extra=extra, mid=mid)
                before = ET.tostring(msg.xml)
                parsed = adapter.parse_xmpp_message(msg, self.xmpp.settings)
                self.assertEqual(ET.tostring(msg.xml), before)
                assert parsed is not None
                self.assertEqual(parsed.wants_chat_marker, expected)
                if not expected:
                    self.assertEqual(adapter.receipt_actions_for(parsed, self.xmpp.settings), [])

    async def test_real_receipt_and_marker_ids_are_read_without_mutation(self):
        for namespace, name in (("urn:xmpp:receipts", "received"), ("urn:xmpp:chat-markers:0", "displayed")):
            msg = self.message(extra=f'<{name} xmlns="{namespace}" id="prior"/>')
            before = ET.tostring(msg.xml)
            parsed = adapter.parse_xmpp_message(msg, self.xmpp.settings)
            assert parsed is not None
            self.assertTrue(parsed.is_marker_or_receipt)
            self.assertEqual(ET.tostring(msg.xml), before)

    async def test_bodyless_oob_dispatches_once_and_body_oob_is_not_duplicated(self):
        oob = '<x xmlns="jabber:x:oob"><url>https://example.org/file.png</url></x>'
        self.xmpp.on_xmpp_message = AsyncMock()
        handlers = self.thin.client._XMLStream__handlers
        for body in (None, "caption", ""):
            msg = self.message(body=body, extra=oob)
            before = ET.tostring(msg.xml)
            parsed = adapter.parse_xmpp_message(msg, self.xmpp.settings)
            assert parsed is not None
            self.assertIn("https://example.org/file.png", parsed.text)
            self.assertEqual(ET.tostring(msg.xml), before)
            self.xmpp.on_xmpp_message.reset_mock()
            # Execute the real matching callbacks without XMLStream networking.
            for handler in handlers:
                if handler.name in ("IM", "Hermes OOB") and handler.match(msg):
                    if handler.name == "IM":
                        await self.thin._on_message(msg)
                    else:
                        await handler._pointer(msg)
            self.xmpp.on_xmpp_message.assert_awaited_once_with(msg)

    async def test_sdk_never_autoacks_and_manual_receipts_obey_local_policy(self):
        self.xmpp.settings.dm_policy = "allowlist"
        self.xmpp.settings.allowed_users = {"friend@example.org"}
        client = types.SimpleNamespace(send_delivery_receipt=AsyncMock(), send_chat_marker=AsyncMock())
        self.xmpp._client = client
        self.xmpp.handle_message = AsyncMock()
        sdk = self.thin.client.plugin["xep_0184"]
        for sender, enabled, count in (("stranger", True, 0), ("friend", False, 0), ("friend", True, 1)):
            self.xmpp.settings.send_delivery_receipts = enabled
            msg = self.message(extra='<request xmlns="urn:xmpp:receipts"/>')
            msg["from"] = f"{sender}@example.org/phone"
            client.send_delivery_receipt.reset_mock()
            with patch.object(Message, "send") as send:
                sdk._handle_receipt_request(msg)
                send.assert_not_called()
            await self.xmpp.on_xmpp_message(msg)
            self.assertEqual(client.send_delivery_receipt.await_count, count)

    async def test_mixed_case_muc_self_echo_uses_nick_identity(self):
        self.xmpp.settings.nickname = "Bot"
        self.xmpp.settings.group_policy = "open"
        self.xmpp.settings.muc_require_mention = False
        self.xmpp.settings.anonymous_muc_policy = "mention_only"
        for nick, item, allowed in (("Bot", "", False), ("bot", "", True),
                                    ("Other", "bot@example.org", False),
                                    ("Other", "friend@example.org", True)):
            msg = self.message("groupchat", body="Bot: hello")
            msg["from"] = f"room@conference.example.org/{nick}"
            if item:
                msg.xml.append(ET.fromstring(f'<x xmlns="http://jabber.org/protocol/muc#user"><item jid="{item}"/></x>'))
            msg = Message(xml=msg.xml, stream=self.thin.client, recv=True)
            parsed = adapter.parse_xmpp_message(msg, self.xmpp.settings)
            assert parsed is not None
            self.assertEqual(adapter.authorized_xmpp_message(parsed, self.xmpp.settings), allowed)

    async def test_gateway_veto_blocks_receipts_and_reactions_but_not_intake(self):
        if not hasattr(self.xmpp, "set_authorization_check"):
            self.skipTest("installed Hermes authorization callback required")
        client = types.SimpleNamespace(is_connected=lambda: True,
                                       send_delivery_receipt=AsyncMock(), send_reactions=AsyncMock(return_value=True))
        self.xmpp._client = client
        self.xmpp.handle_message = AsyncMock()
        msg = self.message(extra='<request xmlns="urn:xmpp:receipts"/>')
        msg["thread"] = "thread-1"
        self.xmpp.settings.send_delivery_receipts = True

        def broken(*args, **kwargs):
            raise RuntimeError("offline authorization failure")

        for verdict in (False, None, "truthy", broken, True):
            check = verdict if callable(verdict) else lambda *args, **kwargs: verdict
            self.xmpp.set_authorization_check(check)
            client.send_delivery_receipt.reset_mock()
            client.send_reactions.reset_mock()
            await self.xmpp.on_xmpp_message(msg)
            event = self.xmpp.handle_message.await_args.args[0]
            await self.xmpp.react_to_event(event, ["ok"])
            await self.xmpp.on_processing_start(event)
            await self.xmpp.on_processing_complete(event, types.SimpleNamespace(value="success"))
            self.assertEqual(client.send_delivery_receipt.await_count, 1 if verdict is True else 0)
            self.assertEqual(client.send_reactions.await_count, 3 if verdict is True else 0)
            event.raw_message = None
            self.assertEqual(self.xmpp._reaction_target_for_event(event) is not None, verdict is True)
        # Host callbacks receive the exact thread scope when present.
        calls = []
        self.xmpp.set_authorization_check(lambda *args, **kwargs: calls.append((args, kwargs)) or True)
        await self.xmpp.on_xmpp_message(msg)
        self.assertEqual(calls, [(("friend@example.org", "dm", "friend@example.org"), {"thread_id": "thread-1"})])

    def test_legacy_host_check_does_not_require_thread_keyword(self):
        self.xmpp._authorization_check = lambda *_: True
        self.xmpp._is_sender_authorized = lambda user, kind, chat: True
        self.assertTrue(self.xmpp._gateway_allows_side_effect("friend", "dm", "chat"))
        self.assertFalse(self.xmpp._gateway_allows_side_effect("friend", "dm", "chat", "scope"))

    def test_resolved_policy_properties(self):
        cfg = types.SimpleNamespace(extra={"jid": "bot@example.org", "password": "secret",
                                          "dm_policy": "allowlist", "group_policy": "allowlist"})
        with patch.dict(os.environ, {"XMPP_DM_POLICY": "open", "XMPP_GROUP_POLICY": "open"}):
            xmpp = adapter.XMPPAdapter(cfg)
        self.assertEqual((xmpp._dm_policy, xmpp._group_policy), ("open", "open"))
        xmpp.settings.dm_policy = "allowlist"
        xmpp.settings.allow_all_users = True
        self.assertEqual(xmpp._dm_policy, "open")
        xmpp.settings.dm_policy = "disabled"
        self.assertEqual(xmpp._dm_policy, "disabled")

    def test_real_gateway_does_not_trust_stale_yaml_allowlist_for_open_intake(self):
        try:
            from gateway.authz_mixin import GatewayAuthorizationMixin
        except ImportError:
            self.skipTest("installed Hermes authorization mixin required")
        from enum import Enum
        platform = Enum("OfflinePlatform", {"XMPP": "xmpp"}).XMPP
        cfg = types.SimpleNamespace(extra={"jid": "bot@example.org", "password": "secret",
                                          "dm_policy": "allowlist", "group_policy": "allowlist",
                                          "allowed_users": ["friend@example.org"]})
        with patch.dict(os.environ, {"XMPP_DM_POLICY": "open", "XMPP_GROUP_POLICY": "open"}, clear=True):
            xmpp = adapter.XMPPAdapter(cfg)
            gateway = GatewayAuthorizationMixin()
            gateway.adapters = {platform: xmpp}
            gateway.config = types.SimpleNamespace(platforms={platform: cfg})
            for kind in ("dm", "group"):
                source = types.SimpleNamespace(platform=platform, chat_type=kind,
                                               chat_id="chat@example.org", user_id="stranger@example.org",
                                               delivered_via_upstream_relay=False)
                self.assertEqual(gateway._adapter_policy(platform, kind, None), "open")
                self.assertFalse(gateway._is_user_authorized(source))

    async def test_real_failed_socket_attempt_retry_is_settled_on_session_timeout(self):
        client = self.thin.client
        retry_started = asyncio.Event()
        client.add_event_handler("reconnect_delay", lambda _: retry_started.set())
        retry = None

        async def timeout(*args, **kwargs):
            nonlocal retry
            await retry_started.wait()
            retry = client._current_connection_attempt
            self.assertIsNotNone(retry)
            self.assertFalse(retry.done())
            raise TimeoutError("offline session timeout")

        def release(key):
            self.assertEqual(key, "offline-lock")
            self.assertTrue(retry.cancelled())
            self.assertIsNone(client._current_connection_attempt)

        with patch.object(client, "_attempt_connection", new=AsyncMock(return_value=False)) as attempt, \
             patch.object(client, "wait_until", new=timeout), \
             patch.object(adapter, "check_requirements", return_value=True), \
             patch.object(adapter, "_SlixmppClient", return_value=self.thin), \
             patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(True, "offline-lock")), \
             patch.object(adapter, "_release_xmpp_identity_lock", side_effect=release) as released:
            try:
                self.assertFalse(await self.xmpp.connect())
            finally:
                pending = client._current_connection_attempt
                if pending is not None:
                    await self.settle_retry(pending)
            attempt.assert_awaited()
            released.assert_called_once()
        self.assertIsNone(self.xmpp._client)

    async def start_real_retry(self):
        client = self.thin.client
        # Never allow a regression or a slow test to fall through to real sockets.
        attempt = patch.object(client, "_attempt_connection", new=AsyncMock(return_value=False))
        attempt.start()
        self.addCleanup(attempt.stop)
        client.custom_address = ("example.org", 5222)
        client._current_connection_attempt = asyncio.get_running_loop().create_future()
        retry = client.reschedule_connection_attempt()
        assert retry is not None
        entered = asyncio.Event()
        client.add_event_handler("reconnect_delay", lambda _: entered.set())
        await entered.wait()
        self.assertFalse(retry.done())
        self.assertIsNone(client.transport)
        self.addAsyncCleanup(self.settle_retry, retry)
        return retry

    async def settle_retry(self, retry):
        retry.cancel()
        await asyncio.gather(retry, return_exceptions=True)

    async def test_failed_connect_settles_real_retry_before_releasing_lock(self):
        retry = await self.start_real_retry()
        self.xmpp._client = self.thin
        self.xmpp._lock_key = "offline-lock"

        def release(key):
            self.assertEqual(key, "offline-lock")
            self.assertTrue(retry.cancelled())
            self.assertIsNone(self.thin.client._current_connection_attempt)

        with patch.object(adapter, "_release_xmpp_identity_lock", side_effect=release) as released:
            await self.xmpp._finish_connect_cleanup(self.thin, "offline-lock")
        released.assert_called_once()

    async def test_stale_real_retry_cleanup_preserves_replacement(self):
        retry = await self.start_real_retry()
        replacement = object()
        self.xmpp._client = replacement
        self.xmpp._lock_key = "replacement-lock"
        with patch.object(adapter, "_release_xmpp_identity_lock") as release:
            await self.xmpp._finish_connect_cleanup(self.thin, "old-lock")
        self.assertTrue(retry.cancelled())
        self.assertIs(self.xmpp._client, replacement)
        self.assertEqual(self.xmpp._lock_key, "replacement-lock")
        release.assert_not_called()

    async def test_explicit_edit_resource_is_not_replaced_by_last_sender(self):
        client = types.SimpleNamespace(is_connected=lambda: True, edit_message=AsyncMock())
        self.xmpp._client = client
        self.xmpp._last_full_jid_by_chat["friend@example.org"] = "friend@example.org/phone"
        with patch.object(self.xmpp, "_supports_message_correction", new=AsyncMock(return_value=True)) as supports:
            result = await self.xmpp.edit_message("friend@example.org/desktop", "prior", "new")
        self.assertTrue(result.success)
        supports.assert_awaited_once_with("friend@example.org/desktop", "chat")
        self.assertEqual(client.edit_message.await_args.args[0], "friend@example.org/desktop")
