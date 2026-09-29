import asyncio
import os
import tempfile
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from typing import Any, cast

from hermes_xmpp import adapter


def _win_tmp_path(suffix: str) -> str:
    """Return a writable temp file path on Windows (uses tempfile.mktemp)."""
    return tempfile.mktemp(suffix=suffix, prefix="hermes-test-")


def clear_xmpp_env():
    for key in list(os.environ):
        if key.startswith("XMPP_"):
            os.environ.pop(key, None)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        clear_xmpp_env()

    def tearDown(self):
        clear_xmpp_env()

    def test_settings_support_policy_port_and_aliases_from_yaml(self):
        cfg = types.SimpleNamespace(
            extra={
                "jid": "Bot@Example.Org/hermes",
                "server": "chat.example.org",
                "port": 5223,
                "password": "secret",
                "dm_policy": "open",
                "group_policy": "allowlist",
                "rooms": ["room@conference.example.org"],
                "groups": ["other@conference.example.org"],
                "allow_from": ["*@example.org"],
                "dm_allowlist": ["friend@example.org"],
                "group_allow_from": ["mod@example.org"],
                "allowed_rooms": ["room@conference.example.org"],
            }
        )
        settings = adapter.XmppSettings.from_config(cfg)
        self.assertEqual(settings.jid, "Bot@Example.Org/hermes")
        self.assertEqual(settings.server, "chat.example.org")
        self.assertEqual(settings.port, 5223)
        self.assertEqual(settings.dm_policy, "open")
        self.assertEqual(settings.group_policy, "allowlist")
        self.assertIn("room@conference.example.org", settings.rooms)
        self.assertIn("other@conference.example.org", settings.rooms)
        self.assertIn("*@example.org", settings.allowed_users)
        self.assertIn("friend@example.org", settings.allowed_users)
        self.assertIn("mod@example.org", settings.group_allow_from)
        self.assertIn("room@conference.example.org", settings.allowed_rooms)

    def test_env_overrides_yaml_and_password_command(self):
        os.environ["XMPP_JID"] = "env@example.org"
        os.environ["XMPP_SERVER"] = "env-server.example.org"
        os.environ["XMPP_PORT"] = "5224"
        os.environ["XMPP_PASSWORD_COMMAND"] = "pass show xmpp/emma"
        with patch.object(adapter, "_read_secret_command", return_value="from-pass") as read_cmd:
            settings = adapter.XmppSettings.from_config(
                types.SimpleNamespace(extra={"jid": "yaml@example.org", "server": "yaml", "password": "yaml"})
            )
        read_cmd.assert_called_once_with("pass show xmpp/emma")
        self.assertEqual(settings.jid, "env@example.org")
        self.assertEqual(settings.server, "env-server.example.org")
        self.assertEqual(settings.port, 5224)
        self.assertEqual(settings.password, "from-pass")

    def test_fastfinge_env_aliases_are_accepted_without_renaming_primary_knobs(self):
        os.environ["XMPP_JID"] = "bot@example.org"
        os.environ["XMPP_HOST"] = "alias-host.example.org"
        os.environ["XMPP_MUC_ROOMS"] = "room@muc.example.org,other@muc.example.org"
        os.environ["XMPP_MUC_NICK"] = "AliasBot"
        os.environ["XMPP_HOME_CHANNEL"] = "home@example.org"
        os.environ["XMPP_MAX_MESSAGE_LENGTH"] = "1200"
        settings = adapter.XmppSettings.from_config(types.SimpleNamespace(extra={"password": "secret"}))
        self.assertEqual(settings.server, "alias-host.example.org")
        self.assertEqual(settings.rooms, ["room@muc.example.org", "other@muc.example.org"])
        self.assertEqual(settings.nickname, "AliasBot")
        self.assertEqual(settings.home_chat, "home@example.org")
        self.assertEqual(settings.text_chunk_limit, 1200)

    def test_apply_yaml_config_accepts_top_level_alias_block(self):
        result = adapter._apply_yaml_config(
            {"xmpp": {"jid": "bot@example.org", "host": "yaml-host.example.org", "muc_rooms": ["room@muc.example.org"], "max_message_length": 900}},
            {},
        )
        self.assertEqual(result["host"], "yaml-host.example.org")
        self.assertEqual(os.environ["XMPP_JID"], "bot@example.org")
        self.assertEqual(os.environ["XMPP_HOST"], "yaml-host.example.org")
        self.assertEqual(os.environ["XMPP_MUC_ROOMS"], "room@muc.example.org")
        self.assertEqual(os.environ["XMPP_MAX_MESSAGE_LENGTH"], "900")

    def test_canonical_env_names_win_over_compatibility_aliases(self):
        os.environ["XMPP_JID"] = "env@example.org"
        os.environ["XMPP_SERVER"] = "canonical.example.org"
        os.environ["XMPP_HOST"] = "alias.example.org"
        os.environ["XMPP_ROOMS"] = "canonical@muc.example.org"
        os.environ["XMPP_MUC_ROOMS"] = "alias@muc.example.org"
        os.environ["XMPP_NICKNAME"] = "CanonicalNick"
        os.environ["XMPP_MUC_NICK"] = "AliasNick"
        os.environ["XMPP_HOME_CHAT"] = "canonical-home@example.org"
        os.environ["XMPP_HOME_CHANNEL"] = "alias-home@example.org"
        os.environ["XMPP_TEXT_CHUNK_LIMIT"] = "456"
        os.environ["XMPP_MAX_MESSAGE_LENGTH"] = "123"
        cfg = types.SimpleNamespace(extra={"password": "secret"})

        settings = adapter.XmppSettings.from_config(cfg)

        self.assertEqual(settings.server, "canonical.example.org")
        self.assertEqual(settings.rooms, ["canonical@muc.example.org"])
        self.assertEqual(settings.nickname, "CanonicalNick")
        self.assertEqual(settings.home_chat, "canonical-home@example.org")
        self.assertEqual(settings.text_chunk_limit, 456)

    def test_processing_reactions_default_true_and_env_can_disable(self):
        cfg = types.SimpleNamespace(extra={"jid": "bot@example.org", "server": "chat.example.org", "password": "secret"})
        self.assertTrue(adapter.XmppSettings.from_config(cfg).reactions_enabled)
        os.environ["XMPP_REACTIONS"] = "false"
        self.assertFalse(adapter.XmppSettings.from_config(cfg).reactions_enabled)

    def test_processing_reaction_choices_accept_env_and_yaml_lists(self):
        cfg = types.SimpleNamespace(
            extra={
                "jid": "bot@example.org",
                "server": "chat.example.org",
                "password": "secret",
                "reaction_success_choices": ["✅", "❤️"],
                "reaction_failure_choices": "❌,💔",
            }
        )
        os.environ["XMPP_REACTION_START_CHOICES"] = "👀,😘"

        settings = adapter.XmppSettings.from_config(cfg)

        self.assertEqual(settings.reaction_start_choices, ("👀", "😘"))
        self.assertEqual(settings.reaction_success_choices, ("✅", "❤️"))
        self.assertEqual(settings.reaction_failure_choices, ("❌", "💔"))

    def test_empty_processing_reaction_choices_fall_back_to_defaults(self):
        cfg = types.SimpleNamespace(
            extra={
                "jid": "bot@example.org",
                "server": "chat.example.org",
                "password": "secret",
                "reaction_start_choices": "",
                "reaction_success_choices": [],
                "reaction_failure_choices": [],
            }
        )

        settings = adapter.XmppSettings.from_config(cfg)

        self.assertEqual(settings.reaction_start_choices, ("👀",))
        self.assertEqual(settings.reaction_success_choices, ("✅",))
        self.assertEqual(settings.reaction_failure_choices, ("❌",))

    def test_editable_progress_policy_defaults_to_known_support_and_accepts_env(self):
        cfg = types.SimpleNamespace(extra={"jid": "bot@example.org", "server": "chat.example.org", "password": "secret"})

        self.assertEqual(adapter.XmppSettings.from_config(cfg).editable_progress_policy, "known")
        self.assertEqual(adapter.XmppSettings.from_config(cfg).progress_delivery, "messages")

        os.environ["XMPP_EDITABLE_PROGRESS"] = "force"
        self.assertEqual(adapter.XmppSettings.from_config(cfg).editable_progress_policy, "known")

        os.environ["XMPP_PROGRESS_DELIVERY"] = "edit"
        self.assertEqual(adapter.XmppSettings.from_config(cfg).progress_delivery, "edit")

        os.environ["XMPP_EDITABLE_PROGRESS"] = "nonsense"
        os.environ["XMPP_PROGRESS_DELIVERY"] = "nonsense"
        settings = adapter.XmppSettings.from_config(cfg)
        self.assertEqual(settings.editable_progress_policy, "known")
        self.assertEqual(settings.progress_delivery, "messages")


class HelperTests(unittest.TestCase):
    def setUp(self):
        clear_xmpp_env()

    def tearDown(self):
        clear_xmpp_env()

    def test_jid_matching_supports_exact_wildcard_and_domain(self):
        self.assertTrue(adapter._matches_jid("user@example.org", {"user@example.org"}))
        self.assertTrue(adapter._matches_jid("user@example.org/resource", {"*@example.org"}))
        self.assertTrue(adapter._matches_jid("anywhere@example.net", {"*"}))
        self.assertFalse(adapter._matches_jid("user@evil.org", {"*@example.org"}))

    def test_target_normalization_and_group_detection(self):
        self.assertEqual(adapter._normalize_target("xmpp:user@example.org"), "user@example.org")
        self.assertEqual(adapter._normalize_target("xmpp:group:room@conference.example.org"), "room@conference.example.org")
        self.assertTrue(adapter._is_group_jid("room@conference.example.org"))
        self.assertTrue(adapter._is_group_jid("room@muc.example.org"))
        self.assertTrue(adapter._is_group_jid("room@rooms.example.org"))
        self.assertTrue(adapter._is_group_jid("room@groupchat.example.org"))
        self.assertTrue(adapter._is_group_jid("room@foo.muc.example.org"))
        self.assertTrue(adapter._is_group_jid("room:local-id"))
        self.assertFalse(adapter._is_group_jid("user@example.org"))
        # Substring traps: domain labels must match whole labels, not fragments.
        self.assertFalse(adapter._is_group_jid("user@notmuc.example.org"))
        self.assertFalse(adapter._is_group_jid("user@myconference.example.org"))
        self.assertFalse(adapter._is_group_jid("user@mucous.example.org"))
        self.assertFalse(adapter._is_group_jid("user@conferencex.example.org"))

    def test_mention_stripping_accepts_colon_comma_and_at_forms(self):
        cfg = types.SimpleNamespace(extra={"jid": "bot@example.org", "server": "s", "password": "p", "nickname": "Emma"})
        xmpp = adapter.XMPPAdapter(cfg)
        self.assertEqual(xmpp._strip_muc_mention("Emma: hello"), "hello")
        self.assertEqual(xmpp._strip_muc_mention("@Emma hello"), "hello")
        self.assertEqual(xmpp._strip_muc_mention("Emma, hello"), "hello")

    def test_split_text_for_xmpp_prefers_readable_boundaries_and_preserves_content(self):
        chunks = adapter.split_text_for_xmpp("alpha beta\ngamma delta", 11)
        self.assertEqual(chunks, ["alpha beta", "gamma delta"])
        hard_chunks = adapter.split_text_for_xmpp("abcdefghijkl", 5)
        self.assertEqual(hard_chunks, ["abcde", "fghij", "kl"])
        trailing_chunks = adapter.split_text_for_xmpp("abcde ", 5)
        self.assertEqual(trailing_chunks, ["abcde"])


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        clear_xmpp_env()

    def tearDown(self):
        clear_xmpp_env()

    def test_direct_policy_disabled_open_and_allowlist(self):
        disabled = adapter.XMPPAdapter(types.SimpleNamespace(extra={"jid": "b@e", "server": "s", "password": "p", "dm_policy": "disabled"}))
        self.assertFalse(disabled._authorized_direct_message("friend@example.org"))
        open_adapter = adapter.XMPPAdapter(types.SimpleNamespace(extra={"jid": "b@e", "server": "s", "password": "p", "dm_policy": "open"}))
        self.assertTrue(open_adapter._authorized_direct_message("anyone@example.org"))
        allow = adapter.XMPPAdapter(types.SimpleNamespace(extra={"jid": "b@e", "server": "s", "password": "p", "allowed_users": ["*@example.org"]}))
        self.assertTrue(allow._authorized_direct_message("friend@example.org/resource"))
        self.assertFalse(allow._authorized_direct_message("friend@evil.org"))

    def test_group_policy_room_allowlist_sender_allowlist_and_mention(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "s",
            "password": "p",
            "nickname": "Emma",
            "group_policy": "allowlist",
            "allowed_rooms": ["room@conference.example.org"],
            "group_allow_from": ["*@example.org"],
            "muc_require_mention": True,
        }))
        self.assertTrue(xmpp._authorized_group_message("friend@example.org", "Emma: hi", room_jid="room@conference.example.org", sender_authenticated=True))
        self.assertFalse(xmpp._authorized_group_message("friend@evil.org", "Emma: hi", room_jid="room@conference.example.org", sender_authenticated=True))
        self.assertFalse(xmpp._authorized_group_message("friend@example.org", "hi", room_jid="room@conference.example.org", sender_authenticated=True))
        self.assertFalse(xmpp._authorized_group_message("friend@example.org", "Emma: hi", room_jid="other@conference.example.org", sender_authenticated=True))

    def test_group_policy_allowlist_empty_allowed_rooms_denies_all_rooms(self):
        """Fail closed: allowlist + empty effective room set authorizes no room JID."""
        for empty in ([], set(), ""):
            with self.subTest(empty=empty):
                xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
                    "jid": "emma@example.org",
                    "server": "s",
                    "password": "p",
                    "nickname": "Emma",
                    "group_policy": "allowlist",
                    "rooms": ["joined@conference.example.org"],
                    "allowed_rooms": empty,
                    "group_allow_from": ["*@example.org"],
                    "muc_require_mention": True,
                }))
                self.assertEqual(xmpp.settings.allowed_rooms, set())
                self.assertFalse(
                    xmpp._authorized_group_message(
                        "friend@example.org",
                        "Emma: hi",
                        room_jid="joined@conference.example.org",
                        sender_authenticated=True,
                    )
                )
                self.assertFalse(
                    xmpp._authorized_group_message(
                        "friend@example.org",
                        "Emma: hi",
                        room_jid="evil@conference.example.org",
                        sender_authenticated=True,
                    )
                )

    def test_group_policy_allowlist_omitted_allowed_rooms_defaults_from_rooms(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "s",
            "password": "p",
            "nickname": "Emma",
            "group_policy": "allowlist",
            "rooms": ["joined@conference.example.org"],
            "group_allow_from": ["*@example.org"],
            "muc_require_mention": True,
        }))
        self.assertEqual(xmpp.settings.allowed_rooms, {"joined@conference.example.org"})
        self.assertTrue(
            xmpp._authorized_group_message(
                "friend@example.org",
                "Emma: hi",
                room_jid="joined@conference.example.org",
                sender_authenticated=True,
            )
        )
        self.assertFalse(
            xmpp._authorized_group_message(
                "friend@example.org",
                "Emma: hi",
                room_jid="evil@conference.example.org",
                sender_authenticated=True,
            )
        )

    def test_anonymous_muc_policy_respects_sender_identity_and_mention_gate(self):
        def authorized(policy, sender, text, *, authenticated=False):
            xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
                "jid": "emma@example.org",
                "server": "s",
                "password": "p",
                "nickname": "Emma",
                "group_policy": "open",
                "anonymous_muc_policy": policy,
                "muc_require_mention": True,
            }))
            return xmpp._authorized_group_message(
                sender,
                text,
                sender_authenticated=authenticated,
            )

        self.assertFalse(authorized("deny", "guest", "Emma: hi"))
        self.assertTrue(
            authorized(
                "deny",
                "guest@example.org",
                "Emma: hi",
                authenticated=True,
            )
        )
        for policy in ("allow", "mention_only"):
            self.assertFalse(authorized(policy, "guest", "hi"))
            self.assertTrue(authorized(policy, "guest", "Emma: hi"))
            self.assertTrue(
                authorized(
                    policy,
                    "guest@example.org",
                    "Emma: hi",
                    authenticated=True,
                )
            )


class FakeMessage:
    def __init__(self, **values):
        self.values = values
        self.muc = values.get("muc", {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def __getitem__(self, key):
        return self.values.get(key, "")

    def get_mucnick(self):
        return self.values.get("mucnick", "")

    def get_child(self, name, namespace=None):
        return self.values.get((namespace, name))


def real_slix_muc_message(*, nick, item_jid=None):
    from slixmpp import Message
    from slixmpp.plugins.xep_0045.stanza import MUCMessage, MUCUserItem
    from slixmpp.plugins.xep_0184.stanza import Received as DeliveryReceipt
    from slixmpp.plugins.xep_0184.stanza import Request
    from slixmpp.plugins.xep_0333.stanza import Acknowledged, Displayed, Markable, Received
    from slixmpp.xmlstream import ET, register_stanza_plugin

    register_stanza_plugin(MUCMessage, MUCUserItem)
    register_stanza_plugin(Message, MUCMessage)
    for stanza in (Request, DeliveryReceipt, Markable, Received, Displayed, Acknowledged):
        register_stanza_plugin(Message, stanza)
    xml = ET.Element(
        "{jabber:client}message",
        {
            "from": f"room@muc.example.org/{nick}",
            "type": "groupchat",
            "id": "muc-auth",
        },
    )
    ET.SubElement(xml, "{jabber:client}body").text = "Emma: hello"
    muc = ET.SubElement(xml, "{http://jabber.org/protocol/muc#user}x")
    if item_jid is not None:
        ET.SubElement(muc, "{http://jabber.org/protocol/muc#user}item", {"jid": item_jid})
    return Message(xml=xml)


class ParseAndReceiptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_xmpp_env()

    def tearDown(self):
        clear_xmpp_env()

    def _settings(self, **extra):
        base = {
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
            "nickname": "Emma",
        }
        base.update(extra)
        return adapter.XmppSettings.from_config(types.SimpleNamespace(extra=base))

    def test_parse_authorize_and_event_text_are_pure_steps(self):
        settings = self._settings()
        msg = FakeMessage(
            body="hello",
            **{"from": "thanos@example.org/dino"},
            type="chat",
            id="m1",
        )
        parsed = adapter.parse_xmpp_message(msg, settings)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.text, "hello")
        self.assertEqual(parsed.chat_type, "dm")
        self.assertEqual(parsed.receipt_target, "thanos@example.org/dino")
        self.assertTrue(adapter.authorized_xmpp_message(parsed, settings))
        self.assertEqual(adapter.event_text_for(parsed, settings), "hello")

    def test_real_muc_item_jid_denies_allowlisted_looking_spoofed_nick(self):
        settings = self._settings(
            group_policy="open",
            group_allow_from=["thanos@example.org"],
            muc_require_mention=True,
        )
        parsed = adapter.parse_xmpp_message(
            real_slix_muc_message(
                nick="thanos@example.org",
                item_jid="attacker@evil.example",
            ),
            settings,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.user_id, "attacker@evil.example")
        self.assertFalse(adapter.authorized_xmpp_message(parsed, settings))

    def test_real_muc_item_jid_allows_authenticated_allowlisted_sender(self):
        settings = self._settings(
            group_policy="open",
            group_allow_from=["thanos@example.org"],
            muc_require_mention=True,
        )
        parsed = adapter.parse_xmpp_message(
            real_slix_muc_message(
                nick="anonymous-looking-nick",
                item_jid="thanos@example.org/resource",
            ),
            settings,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.user_id, "thanos@example.org")
        self.assertTrue(adapter.authorized_xmpp_message(parsed, settings))

    def test_real_muc_without_item_jid_follows_anonymous_policy(self):
        msg = real_slix_muc_message(nick="thanos@example.org")
        deny_settings = self._settings(
            group_policy="open",
            anonymous_muc_policy="deny",
            muc_require_mention=True,
        )
        mention_settings = self._settings(
            group_policy="open",
            anonymous_muc_policy="mention_only",
            muc_require_mention=True,
        )

        denied = adapter.parse_xmpp_message(msg, deny_settings)
        allowed = adapter.parse_xmpp_message(msg, mention_settings)

        self.assertIsNotNone(denied)
        self.assertIsNotNone(allowed)
        self.assertFalse(adapter.authorized_xmpp_message(denied, deny_settings))
        self.assertTrue(adapter.authorized_xmpp_message(allowed, mention_settings))

    def test_real_muc_with_malformed_item_jid_follows_anonymous_policy(self):
        settings = self._settings(
            group_policy="open",
            anonymous_muc_policy="deny",
            muc_require_mention=True,
        )

        parsed = adapter.parse_xmpp_message(
            real_slix_muc_message(
                nick="thanos@example.org",
                item_jid="not a jid",
            ),
            settings,
        )

        self.assertIsNotNone(parsed)
        self.assertFalse(adapter.authorized_xmpp_message(parsed, settings))

    def test_parse_preserves_xep_0201_thread(self):
        settings = self._settings()
        parsed = adapter.parse_xmpp_message(
            FakeMessage(
                body="hello",
                **{"from": "thanos@example.org/dino"},
                type="chat",
                id="m-thread",
                thread="thread-42",
            ),
            settings,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.thread_id, "thread-42")

    def test_parse_preserves_opaque_thread_id_exactly(self):
        settings = self._settings()
        parsed = adapter.parse_xmpp_message(
            FakeMessage(
                body="hello",
                **{"from": "thanos@example.org/dino"},
                type="chat",
                id="m-thread",
                thread=" thread-42 ",
            ),
            settings,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.thread_id, " thread-42 ")

    def test_unauthorized_messages_do_not_get_receipt_actions(self):
        settings = self._settings()
        msg = FakeMessage(
            body="hello",
            **{"from": "intruder@example.net/laptop"},
            type="chat",
            id="m2",
            request_receipt=True,
            markable=True,
        )
        parsed = adapter.parse_xmpp_message(msg, settings)
        self.assertFalse(adapter.authorized_xmpp_message(parsed, settings))
        # Caller sends actions only after authorization; helper remains data-only.
        self.assertEqual(
            [a.kind for a in adapter.receipt_actions_for(parsed, settings)],
            [adapter.XmppReceiptKind.DELIVERY_RECEIPT, adapter.XmppReceiptKind.RECEIVED_MARKER],
        )

    def test_receipt_actions_follow_xep_0184_and_xep_0333_settings(self):
        settings = self._settings(send_read_receipts=True)
        msg = FakeMessage(
            body="hello",
            **{"from": "thanos@example.org/dino"},
            type="chat",
            id="m3",
            request_receipt=True,
            markable=True,
        )
        parsed = adapter.parse_xmpp_message(msg, settings)
        self.assertTrue(adapter.authorized_xmpp_message(parsed, settings))
        actions = adapter.receipt_actions_for(parsed, settings)
        self.assertEqual(
            [a.kind for a in actions],
            [
                adapter.XmppReceiptKind.DELIVERY_RECEIPT,
                adapter.XmppReceiptKind.RECEIVED_MARKER,
                adapter.XmppReceiptKind.DISPLAYED_MARKER,
            ],
        )
        self.assertTrue(all(a.to_jid == "thanos@example.org/dino" for a in actions))
        self.assertTrue(all(a.message_id == "m3" for a in actions))

    def test_no_marker_loops_or_groupchat_marker_sends(self):
        settings = self._settings(send_read_receipts=True)
        marker_msg = FakeMessage(
            body="",
            **{"from": "thanos@example.org/dino"},
            type="chat",
            id="marker1",
            received={"id": "m3"},
        )
        self.assertIsNone(adapter.parse_xmpp_message(marker_msg, settings))

        group_msg = FakeMessage(
            body="Emma: hello",
            **{"from": "room@muc.example.org/thanos"},
            type="groupchat",
            id="g1",
            request_receipt=True,
            markable=True,
            muc={"jid": "thanos@example.org"},
            mucnick="thanos",
        )
        parsed = adapter.parse_xmpp_message(group_msg, settings)
        self.assertEqual(adapter.receipt_actions_for(parsed, settings), [])
        self.assertEqual(adapter.event_text_for(parsed, settings), "hello")

    async def test_adapter_sends_receipts_before_dispatch_for_authorized_dm(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
            "send_read_receipts": True,
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_delivery_receipt(self, to_jid, receipt_id, message_type="chat"):
                self.calls.append(("receipt", to_jid, receipt_id, message_type))

            async def send_chat_marker(self, to_jid, marker_id, marker, message_type="chat"):
                self.calls.append((marker, to_jid, marker_id, message_type))

        fake_client = FakeClient()
        xmpp._client = fake_client
        handled_events = []

        async def capture_event(event):
            handled_events.append(event)

        xmpp.handle_message = capture_event
        msg = FakeMessage(
            body="ping",
            **{"from": "thanos@example.org/dino"},
            type="chat",
            id="m4",
            request_receipt=True,
            markable=True,
        )
        await xmpp.on_xmpp_message(msg)
        self.assertEqual(fake_client.calls, [
            ("receipt", "thanos@example.org/dino", "m4", "chat"),
            ("received", "thanos@example.org/dino", "m4", "chat"),
            ("displayed", "thanos@example.org/dino", "m4", "chat"),
        ])
        self.assertEqual(len(handled_events), 1)
        self.assertEqual(handled_events[0].text, "ping")

    async def test_adapter_sends_composing_to_last_full_dm_resource_and_active_on_stop(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
            "reactions_enabled": False,
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_chat_state(self, to_jid, state, message_type="chat", *, thread_id=None):
                self.calls.append((state, to_jid, message_type, thread_id))

        fake_client = FakeClient()
        xmpp._client = fake_client
        async def ignore_event(event):
            return None

        xmpp.handle_message = ignore_event
        msg = FakeMessage(
            body="ping",
            **{"from": "thanos@example.org/dino"},
            type="chat",
            id="m5",
        )
        await xmpp.on_xmpp_message(msg)

        typing_task = asyncio.create_task(xmpp.send_typing(
            "thanos@example.org",
            metadata={"thread_id": " thread-42 "},
        ))
        await xmpp.on_processing_start(types.SimpleNamespace(
            source=types.SimpleNamespace(thread_id=" thread-42 "),
        ))
        await typing_task
        await xmpp.stop_typing("thanos@example.org")
        await xmpp.stop_typing("thanos@example.org")

        self.assertEqual(fake_client.calls, [
            ("composing", "thanos@example.org", "chat", " thread-42 "),
            ("active", "thanos@example.org", "chat", " thread-42 "),
        ])

    async def test_concurrent_thread_chat_states_keep_task_ownership(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
            "reactions_enabled": False,
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_chat_state(self, to_jid, state, message_type="chat", *, thread_id=None):
                self.calls.append((state, thread_id))

        fake_client = FakeClient()
        xmpp._client = fake_client
        ready = asyncio.Event()
        started = 0

        async def run_thread(thread_id):
            nonlocal started
            typing_task = asyncio.create_task(xmpp.send_typing(
                "thanos@example.org",
                metadata={"thread_id": thread_id},
            ))
            await xmpp.on_processing_start(types.SimpleNamespace(
                source=types.SimpleNamespace(thread_id=thread_id),
            ))
            await typing_task
            started += 1
            if started == 2:
                ready.set()
            await ready.wait()
            await xmpp.stop_typing("thanos@example.org")
            await xmpp.stop_typing("thanos@example.org")

        await asyncio.gather(run_thread("thread-a"), run_thread("thread-b"))

        self.assertCountEqual(fake_client.calls, [
            ("composing", "thread-a"),
            ("active", "thread-a"),
            ("composing", "thread-b"),
            ("active", "thread-b"),
        ])

    async def test_keep_typing_keeps_thread_context_across_wait_for_cleanup(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_chat_state(self, to_jid, state, message_type="chat", *, thread_id=None):
                self.calls.append((to_jid, state, thread_id))

        async def base_keep_typing(
            base_adapter,
            chat_id,
            interval=2.0,
            metadata=None,
            stop_event=None,
        ):
            await asyncio.wait_for(
                base_adapter.send_typing(chat_id, metadata=metadata),
                timeout=0.1,
            )
            await base_adapter.stop_typing(chat_id)

        fake_client = FakeClient()
        xmpp._client = fake_client
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/dino"

        with patch.object(adapter.BasePlatformAdapter, "_keep_typing", base_keep_typing, create=True):
            await asyncio.gather(
                xmpp._keep_typing("thanos@example.org", metadata={"thread_id": "thread-a"}),
                xmpp._keep_typing("thanos@example.org", metadata={"thread_id": "thread-b"}),
            )

        self.assertCountEqual(fake_client.calls, [
            ("thanos@example.org", "composing", "thread-a"),
            ("thanos@example.org", "active", "thread-a"),
            ("thanos@example.org", "composing", "thread-b"),
            ("thanos@example.org", "active", "thread-b"),
        ])

    async def test_unowned_interrupt_stop_cannot_emit_cross_thread_active(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        }))

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_chat_state(self, to_jid, state, message_type="chat", *, thread_id=None):
                self.calls.append((state, thread_id))

        started = asyncio.Event()

        async def base_keep_typing(
            base_adapter,
            chat_id,
            interval=2.0,
            metadata=None,
            stop_event=None,
        ):
            try:
                await asyncio.wait_for(
                    base_adapter.send_typing(chat_id, metadata=metadata),
                    timeout=0.1,
                )
                started.set()
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await base_adapter.stop_typing(chat_id)

        fake_client = FakeClient()
        xmpp._client = fake_client
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/dino"

        with patch.object(adapter.BasePlatformAdapter, "_keep_typing", base_keep_typing, create=True):
            typing_task = asyncio.create_task(xmpp._keep_typing(
                "thanos@example.org",
                metadata={"thread_id": "thread-a"},
            ))
            await started.wait()
            await xmpp.stop_typing("thanos@example.org")
            typing_task.cancel()
            await typing_task

        self.assertEqual(fake_client.calls, [
            ("composing", "thread-a"),
            ("active", "thread-a"),
        ])

    async def test_composing_repetition_is_suppressed_per_full_resource(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_chat_state(self, to_jid, state, message_type="chat", *, thread_id=None):
                self.calls.append((to_jid, state, thread_id))

        fake_client = FakeClient()
        xmpp._client = fake_client
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/dino"

        await xmpp.send_typing("thanos@example.org", metadata={"thread_id": "thread-42"})
        await xmpp.send_typing("thanos@example.org", metadata={"thread_id": "thread-42"})
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/cheogram"
        await xmpp.send_typing("thanos@example.org", metadata={"thread_id": "thread-42"})
        await xmpp.send_typing("thanos@example.org", metadata={"thread_id": "thread-42"})

        self.assertEqual(fake_client.calls, [
            ("thanos@example.org", "composing", "thread-42"),
        ])

    async def test_body_reply_active_state_suppresses_redundant_stop(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
            "reactions_enabled": False,
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.states = []

            async def send_chat_state(
                self,
                to_jid,
                state,
                message_type="chat",
                *,
                thread_id=None,
            ):
                self.states.append((state, thread_id))

            async def send_message(
                self,
                to_jid,
                text,
                message_type,
                *,
                thread_id=None,
                oob_url=None,
            ):
                return "reply-1"

        fake_client = FakeClient()
        xmpp._client = fake_client
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/dino"

        await xmpp.send_typing(
            "thanos@example.org",
            metadata={"thread_id": " opaque thread "},
        )
        await xmpp.send_typing(
            "thanos@example.org",
            metadata={"thread_id": " opaque thread "},
        )
        await xmpp.send(
            "thanos@example.org",
            "done",
            metadata={"thread_id": " opaque thread "},
        )
        await xmpp.stop_typing("thanos@example.org")
        await xmpp.stop_typing("thanos@example.org")

        self.assertEqual(fake_client.states, [
            ("composing", " opaque thread "),
        ])

    async def test_correction_active_state_suppresses_redundant_stop(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
            "progress_delivery": "edit",
            "reactions_enabled": False,
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.states = []

            async def send_chat_state(
                self,
                to_jid,
                state,
                message_type="chat",
                *,
                thread_id=None,
            ):
                self.states.append((state, thread_id))

            async def supports_message_correction(self, to_jid, message_type):
                return True

            async def edit_message(
                self,
                to_jid,
                message_id,
                text,
                message_type,
                *,
                thread_id=None,
            ):
                return message_id

        fake_client = FakeClient()
        xmpp._client = fake_client
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/dino"
        xmpp._sent_text_by_message_id["status-1"] = "old"

        await xmpp.send_typing(
            "thanos@example.org",
            metadata={"thread_id": " opaque thread "},
        )
        await xmpp.send_typing(
            "thanos@example.org",
            metadata={"thread_id": " opaque thread "},
        )
        result = await xmpp.edit_message(
            "thanos@example.org",
            "status-1",
            "new",
            metadata={"thread_id": " opaque thread "},
        )
        await xmpp.stop_typing("thanos@example.org")
        await xmpp.stop_typing("thanos@example.org")

        self.assertTrue(result.success)
        self.assertEqual(fake_client.states, [
            ("composing", " opaque thread "),
        ])

    async def test_adapter_puts_incoming_thread_on_message_source(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
        })
        xmpp = adapter.XMPPAdapter(cfg)
        handled_events = []

        async def capture_event(event):
            handled_events.append(event)

        xmpp.handle_message = capture_event
        xmpp._client = types.SimpleNamespace()
        await xmpp.on_xmpp_message(FakeMessage(
            body="ping",
            **{"from": "thanos@example.org/dino"},
            type="chat",
            id="m-thread",
            thread="thread-42",
        ))

        self.assertEqual(handled_events[0].source.thread_id, "thread-42")

    async def test_adapter_does_not_send_chat_state_when_disconnected(self):
        cfg = types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret"})
        xmpp = adapter.XMPPAdapter(cfg)
        await xmpp.send_typing("thanos@example.org")
        await xmpp.stop_typing("thanos@example.org")

    def test_slixmpp_client_enforces_starttls(self):
        class FakeClientXMPP:
            def __init__(self, jid, password):
                self.jid = jid
                self.password = password
                self.boundjid = types.SimpleNamespace(resource="")
                self.requested_jid = types.SimpleNamespace(resource="")
                self.plugin = {}
                self.enable_starttls = False
                self.enable_direct_tls = True
                self.enable_plaintext = True

            def register_handler(self, handler):
                pass

            def register_plugin(self, plugin, **kwargs):
                self.plugin[plugin] = object()

            def add_event_handler(self, *args, **kwargs):
                return None

        fake_slixmpp = types.SimpleNamespace(ClientXMPP=FakeClientXMPP)
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "resource": "hermes",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        with patch.dict(sys.modules, {"slixmpp": fake_slixmpp}):
            thin = adapter._SlixmppClient(xmpp)

        client = cast(Any, thin.client)
        self.assertTrue(client.enable_starttls)
        self.assertFalse(client.enable_direct_tls)
        self.assertFalse(client.enable_plaintext)
        self.assertIn("xep_0461", client.plugin)

    async def test_slixmpp_client_uses_configured_host_and_port(self):
        import inspect

        import slixmpp

        inspect.signature(slixmpp.ClientXMPP.connect).bind(
            object(),
            host="chat.example.org",
            port=5222,
        )
        calls = []

        class FakeClient:
            async def connect(self, *, host=None, port=None):
                calls.append((host, port))

            async def wait_until(self, event, timeout=None):
                calls.append((event, timeout))

        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.adapter = types.SimpleNamespace(
            settings=types.SimpleNamespace(connect_address=lambda: ("chat.example.org", 5222))
        )
        thin.client = FakeClient()

        self.assertTrue(await thin.connect())
        self.assertEqual(calls, [("chat.example.org", 5222), ("session_start", 20)])

    async def test_slixmpp_without_starttls_rejects_every_sasl_offer(self):
        from slixmpp.stanza import StreamFeatures
        from slixmpp.xmlstream import ET

        offers = (
            ("ANONYMOUS",),
            ("EXTERNAL",),
            ("EXTERNAL", "SCRAM-SHA-1"),
        )
        for mechanisms in offers:
            with self.subTest(mechanisms=mechanisms):
                cfg = types.SimpleNamespace(extra={
                    "jid": "bot@example.org",
                    "server": "chat.example.org",
                    "password": "secret",
                })
                thin = adapter._SlixmppClient(adapter.XMPPAdapter(cfg))
                client = cast(Any, thin.client)
                sent = []
                disconnects = []

                def send(data, use_filters=True, *, captured=sent):
                    captured.append(type(data).__name__)

                client.send = send

                def disconnect(*args, captured=disconnects, **kwargs):
                    captured.append((args, kwargs))
                    future = asyncio.get_running_loop().create_future()
                    future.set_result(None)
                    return future

                client.disconnect = disconnect
                mechanism_xml = "".join(
                    f"<mechanism>{mechanism}</mechanism>"
                    for mechanism in mechanisms
                )
                xml = ET.fromstring(
                    "<stream:features xmlns:stream='http://etherx.jabber.org/streams'>"
                    "<mechanisms xmlns='urn:ietf:params:xml:ns:xmpp-sasl'>"
                    f"{mechanism_xml}"
                    "</mechanisms>"
                    "</stream:features>"
                )
                features = StreamFeatures(xml=xml, stream=client)

                try:
                    await client._handle_stream_features(features)
                    self.assertEqual(sent, [])
                    self.assertEqual(len(disconnects), 1)
                finally:
                    client.abort()

    async def test_slixmpp_allows_sasl_after_starttls_negotiation(self):
        from slixmpp.stanza import StreamFeatures
        from slixmpp.xmlstream import ET

        cfg = types.SimpleNamespace(extra={
            "jid": "bot@example.org",
            "server": "chat.example.org",
            "password": "secret",
        })
        thin = adapter._SlixmppClient(adapter.XMPPAdapter(cfg))
        client = cast(Any, thin.client)
        client.features.add("starttls")
        sent = []
        disconnects = []

        def send(data, use_filters=True):
            sent.append(type(data).__name__)

        client.send = send

        def disconnect(*args, **kwargs):
            disconnects.append((args, kwargs))
            future = asyncio.get_running_loop().create_future()
            future.set_result(None)
            return future

        client.disconnect = disconnect
        xml = ET.fromstring(
            "<stream:features xmlns:stream='http://etherx.jabber.org/streams'>"
            "<mechanisms xmlns='urn:ietf:params:xml:ns:xmpp-sasl'>"
            "<mechanism>SCRAM-SHA-1</mechanism>"
            "</mechanisms>"
            "</stream:features>"
        )
        features = StreamFeatures(xml=xml, stream=client)

        try:
            await client._handle_stream_features(features)
            self.assertIn("Auth", sent)
            self.assertEqual(disconnects, [])
        finally:
            client.abort()

    def test_slixmpp_client_registers_disconnect_lifecycle_handlers(self):
        class FakeClientXMPP:
            def __init__(self, jid, password):
                self.jid = jid
                self.password = password
                self.boundjid = types.SimpleNamespace(resource="")
                self.requested_jid = types.SimpleNamespace(resource="")
                self.plugin = {}
                self.handlers = {}

            def register_handler(self, handler):
                pass

            def register_plugin(self, plugin, **kwargs):
                self.plugin[plugin] = object()

            def add_event_handler(self, event_name, handler, *args, **kwargs):
                self.handlers[event_name] = handler

            def is_connected(self):
                return True

        fake_slixmpp = types.SimpleNamespace(ClientXMPP=FakeClientXMPP)
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "resource": "hermes",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        with patch.dict(sys.modules, {"slixmpp": fake_slixmpp}):
            thin = adapter._SlixmppClient(xmpp)

        client = cast(Any, thin.client)
        self.assertIn("session_start", client.handlers)
        self.assertIn("message", client.handlers)
        self.assertIn("session_end", client.handlers)
        self.assertIn("disconnected", client.handlers)
        self.assertIs(client.handlers["session_end"], client.handlers["disconnected"])

    async def test_slixmpp_upload_uses_plugin_indexing_not_dict_get(self):
        class FakeUploadPlugin:
            def __init__(self):
                self.calls = []

            async def upload_file(self, file_path, content_type=None):
                self.calls.append((str(file_path), content_type))
                return "https://upload.example.org/file.bin"

        class FakePluginManager:
            def __init__(self, upload):
                self.upload = upload

            def __getitem__(self, key):
                if key != "xep_0363":
                    raise KeyError(key)
                return self.upload

            def get(self, *args, **kwargs):
                raise TypeError("PluginManager.get() missing 1 required positional argument: 'default'")

        upload = FakeUploadPlugin()
        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = types.SimpleNamespace(plugin=FakePluginManager(upload))
        result = await thin.upload_file("/tmp/file.bin", "application/octet-stream")
        self.assertEqual(result, "https://upload.example.org/file.bin")
        self.assertEqual(upload.calls, [("/tmp/file.bin", "application/octet-stream")])

    async def test_slixmpp_reactions_use_xep_0444_and_missing_plugin_returns_false(self):
        class FakeMessage:
            def __init__(self, mto, mtype):
                self.values = {"to": mto, "type": mtype, "reactions": {}}
                self.sent = False
                self.store_enabled = False

            def __getitem__(self, key):
                return self.values.setdefault(key, {})

            def __setitem__(self, key, value):
                self.values[key] = value

            def enable(self, key):
                if key == "store":
                    self.store_enabled = True

            def send(self):
                self.sent = True

        class FakeReactionsPlugin:
            def __init__(self):
                self.calls = []

            def set_reactions(self, msg, message_id, reactions):
                self.calls.append((msg, message_id, tuple(reactions)))
                msg.values["reactions"] = {"id": message_id, "values": tuple(reactions)}

        class FakeClient:
            def __init__(self, plugin):
                self.plugin = plugin
                self.messages = []

            def make_message(self, mto, mtype):
                msg = FakeMessage(mto, mtype)
                self.messages.append(msg)
                return msg

        reactions_plugin = FakeReactionsPlugin()
        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = FakeClient({"xep_0444": reactions_plugin})

        sent = await thin.send_reactions(
            "room@muc.example.org",
            "m1",
            ("👀",),
            "groupchat",
            thread_id=" reaction-thread ",
        )
        missing_thin = cast(Any, object.__new__(adapter._SlixmppClient))
        missing_thin.client = FakeClient({})
        missing = await missing_thin.send_reactions("thanos@example.org", "m1", ("👀",), "chat")

        self.assertTrue(sent)
        self.assertFalse(missing)
        self.assertEqual(reactions_plugin.calls[0][1:], ("m1", ("👀",)))
        self.assertEqual(thin.client.messages[0].values["reactions"], {"id": "m1", "values": ("👀",)})
        self.assertEqual(thin.client.messages[0].values["type"], "groupchat")
        self.assertEqual(thin.client.messages[0].values["thread"], " reaction-thread ")
        self.assertTrue(thin.client.messages[0].store_enabled)
        self.assertTrue(thin.client.messages[0].sent)

    async def test_slixmpp_send_message_puts_reply_and_oob_on_same_stanza(self):
        class FakeMessage:
            def __init__(self):
                self.values = {"oob": {}}
                self.sent = False

            def __setitem__(self, key, value):
                self.values[key] = value

            def __getitem__(self, key):
                return self.values.setdefault(key, {})

            def send(self):
                self.sent = True

        class FakeClient:
            def __init__(self):
                self.messages = []
                self.send_message_calls = []

            def make_message(self, mto, mbody, mtype):
                msg = FakeMessage()
                msg.values.update({"to": mto, "body": mbody, "type": mtype})
                self.messages.append(msg)
                return msg

            def send_message(self, **kwargs):
                self.send_message_calls.append(kwargs)

        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = FakeClient()
        thin.adapter = types.SimpleNamespace(settings=types.SimpleNamespace(send_chat_states=True))

        message_id = await thin.send_message(
            "thanos@example.org",
            "caption\nhttps://upload.example.org/image.png",
            "chat",
            thread_id="thread-42",
            oob_url="https://upload.example.org/image.png",
            reply_to="original-message",
        )

        self.assertTrue(message_id.startswith("hermes-"))
        self.assertEqual(len(thin.client.messages), 1)
        msg = thin.client.messages[0]
        self.assertTrue(msg.sent)
        self.assertEqual(msg.values["oob"]["url"], "https://upload.example.org/image.png")
        self.assertEqual(msg.values["chat_state"], "active")
        self.assertEqual(msg.values["thread"], "thread-42")
        self.assertEqual(msg.values["reply"]["id"], "original-message")
        self.assertEqual(thin.client.send_message_calls, [])

    async def test_slixmpp_chat_state_preserves_xep_0201_thread(self):
        class FakeMessage:
            def __init__(self):
                self.values = {}
                self.sent = False

            def __setitem__(self, key, value):
                self.values[key] = value

            def send(self):
                self.sent = True

        class FakeClient:
            def __init__(self):
                self.messages = []

            def make_message(self, *, mto=None, mtype=None):
                msg = FakeMessage()
                msg.values.update({"to": mto, "type": mtype})
                self.messages.append(msg)
                return msg

        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = FakeClient()

        await thin.send_chat_state(
            "thanos@example.org/dino",
            "composing",
            "chat",
            thread_id="thread-42",
        )

        self.assertEqual(thin.client.messages[0].values["thread"], "thread-42")
        self.assertEqual(thin.client.messages[0].values["chat_state"], "composing")
        self.assertTrue(thin.client.messages[0].sent)

    async def test_slixmpp_client_edit_message_sends_xep_0308_correction(self):
        class FakeCorrectionPlugin:
            def __init__(self):
                self.calls = []

            def set_correction(self, msg, message_id):
                self.calls.append((msg, message_id))
                msg.values["replace"] = {"id": message_id}

        class FakeMsg:
            def __init__(self):
                self.values: dict[str, Any] = {"replace": {}}
                self.sent = False

            def __setitem__(self, key, value):
                self.values[key] = value

            def __getitem__(self, key):
                self.values.setdefault(key, {})
                return self.values[key]

            def send(self):
                self.sent = True

        class FakeClient:
            def __init__(self):
                self.plugin = {"xep_0308": FakeCorrectionPlugin()}
                self.messages = []

            def make_message(self, *, mto=None, mbody=None, mtype=None):
                msg = FakeMsg()
                msg.values.update({"to": mto, "body": mbody, "type": mtype})
                self.messages.append(msg)
                return msg

        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = FakeClient()
        thin.adapter = types.SimpleNamespace(settings=types.SimpleNamespace(send_chat_states=True))

        replacement_id = await thin.edit_message(
            "thanos@example.org",
            "msg-1",
            "📖 read_file...",
            "chat",
            thread_id=" correction-thread ",
        )
        group_replacement_id = await thin.edit_message(
            "room@muc.example.org",
            "group-msg-1",
            "📖 read_file...",
            "groupchat",
            thread_id=" group-correction-thread ",
        )

        self.assertTrue(replacement_id.startswith("hermes-"))
        self.assertTrue(group_replacement_id.startswith("hermes-"))
        self.assertEqual(len(thin.client.messages), 2)
        msg = thin.client.messages[0]
        self.assertTrue(msg.sent)
        self.assertEqual(msg.values["body"], "📖 read_file...")
        self.assertEqual(msg.values["replace"], {"id": "msg-1"})
        self.assertEqual(msg.values["chat_state"], "active")
        self.assertEqual(msg.values["thread"], " correction-thread ")
        group_msg = thin.client.messages[1]
        self.assertEqual(group_msg.values["type"], "groupchat")
        self.assertEqual(group_msg.values["thread"], " group-correction-thread ")
        self.assertNotIn("chat_state", group_msg.values)
        self.assertEqual(thin.client.plugin["xep_0308"].calls, [
            (msg, "msg-1"),
            (group_msg, "group-msg-1"),
        ])

    async def test_slixmpp_client_edit_message_raises_when_xep_0308_missing(self):
        class FakeClient:
            plugin = {}

        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = FakeClient()
        thin.adapter = types.SimpleNamespace(settings=types.SimpleNamespace(send_chat_states=True))

        with self.assertRaisesRegex(RuntimeError, "XEP-0308"):
            await thin.edit_message("thanos@example.org", "msg-1", "📖 read_file...", "chat")

    async def test_adapter_probes_and_corrects_last_full_dm_resource(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
        }))

        class FakeClient:
            def __init__(self):
                self.probes = []
                self.corrections = []

            async def supports_message_correction(self, to_jid, message_type):
                self.probes.append((to_jid, message_type))
                return True

            async def edit_message(
                self,
                to_jid,
                message_id,
                text,
                message_type,
                *,
                thread_id=None,
            ):
                self.corrections.append((to_jid, message_id, text, message_type, thread_id))
                return message_id

        fake_client = FakeClient()
        xmpp._client = fake_client
        xmpp._sent_text_by_message_id["status-1"] = "old"
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/dino"

        first = await xmpp.edit_message(
            "thanos@example.org",
            "status-1",
            "first",
            metadata={"thread_id": " opaque thread "},
        )
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/cheogram"
        second = await xmpp.edit_message(
            "thanos@example.org",
            "status-1",
            "second",
            metadata={"thread_id": " opaque thread "},
        )

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(fake_client.probes, [
            ("thanos@example.org/dino", "chat"),
            ("thanos@example.org/cheogram", "chat"),
        ])
        self.assertEqual(fake_client.corrections, [
            ("thanos@example.org/dino", "status-1", "first", "chat", " opaque thread "),
            ("thanos@example.org/cheogram", "status-1", "second", "chat", " opaque thread "),
        ])

    async def test_hanging_correction_probe_falls_back_within_bound(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
        }))

        class FakeClient:
            def __init__(self):
                self.probes = []
                self.corrections = []

            async def supports_message_correction(self, to_jid, message_type):
                self.probes.append((to_jid, message_type))
                await asyncio.Event().wait()

            async def edit_message(self, *args, **kwargs):
                self.corrections.append((args, kwargs))

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/emacs"
        xmpp._sent_text_by_message_id["status-1"] = "old"

        with patch.object(adapter, "_MESSAGE_CORRECTION_SUPPORT_TIMEOUT", 0.01, create=True):
            result = await asyncio.wait_for(
                xmpp.edit_message("thanos@example.org", "status-1", "new"),
                timeout=0.1,
            )

        self.assertFalse(result.success)
        self.assertFalse(result.retryable)
        self.assertEqual(fake_client.probes, [("thanos@example.org/emacs", "chat")])
        self.assertEqual(fake_client.corrections, [])

    async def test_correction_without_full_resource_falls_back_without_probe(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
        }))

        class FakeClient:
            def __init__(self):
                self.probes = []
                self.corrections = []

            async def supports_message_correction(self, to_jid, message_type):
                self.probes.append((to_jid, message_type))
                return True

            async def edit_message(self, *args, **kwargs):
                self.corrections.append((args, kwargs))

        fake_client = FakeClient()
        xmpp._client = fake_client
        xmpp._sent_text_by_message_id["status-1"] = "old"

        result = await xmpp.edit_message("thanos@example.org", "status-1", "new")

        self.assertFalse(result.success)
        self.assertFalse(result.retryable)
        self.assertEqual(fake_client.probes, [])
        self.assertEqual(fake_client.corrections, [])

    def test_adapter_enables_generic_gateway_edit_paths(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret"}))

        self.assertIsNot(
            type(xmpp).edit_message,
            adapter.BasePlatformAdapter.edit_message,
        )
        self.assertIs(getattr(xmpp, "SUPPORTS_MESSAGE_EDITING", True), True)

    async def test_editable_preview_uses_bounded_core_fallback_when_edit_is_unsupported(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret"}))

        class FakeClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append(text)
                return f"msg-{len(self.messages)}"

            async def supports_message_correction(self, to_jid, message_type):
                return False

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)

        preview = await xmpp.send(
            "thanos@example.org",
            "partial",
            metadata={"expect_edits": True},
        )
        edit = await xmpp.edit_message(
            "thanos@example.org",
            cast(str, preview.message_id),
            "partial response",
        )
        final = await xmpp.send("thanos@example.org", "complete final")

        self.assertTrue(preview.success)
        self.assertFalse(edit.success)
        self.assertFalse(edit.retryable)
        self.assertTrue(final.success)
        self.assertEqual(fake_client.messages, ["partial", "complete final"])

    async def test_lifecycle_status_edits_existing_bubble_with_xep_0308(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "text_chunk_limit": 80,
            "progress_delivery": "edit",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []
                self.edits = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url))
                return f"msg-{len(self.messages)}"

            async def edit_message(self, to_jid, message_id, text, message_type, *, thread_id=None):
                self.edits.append((to_jid, message_id, text, message_type, thread_id))
                return f"edit-{len(self.edits)}"

            async def supports_message_correction(self, to_jid, message_type):
                return True

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/emacs"

        thread_metadata = {"chat_type": "dm", "thread_id": " progress-thread "}
        first = await xmpp.send(
            "thanos@example.org",
            "🔍 search_files...",
            metadata=thread_metadata,
        )
        edit = await xmpp.edit_message(
            chat_id="thanos@example.org",
            message_id=cast(str, first.message_id),
            content="🔍 search_files...\n📖 read_file...",
            metadata=thread_metadata,
        )
        duplicate = await xmpp.edit_message(
            chat_id="thanos@example.org",
            message_id=cast(str, first.message_id),
            content="🔍 search_files...\n📖 read_file...",
            metadata=thread_metadata,
        )

        self.assertTrue(edit.success)
        self.assertEqual(edit.message_id, first.message_id)
        self.assertTrue(duplicate.success)
        self.assertEqual(fake_client.messages, [
            ("thanos@example.org", "🔍 search_files...", "chat", " progress-thread ", None),
        ])
        self.assertEqual(fake_client.edits, [
            ("thanos@example.org/emacs", cast(str, first.message_id), "🔍 search_files...\n📖 read_file...", "chat", " progress-thread "),
        ])

    async def test_lifecycle_status_edit_unsupported_fails_without_extra_bubbles(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url))
                return f"msg-{len(self.messages)}"

            async def supports_message_correction(self, to_jid, message_type):
                return False

            async def edit_message(self, to_jid, message_id, text, message_type, *, thread_id=None):
                raise AssertionError("unsupported clients must be gated before sending correction stanzas")

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/emacs"

        first = await xmpp.send("thanos@example.org", "🔍 search_files...")
        result = await xmpp.edit_message(
            chat_id="thanos@example.org",
            message_id=cast(str, first.message_id),
            content="🔍 search_files...\n📖 read_file...",
        )

        self.assertFalse(result.success)
        self.assertFalse(result.retryable)
        self.assertIn("not supported", cast(str, result.error))
        self.assertEqual([call[1] for call in fake_client.messages], ["🔍 search_files..."])

    async def test_send_or_update_status_defaults_to_visible_messages(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []
                self.edits = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url))
                return f"msg-{len(self.messages)}"

            async def supports_message_correction(self, to_jid, message_type):
                return True

            async def edit_message(self, to_jid, message_id, text, message_type, *, thread_id=None):
                self.edits.append((to_jid, message_id, text, message_type))
                return f"edit-{len(self.edits)}"

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)

        first = await xmpp.send_or_update_status("thanos@example.org", "lifecycle", "Thinking…")
        second = await xmpp.send_or_update_status("thanos@example.org", "lifecycle", "Still working…")

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual([call[1] for call in fake_client.messages], ["Thinking…", "Still working…"])
        self.assertEqual(fake_client.edits, [])

    async def test_send_or_update_status_edits_one_status_bubble_when_supported(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []
                self.edits = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url))
                return f"msg-{len(self.messages)}"

            async def supports_message_correction(self, to_jid, message_type):
                return True

            async def edit_message(self, to_jid, message_id, text, message_type, *, thread_id=None):
                self.edits.append((to_jid, message_id, text, message_type))
                return f"edit-{len(self.edits)}"

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/emacs"

        first = await xmpp.send_or_update_status("thanos@example.org", "lifecycle", "Thinking…")
        second = await xmpp.send_or_update_status("thanos@example.org", "lifecycle", "Still working…")
        final = await xmpp.send("thanos@example.org", "normal final reply")

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertTrue(final.success)
        self.assertEqual(fake_client.messages, [
            ("thanos@example.org", "Thinking…", "chat", None, None),
            ("thanos@example.org", "normal final reply", "chat", None, None),
        ])
        self.assertEqual(fake_client.edits, [
            ("thanos@example.org/emacs", "msg-1", "Still working…", "chat"),
        ])

    async def test_status_bubbles_are_isolated_by_xmpp_thread(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []
                self.edits = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((text, thread_id))
                return f"msg-{len(self.messages)}"

            async def supports_message_correction(self, to_jid, message_type):
                return True

            async def edit_message(self, to_jid, message_id, text, message_type, *, thread_id=None):
                self.edits.append((message_id, text))
                return message_id

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)

        first = await xmpp.send_or_update_status(
            "thanos@example.org",
            "lifecycle",
            "thread A",
            metadata={"thread_id": "thread-a"},
        )
        second = await xmpp.send_or_update_status(
            "thanos@example.org",
            "lifecycle",
            "thread B",
            metadata={"thread_id": "thread-b"},
        )

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(fake_client.messages, [
            ("thread A", "thread-a"),
            ("thread B", "thread-b"),
        ])
        self.assertEqual(fake_client.edits, [])

    async def test_send_or_update_status_edit_unsupported_falls_back_to_visible_messages(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
            "editable_progress": "force",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []
                self.support_checks = 0

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url))
                return f"msg-{len(self.messages)}"

            async def supports_message_correction(self, to_jid, message_type):
                self.support_checks += 1
                return False

            async def edit_message(self, to_jid, message_id, text, message_type, *, thread_id=None):
                raise AssertionError("unsupported clients must not receive correction stanzas")

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/emacs"

        first = await xmpp.send_or_update_status("thanos@example.org", "lifecycle", "Thinking…")
        second = await xmpp.send_or_update_status("thanos@example.org", "lifecycle", "Still working…")
        third = await xmpp.send_or_update_status("thanos@example.org", "lifecycle", "Still still working…")

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertTrue(third.success)
        self.assertEqual([call[1] for call in fake_client.messages], [
            "Thinking…",
            "Still working…",
            "Still still working…",
        ])
        self.assertEqual(fake_client.support_checks, 2)

    async def test_send_uses_chat_type_for_domains_that_only_substring_match_muc(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url))
                return f"msg-{len(self.messages)}"

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)

        result = await xmpp.send("user@notmuc.example.org", "hello")

        self.assertTrue(result.success)
        self.assertEqual(fake_client.messages, [
            ("user@notmuc.example.org", "hello", "chat", None, None),
        ])

    async def test_threaded_muc_send_preserves_opaque_thread(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None):
                self.messages.append((to_jid, text, message_type, thread_id))
                return "muc-message-1"

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)

        result = await xmpp.send(
            "room@muc.example.org",
            "hello room",
            metadata={"chat_type": "group", "thread_id": " muc-thread "},
        )

        self.assertTrue(result.success)
        self.assertEqual(fake_client.messages, [
            ("room@muc.example.org", "hello room", "groupchat", " muc-thread "),
        ])

    async def test_threaded_muc_correction_preserves_opaque_thread(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "progress_delivery": "edit",
            "editable_progress": "known",
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.edits = []

            async def supports_message_correction(self, to_jid, message_type):
                return True

            async def edit_message(self, to_jid, message_id, text, message_type, *, thread_id=None):
                self.edits.append((to_jid, message_id, text, message_type, thread_id))
                return message_id

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)
        xmpp._sent_text_by_message_id["muc-status-1"] = "old"

        result = await xmpp.edit_message(
            "room@muc.example.org",
            "muc-status-1",
            "new",
            metadata={"chat_type": "group", "thread_id": " muc-thread "},
        )

        self.assertTrue(result.success)
        self.assertEqual(fake_client.edits, [
            ("room@muc.example.org", "muc-status-1", "new", "groupchat", " muc-thread "),
        ])

    async def test_adapter_chunks_long_text_and_returns_continuation_ids(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "text_chunk_limit": 12,
        })
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None, reply_to=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url, reply_to))
                return f"msg-{len(self.messages)}"

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)

        result = await xmpp.send(
            "thanos@example.org",
            "hello brave little world",
            reply_to="orig-msg",
            metadata={"thread_id": " thread-42 "},
        )

        self.assertTrue(result.success)
        self.assertEqual(result.message_id, "msg-2")
        self.assertEqual(result.continuation_message_ids, ("msg-1",))
        self.assertEqual(fake_client.messages, [
            ("thanos@example.org", "hello brave", "chat", " thread-42 ", None, "orig-msg"),
            ("thanos@example.org", "little world", "chat", " thread-42 ", None, None),
        ])

    async def test_sent_text_cache_is_bounded_and_retains_recent_noop_detection(self):
        xmpp = adapter.XMPPAdapter(types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        }))

        for index in range(adapter._SENT_TEXT_CACHE_LIMIT + 5):
            xmpp._remember_sent_text(f"message-{index}", f"text-{index}")

        self.assertEqual(len(xmpp._sent_text_by_message_id), adapter._SENT_TEXT_CACHE_LIMIT)
        self.assertNotIn("message-0", xmpp._sent_text_by_message_id)
        recent = adapter._SENT_TEXT_CACHE_LIMIT + 4
        self.assertFalse(xmpp._message_text_changed(f"message-{recent}", f"text-{recent}"))

    async def test_media_upload_deterministic_failures_are_not_retryable(self):
        cfg = types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret"})
        xmpp = adapter.XMPPAdapter(cfg)

        class UploadServiceNotFound(Exception):
            pass

        class FakeClient:
            async def upload_file(self, file_path, content_type=None):
                raise UploadServiceNotFound("HTTP Upload service not found")

        image_path = "/tmp/hermes-test-image-upload-failure.png"
        Path(image_path).write_bytes(b"fake png")
        xmpp._client = cast(Any, FakeClient())

        result = await xmpp.send_image_file("thanos@example.org", image_path)

        self.assertFalse(result.success)
        self.assertFalse(result.retryable)
        self.assertIn("HTTP Upload service not found", result.error or "")

    async def test_adapter_sends_local_image_via_http_upload_with_oob_url(self):
        cfg = types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret"})
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.uploads = []
                self.messages = []
                self.states = []

            async def upload_file(self, file_path, content_type=None):
                self.uploads.append((file_path, content_type))
                return "https://upload.example.org/image.png"

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None, reply_to=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url, reply_to))
                return "msg-image"

            async def send_chat_state(
                self,
                to_jid,
                state,
                message_type="chat",
                *,
                thread_id=None,
            ):
                            self.states.append((state, thread_id))

                    image_path = _win_tmp_path(".png")
                    Path(image_path).write_bytes(b"fake png")
                    fake_client = FakeClient()
        xmpp._client = fake_client

        await xmpp.send_typing(
            "thanos@example.org",
            metadata={"thread_id": " media-thread "},
        )
        result = await xmpp.send_image_file(
            "thanos@example.org",
            image_path,
            caption="A tiny test",
            reply_to="reply-anchor",
            metadata={"thread_id": " media-thread "},
        )
        await xmpp.stop_typing("thanos@example.org")

        self.assertTrue(result.success)
        self.assertEqual(fake_client.uploads, [(image_path, "image/png")])
        self.assertEqual(fake_client.messages, [
            ("thanos@example.org", "A tiny test\nhttps://upload.example.org/image.png", "chat", " media-thread ", "https://upload.example.org/image.png", "reply-anchor")
        ])
        self.assertEqual(fake_client.states, [("composing", " media-thread ")])

    async def test_reply_anchor_applies_only_to_first_chunk_without_creating_thread(self):
        cfg = types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret", "text_chunk_limit": 6})
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeClient:
            def __init__(self):
                self.messages = []

            async def send_message(self, to_jid, text, message_type, *, thread_id=None, oob_url=None, reply_to=None):
                self.messages.append((to_jid, text, message_type, thread_id, oob_url, reply_to))
                return f"msg-{len(self.messages)}"

        fake_client = FakeClient()
        xmpp._client = cast(Any, fake_client)

        result = await xmpp.send("thanos@example.org", "hello there friend", reply_to="root")

        self.assertTrue(result.success)
        self.assertEqual(result.message_id, "msg-3")
        self.assertEqual(result.continuation_message_ids, ("msg-1", "msg-2"))
        self.assertEqual([call[1] for call in fake_client.messages], ["hello", "there", "friend"])
        self.assertEqual([call[3] for call in fake_client.messages], [None, None, None])
        self.assertEqual([call[5] for call in fake_client.messages], ["root", None, None])

    def test_declared_media_kinds_tracks_future_fail_closed_gateway_api(self):
        old_media_kind = adapter.MediaKind
        try:
            adapter.MediaKind = types.SimpleNamespace(
                IMAGE="image",
                VIDEO="video",
                VOICE="voice",
                DOCUMENT="document",
            )
            self.assertEqual(
                adapter._declared_media_kinds(),
                frozenset({"image", "video", "voice", "document"}),
            )
        finally:
            adapter.MediaKind = old_media_kind

    async def test_standalone_thread_uses_thread_metadata_not_reply_anchor(self):
        cfg = types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
        })
        sent = []

        class FakeAdapter:
            def __init__(self, pconfig):
                pass

            async def connect(self):
                return True

            async def send(self, chat_id, content, reply_to=None, metadata=None):
                sent.append((chat_id, content, reply_to, metadata))
                return adapter.SendResult(success=True, message_id="message-1")

            async def disconnect(self):
                return None

        old = adapter.XMPPAdapter
        try:
            adapter.XMPPAdapter = FakeAdapter
            result = await adapter._standalone_send(
                cfg,
                "thanos@example.org",
                "hello",
                thread_id=" standalone-thread ",
            )
        finally:
            adapter.XMPPAdapter = old

        self.assertEqual(result, {"success": True, "message_id": "message-1"})
        self.assertEqual(sent, [
            (
                "thanos@example.org",
                "hello",
                None,
                {"thread_id": " standalone-thread "},
            ),
        ])

    async def test_standalone_sender_routes_video_to_send_video(self):
        cfg = types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret"})

        class FakeAdapter:
            def __init__(self, pconfig):
                self.sent = []

            async def connect(self):
                return True

            async def send_video(self, chat_id, video_path, caption=None, reply_to=None, metadata=None):
                self.sent.append((chat_id, video_path, caption, reply_to))
                return adapter.SendResult(success=True, message_id="video-msg")

            async def disconnect(self):
                return None

        old = adapter.XMPPAdapter
        try:
            adapter.XMPPAdapter = FakeAdapter
            video_path = "/tmp/hermes-standalone-video.mp4"
            Path(video_path).write_bytes(b"fake mp4")
            result = await adapter._standalone_send(cfg, "thanos@example.org", "caption", media_files=[video_path])
        finally:
            adapter.XMPPAdapter = old

        self.assertEqual(result, {"success": True, "message_id": "video-msg"})

    async def test_standalone_sender_uploads_media_files(self):
        cfg = types.SimpleNamespace(extra={"jid": "emma@example.org", "server": "chat.example.org", "password": "secret"})

        class FakeAdapter:
            def __init__(self, pconfig):
                self.sent = []
                self.disconnected = False

            async def connect(self):
                return True

            async def send_image_file(self, chat_id, image_path, caption=None, reply_to=None, metadata=None):
                self.sent.append((chat_id, image_path, caption, reply_to))
                return adapter.SendResult(success=True, message_id="media-msg")

            async def disconnect(self):
                self.disconnected = True

        old = adapter.XMPPAdapter
        try:
            adapter.XMPPAdapter = FakeAdapter
            image_path = "/tmp/hermes-standalone-image.jpg"
            Path(image_path).write_bytes(b"fake jpg")
            result = await adapter._standalone_send(cfg, "thanos@example.org", "caption", media_files=[image_path])
        finally:
            adapter.XMPPAdapter = old

        self.assertEqual(result, {"success": True, "message_id": "media-msg"})


class ProcessingReactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_xmpp_env()

    def tearDown(self):
        clear_xmpp_env()

    def _xmpp(self, **extra):
        base = {
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "allowed_users": ["thanos@example.org"],
            "nickname": "Emma",
            "allowed_rooms": ["room@muc.example.org"],
            "group_allow_from": ["thanos@example.org"],
        }
        base.update(extra)
        return adapter.XMPPAdapter(types.SimpleNamespace(extra=base))

    def _event(self, xmpp, msg):
        parsed = adapter.parse_xmpp_message(msg, xmpp.settings)
        source = xmpp.build_source(
            chat_id=parsed.chat_id,
            chat_name=parsed.chat_name,
            chat_type=parsed.chat_type,
            user_id=parsed.user_id,
            user_name=parsed.user_name,
            message_id=parsed.message_id,
        )
        return adapter.MessageEvent(
            text=adapter.event_text_for(parsed, xmpp.settings),
            message_type=adapter.MessageType.TEXT,
            source=source,
            raw_message=msg,
            message_id=parsed.message_id,
        )

    async def test_configured_reaction_choices_are_selected_for_lifecycle_hooks(self):
        xmpp = self._xmpp(
            reaction_start_choices=["👀", "😘"],
            reaction_success_choices=["✅", "❤️"],
            reaction_failure_choices=["❌", "💔"],
        )

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_reactions(
                self,
                to_jid,
                message_id,
                reactions,
                message_type="chat",
                *,
                thread_id=None,
            ):
                self.calls.append((to_jid, message_id, tuple(reactions), message_type))
                return True

        fake_client = FakeClient()
        xmpp._client = fake_client
        msg = FakeMessage(body="hello", **{"from": "thanos@example.org/dino"}, type="chat", id="dm1")
        event = self._event(xmpp, msg)

        with patch.object(adapter.random, "choice", side_effect=lambda choices: choices[-1]):
            await xmpp.on_processing_start(event)
            await xmpp.on_processing_complete(event, adapter.ProcessingOutcome.SUCCESS)
            await xmpp.on_processing_complete(event, adapter.ProcessingOutcome.FAILURE)

        self.assertEqual(fake_client.calls, [
            ("thanos@example.org/dino", "dm1", ("😘",), "chat"),
            ("thanos@example.org/dino", "dm1", ("❤️",), "chat"),
            ("thanos@example.org/dino", "dm1", ("💔",), "chat"),
        ])

    async def test_authorized_event_can_send_arbitrary_reactions(self):
        xmpp = self._xmpp()

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_reactions(
                self,
                to_jid,
                message_id,
                reactions,
                message_type="chat",
                *,
                thread_id=None,
            ):
                self.calls.append(
                    (to_jid, message_id, tuple(reactions), message_type, thread_id)
                )
                return True

        fake_client = FakeClient()
        xmpp._client = fake_client
        msg = FakeMessage(
            body="hello",
            **{"from": "thanos@example.org/dino"},
            type="chat",
            id="dm-playful",
            thread=" reaction-thread ",
        )
        event = self._event(xmpp, msg)

        sent = await xmpp.react_to_event(event, ["❤️", "😂"])

        self.assertTrue(sent)
        self.assertEqual(fake_client.calls, [
            (
                "thanos@example.org/dino",
                "dm-playful",
                ("❤️", "😂"),
                "chat",
                " reaction-thread ",
            ),
        ])

    async def test_arbitrary_reaction_helper_keeps_auth_gate(self):
        xmpp = self._xmpp()

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_reactions(self, to_jid, message_id, reactions, message_type="chat", *, thread_id=None):
                self.calls.append((to_jid, message_id, tuple(reactions), message_type))
                return True

        fake_client = FakeClient()
        xmpp._client = fake_client
        msg = FakeMessage(body="hello", **{"from": "intruder@example.net/laptop"}, type="chat", id="dm-intruder")
        event = self._event(xmpp, msg)

        sent = await xmpp.react_to_event(event, ["❤️"])

        self.assertFalse(sent)
        self.assertEqual(fake_client.calls, [])

    async def test_authorized_dm_gets_processing_start_and_success_reactions(self):
        xmpp = self._xmpp()

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_reactions(self, to_jid, message_id, reactions, message_type="chat", *, thread_id=None):
                self.calls.append((to_jid, message_id, tuple(reactions), message_type))
                return True

        fake_client = FakeClient()
        xmpp._client = fake_client
        msg = FakeMessage(body="hello", **{"from": "thanos@example.org/dino"}, type="chat", id="dm1")
        event = self._event(xmpp, msg)

        await xmpp.on_processing_start(event)
        await xmpp.on_processing_complete(event, adapter.ProcessingOutcome.SUCCESS)

        self.assertEqual(fake_client.calls, [
            ("thanos@example.org/dino", "dm1", ("👀",), "chat"),
            ("thanos@example.org/dino", "dm1", ("✅",), "chat"),
        ])

    async def test_unauthorized_sender_gets_no_processing_reactions(self):
        xmpp = self._xmpp()

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_reactions(self, to_jid, message_id, reactions, message_type="chat", *, thread_id=None):
                self.calls.append((to_jid, message_id, tuple(reactions), message_type))
                return True

        fake_client = FakeClient()
        xmpp._client = fake_client
        msg = FakeMessage(body="hello", **{"from": "intruder@example.net/laptop"}, type="chat", id="dm2")
        event = self._event(xmpp, msg)

        await xmpp.on_processing_start(event)
        await xmpp.on_processing_complete(event, adapter.ProcessingOutcome.FAILURE)

        self.assertEqual(fake_client.calls, [])

    async def test_muc_reactions_follow_authorized_mention_policy(self):
        xmpp = self._xmpp(muc_require_mention=True)

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_reactions(self, to_jid, message_id, reactions, message_type="chat", *, thread_id=None):
                self.calls.append((to_jid, message_id, tuple(reactions), message_type, thread_id))
                return True

        fake_client = FakeClient()
        xmpp._client = fake_client
        unauthorized = FakeMessage(
            body="hello",
            **{"from": "room@muc.example.org/thanos"},
            type="groupchat",
            id="muc1",
            muc={"jid": "thanos@example.org"},
            mucnick="thanos",
        )
        authorized = FakeMessage(
            body="Emma: hello",
            **{"from": "room@muc.example.org/thanos"},
            type="groupchat",
            id="muc2",
            thread=" muc-thread ",
            muc={"jid": "thanos@example.org"},
            mucnick="thanos",
        )

        await xmpp.on_processing_start(self._event(xmpp, unauthorized))
        await xmpp.on_processing_start(self._event(xmpp, authorized))

        self.assertEqual(fake_client.calls, [
            ("room@muc.example.org", "muc2", ("👀",), "groupchat", " muc-thread "),
        ])

    async def test_failure_outcome_gets_cross_reaction(self):
        xmpp = self._xmpp()

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def send_reactions(self, to_jid, message_id, reactions, message_type="chat", *, thread_id=None):
                self.calls.append((to_jid, message_id, tuple(reactions), message_type))
                return True

        fake_client = FakeClient()
        xmpp._client = fake_client
        msg = FakeMessage(body="hello", **{"from": "thanos@example.org/dino"}, type="chat", id="dm3")
        event = self._event(xmpp, msg)

        await xmpp.on_processing_complete(event, adapter.ProcessingOutcome.FAILURE)

        self.assertEqual(fake_client.calls, [
            ("thanos@example.org/dino", "dm3", ("❌",), "chat"),
        ])

    async def test_missing_xep_0444_fallback_does_not_break_processing_hooks(self):
        xmpp = self._xmpp()

        class FakeClient:
            async def send_reactions(self, to_jid, message_id, reactions, message_type="chat", *, thread_id=None):
                return False

        xmpp._client = FakeClient()
        msg = FakeMessage(body="hello", **{"from": "thanos@example.org/dino"}, type="chat", id="dm4")
        event = self._event(xmpp, msg)

        await xmpp.on_processing_start(event)
        await xmpp.on_processing_complete(event, adapter.ProcessingOutcome.SUCCESS)


class ThreadStanzaTests(unittest.IsolatedAsyncioTestCase):
    """S1: thread_id must be written onto the XMPP stanza, not dropped."""

    async def test_send_message_sets_thread_when_thread_id_given(self):
        class FakeMessage:
            def __init__(self):
                self.values: dict[str, Any] = {}
                self.sent = False

            def __setitem__(self, key, value):
                self.values[key] = value

            def __getitem__(self, key):
                return self.values.setdefault(key, {})

            def send(self):
                self.sent = True

        class FakeClient:
            def __init__(self):
                self.messages = []

            def make_message(self, mto, mbody, mtype):
                msg = FakeMessage()
                msg.values.update({"to": mto, "body": mbody, "type": mtype})
                self.messages.append(msg)
                return msg

        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = FakeClient()
        thin.adapter = types.SimpleNamespace(settings=types.SimpleNamespace(send_chat_states=False))

        await thin.send_message(
            "room@muc.example.org",
            "hi",
            "groupchat",
            thread_id=" thread-123 ",
        )

        self.assertEqual(len(thin.client.messages), 1)
        self.assertEqual(thin.client.messages[0].values["type"], "groupchat")
        self.assertEqual(thin.client.messages[0].values["thread"], " thread-123 ")
        self.assertTrue(thin.client.messages[0].sent)

    async def test_send_message_omits_thread_when_thread_id_absent(self):
        class FakeMessage:
            def __init__(self):
                self.values: dict[str, Any] = {}
                self.sent = False

            def __setitem__(self, key, value):
                self.values[key] = value

            def __getitem__(self, key):
                return self.values.setdefault(key, {})

            def send(self):
                self.sent = True

        class FakeClient:
            def __init__(self):
                self.messages = []

            def make_message(self, mto, mbody, mtype):
                msg = FakeMessage()
                msg.values.update({"to": mto, "body": mbody, "type": mtype})
                self.messages.append(msg)
                return msg

        thin = cast(Any, object.__new__(adapter._SlixmppClient))
        thin.client = FakeClient()
        thin.adapter = types.SimpleNamespace(settings=types.SimpleNamespace(send_chat_states=False))

        await thin.send_message("thanos@example.org", "hi", "chat")

        self.assertEqual(len(thin.client.messages), 1)
        self.assertNotIn("thread", thin.client.messages[0].values)


class JoinMucRoomTests(unittest.IsolatedAsyncioTestCase):
    """S3: prefer join_muc_wait, fall back to join_muc."""

    async def test_prefers_join_muc_wait_when_available(self):
        class FakeMuc:
            def __init__(self):
                self.wait_called = False
                self.join_called = False

            async def join_muc_wait(self, room, nick):
                self.wait_called = True
                self.wait_args = (room, nick)

            def join_muc(self, room, nick):
                self.join_called = True

        muc = FakeMuc()
        await adapter._join_muc_room(muc, "room@conference.example.org", "emma")
        self.assertTrue(muc.wait_called)
        self.assertFalse(muc.join_called)
        self.assertEqual(muc.wait_args, ("room@conference.example.org", "emma"))

    async def test_falls_back_to_join_muc_when_wait_missing(self):
        class FakeMuc:
            def __init__(self):
                self.join_called = False

            def join_muc(self, room, nick):
                self.join_called = True
                self.join_args = (room, nick)

        muc = FakeMuc()
        await adapter._join_muc_room(muc, "room@conference.example.org", "emma")
        self.assertTrue(muc.join_called)
        self.assertEqual(muc.join_args, ("room@conference.example.org", "emma"))

    async def test_falls_back_to_join_muc_when_wait_raises(self):
        class FakeMuc:
            def __init__(self):
                self.join_called = False

            async def join_muc_wait(self, room, nick):
                raise RuntimeError("server rejected join")

            def join_muc(self, room, nick):
                self.join_called = True

        muc = FakeMuc()
        await adapter._join_muc_room(muc, "room@conference.example.org", "emma")
        self.assertTrue(muc.join_called)


class ScopedIdentityLockTests(unittest.IsolatedAsyncioTestCase):
    """S4: XMPP identity lock prevents two profiles on the same JID:resource."""

    def _cfg(self):
        return types.SimpleNamespace(extra={
            "jid": "emma@example.org",
            "server": "chat.example.org",
            "password": "secret",
            "resource": "hermes",
        })

    @staticmethod
    def _install_recovery_hooks(xmpp):
        fatal_errors = []
        notifications = []

        def set_fatal_error(code, message, retryable=False):
            fatal_errors.append((code, message, retryable))

        async def notify_fatal_error():
            notifications.append("notified")

        xmpp._set_fatal_error = set_fatal_error
        xmpp._notify_fatal_error = notify_fatal_error
        return fatal_errors, notifications

    async def test_connect_returns_false_on_lock_conflict(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)

        with patch.object(adapter, "check_requirements", return_value=True), \
             patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(False, "emma@example.org:hermes")):
            ok = await xmpp.connect()

        self.assertFalse(ok)
        self.assertEqual(xmpp.fatal_error_message, "XMPP identity in use by another profile")
        self.assertIsNone(xmpp._client)
        self.assertIsNone(xmpp._lock_key)

    async def test_connect_acquires_lock_then_proceeds(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        mark_calls = []

        class FakeThinClient:
            def __init__(self, _adapter):
                pass

            async def connect(self):
                return True

        def mark_connected():
            mark_calls.append("connected")

        xmpp._mark_connected = mark_connected

        with patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(True, "emma@example.org:hermes")), \
             patch.object(adapter, "_SlixmppClient", FakeThinClient), \
             patch.object(adapter, "check_requirements", return_value=True), \
             patch.object(adapter, "_release_xmpp_identity_lock") as release:
            ok = await xmpp.connect()

        self.assertTrue(ok)
        self.assertIsInstance(xmpp._client, FakeThinClient)
        self.assertEqual(xmpp._lock_key, "emma@example.org:hermes")
        self.assertEqual(mark_calls, ["connected"])
        release.assert_not_called()

    async def test_connect_false_return_drops_client_and_releases_lock(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        mark_calls = []
        built = []

        class FalseThinClient:
            def __init__(self, _adapter):
                self.disconnect_calls = 0
                built.append(self)

            async def connect(self):
                return False

            async def disconnect(self):
                self.disconnect_calls += 1

        def mark_connected():
            mark_calls.append("connected")

        xmpp._mark_connected = mark_connected

        with patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(True, "emma@example.org:hermes")), \
             patch.object(adapter, "_SlixmppClient", FalseThinClient), \
             patch.object(adapter, "check_requirements", return_value=True), \
             patch.object(adapter, "_release_xmpp_identity_lock") as release:
            ok = await xmpp.connect()

        self.assertFalse(ok)
        self.assertEqual(len(built), 1)
        self.assertIsNone(xmpp._client)
        self.assertIsNone(xmpp._lock_key)
        self.assertEqual(mark_calls, [])
        self.assertEqual(built[0].disconnect_calls, 1)
        release.assert_called_once_with("emma@example.org:hermes")

    async def test_connect_constructor_failure_aborts_partial_client_and_releases_lock(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        built = []

        class FakeClientXMPP:
            def __init__(self, jid, password):
                self.boundjid = types.SimpleNamespace(resource="")
                self.requested_jid = types.SimpleNamespace(resource="")
                self.plugin = {}
                self.abort_calls = 0
                built.append(self)

            def register_handler(self, handler):
                pass

            def register_plugin(self, plugin, **kwargs):
                self.plugin[plugin] = object()

            def add_event_handler(self, *_args, **_kwargs):
                raise RuntimeError("handler registration failed")

            def abort(self):
                self.abort_calls += 1

        with patch.dict(sys.modules, {"slixmpp": types.SimpleNamespace(ClientXMPP=FakeClientXMPP)}), \
             patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(True, "emma@example.org:hermes")), \
             patch.object(adapter, "check_requirements", return_value=True), \
             patch.object(adapter, "_release_xmpp_identity_lock") as release:
            ok = await xmpp.connect()

        self.assertFalse(ok)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0].abort_calls, 1)
        self.assertIsNone(xmpp._client)
        self.assertIsNone(xmpp._lock_key)
        release.assert_called_once_with("emma@example.org:hermes")

    async def test_connect_cancellation_boundedly_tears_down_and_releases_lock(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        connect_started = asyncio.Event()
        disconnect_started = asyncio.Event()
        disconnect_cancelled = asyncio.Event()
        abort_calls = []

        class HangingThinClient:
            async def connect(self):
                connect_started.set()
                await asyncio.Event().wait()
                return True

            async def disconnect(self):
                disconnect_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    disconnect_cancelled.set()

            def abort(self):
                abort_calls.append("abort")

        with patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(True, "emma@example.org:hermes")), \
             patch.object(adapter, "_SlixmppClient", return_value=HangingThinClient()), \
             patch.object(adapter, "check_requirements", return_value=True), \
             patch.object(adapter, "_FAILED_CONNECT_TEARDOWN_TIMEOUT", 0.01, create=True), \
             patch.object(adapter, "_release_xmpp_identity_lock") as release:
            connect_task = asyncio.create_task(xmpp.connect())
            await asyncio.wait_for(connect_started.wait(), 1)
            connect_task.cancel()
            await asyncio.wait_for(disconnect_started.wait(), 1)
            connect_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(connect_task, 1)

        self.assertTrue(disconnect_started.is_set())
        self.assertTrue(disconnect_cancelled.is_set())
        self.assertEqual(abort_calls, ["abort"])
        self.assertIsNone(xmpp._client)
        self.assertIsNone(xmpp._lock_key)
        release.assert_called_once_with("emma@example.org:hermes")

    async def test_stale_connect_cleanup_does_not_release_replacement_ownership(self):
        xmpp = adapter.XMPPAdapter(self._cfg())

        class OldClient:
            def __init__(self):
                self.disconnect_calls = 0

            async def disconnect(self):
                self.disconnect_calls += 1

        old_client = OldClient()
        replacement_client = object()
        xmpp._client = cast(Any, replacement_client)
        xmpp._lock_key = "emma@example.org:hermes"

        with patch.object(adapter, "_release_xmpp_identity_lock") as release:
            await xmpp._cleanup_connect_attempt(old_client, "emma@example.org:hermes")

        self.assertIs(xmpp._client, replacement_client)
        self.assertEqual(xmpp._lock_key, "emma@example.org:hermes")
        self.assertEqual(old_client.disconnect_calls, 1)
        release.assert_not_called()

    async def test_connect_accepts_gateway_reconnect_keyword(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)

        class FakeThinClient:
            def __init__(self, _adapter):
                pass

            async def connect(self):
                return True

        with patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(True, "emma@example.org:hermes")), \
             patch.object(adapter, "_SlixmppClient", FakeThinClient), \
             patch.object(adapter, "check_requirements", return_value=True):
            ok = await xmpp.connect(is_reconnect=True)

        self.assertTrue(ok)
        self.assertEqual(xmpp._lock_key, "emma@example.org:hermes")

    async def test_disconnect_releases_lock(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        xmpp._lock_key = "emma@example.org:hermes"
        xmpp._chat_states[("thanos@example.org", "chat", "thread-1")] = "active"
        xmpp._sent_text_by_message_id["message-1"] = "hello"
        xmpp._status_message_ids[("thanos@example.org", None, "status")] = "message-1"
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/emacs"

        with patch.object(adapter, "_release_xmpp_identity_lock") as release:
            await xmpp.disconnect()

        release.assert_called_once_with("emma@example.org:hermes")
        self.assertIsNone(xmpp._lock_key)
        self.assertEqual(xmpp._chat_states, {})
        self.assertEqual(xmpp._sent_text_by_message_id, {})
        self.assertEqual(xmpp._status_message_ids, {})
        self.assertEqual(xmpp._last_full_jid_by_chat, {})

    async def test_unexpected_disconnect_sets_retryable_fatal_error_notifies_once_and_releases_once(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        client = object()
        xmpp._client = cast(Any, client)
        xmpp._lock_key = "emma@example.org:hermes"
        xmpp._chat_states[("thanos@example.org", "chat", "thread-1")] = "active"
        xmpp._sent_text_by_message_id["message-1"] = "hello"
        xmpp._status_message_ids[("thanos@example.org", None, "status")] = "message-1"
        xmpp._last_full_jid_by_chat["thanos@example.org"] = "thanos@example.org/emacs"
        fatal_errors, notifications = self._install_recovery_hooks(xmpp)

        with patch.object(adapter, "_release_xmpp_identity_lock") as release:
            await xmpp.on_xmpp_disconnected(ConnectionError("socket lost"), client=client)
            await xmpp.on_xmpp_disconnected(ConnectionError("duplicate event"), client=client)

        self.assertEqual(len(fatal_errors), 1)
        self.assertEqual(fatal_errors[0][0], "connection_lost")
        self.assertTrue(fatal_errors[0][2])
        self.assertEqual(notifications, ["notified"])
        release.assert_called_once_with("emma@example.org:hermes")
        self.assertIsNone(xmpp._client)
        self.assertIsNone(xmpp._lock_key)
        self.assertEqual(xmpp._chat_states, {})
        self.assertEqual(xmpp._sent_text_by_message_id, {})
        self.assertEqual(xmpp._status_message_ids, {})
        self.assertEqual(xmpp._last_full_jid_by_chat, {})

    async def test_fallback_base_notify_fatal_error_invokes_handler_without_monkeypatch(self):
        """Unit-test BasePlatformAdapter stub must expose Hermes' notify hook."""
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        client = object()
        xmpp._client = cast(Any, client)
        xmpp._lock_key = "emma@example.org:hermes"
        notifications = []

        def set_fatal_error(code, message, retryable=False):
            pass

        async def fatal_handler(adapter_self):
            notifications.append(adapter_self)

        xmpp._set_fatal_error = set_fatal_error
        xmpp._fatal_error_handler = fatal_handler
        # Intentionally do not monkeypatch _notify_fatal_error.

        with patch.object(adapter, "_release_xmpp_identity_lock"):
            await xmpp.on_xmpp_disconnected(ConnectionError("socket lost"), client=client)

        self.assertEqual(notifications, [xmpp])

    async def test_explicit_disconnect_does_not_notify_reconnect_handler(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        fatal_errors, notifications = self._install_recovery_hooks(xmpp)

        class Client:
            async def disconnect(self):
                await xmpp.on_xmpp_disconnected("operator disconnect", client=self)

        client = Client()
        xmpp._client = cast(Any, client)
        xmpp._lock_key = "emma@example.org:hermes"

        with patch.object(adapter, "_release_xmpp_identity_lock") as release:
            await xmpp.disconnect()

        self.assertEqual(fatal_errors, [])
        self.assertEqual(notifications, [])
        release.assert_called_once_with("emma@example.org:hermes")
        self.assertIsNone(xmpp._client)
        self.assertIsNone(xmpp._lock_key)

    async def test_stale_disconnect_event_does_not_disconnect_replacement_client(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        old_client = object()
        replacement_client = object()
        xmpp._client = cast(Any, replacement_client)
        xmpp._lock_key = "emma@example.org:hermes"
        fatal_errors, notifications = self._install_recovery_hooks(xmpp)

        with patch.object(adapter, "_release_xmpp_identity_lock") as release:
            await xmpp.on_xmpp_disconnected("old client event", client=old_client)

        self.assertIs(xmpp._client, replacement_client)
        self.assertEqual(xmpp._lock_key, "emma@example.org:hermes")
        self.assertEqual(fatal_errors, [])
        self.assertEqual(notifications, [])
        release.assert_not_called()

    async def test_send_connection_exception_notifies_recovery_handler(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        xmpp._lock_key = "emma@example.org:hermes"
        fatal_errors, notifications = self._install_recovery_hooks(xmpp)

        class FailingClient:
            def __init__(self):
                self.send_calls = 0

            def is_connected(self):
                return True

            async def send_message(self, *args, **kwargs):
                self.send_calls += 1
                raise ConnectionError("socket closed")

        failing_client = FailingClient()
        xmpp._client = cast(Any, failing_client)

        with patch.object(adapter, "_release_xmpp_identity_lock") as release:
            result = await xmpp.send("thanos@example.org", "hello")

        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertEqual(failing_client.send_calls, 1)
        self.assertEqual(fatal_errors[0][0], "connection_lost")
        self.assertTrue(fatal_errors[0][2])
        self.assertEqual(notifications, ["notified"])
        release.assert_called_once_with("emma@example.org:hermes")
        self.assertIsNone(xmpp._client)
        self.assertIsNone(xmpp._lock_key)

    async def test_connect_failure_releases_lock(self):
        cfg = self._cfg()
        xmpp = adapter.XMPPAdapter(cfg)
        mark_calls = []

        class FailingThinClient:
            def __init__(self, _adapter):
                pass

            async def connect(self):
                raise RuntimeError("connection refused")

        def mark_connected():
            mark_calls.append("connected")

        xmpp._mark_connected = mark_connected

        with patch.object(adapter, "_acquire_xmpp_identity_lock", return_value=(True, "emma@example.org:hermes")), \
             patch.object(adapter, "_SlixmppClient", FailingThinClient), \
             patch.object(adapter, "check_requirements", return_value=True), \
             patch.object(adapter, "_release_xmpp_identity_lock") as release:
            ok = await xmpp.connect()

        self.assertFalse(ok)
        self.assertIsNone(xmpp._client)
        # Lock must be released so a retry is not blocked by a stale lock.
        self.assertIsNone(xmpp._lock_key)
        self.assertEqual(mark_calls, [])
        release.assert_called_once_with("emma@example.org:hermes")
        self.assertEqual(xmpp.fatal_error_message, "connection refused")

    def test_acquire_lock_fails_open_without_status_module(self):
        real_import = __import__

        def import_without_status(name, *args, **kwargs):
            if name == "gateway.status":
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_status):
            acquired, key = adapter._acquire_xmpp_identity_lock("emma@example.org", "hermes")
        self.assertTrue(acquired)
        self.assertIsNone(key)

    def test_lock_key_uses_bare_jid_and_resource(self):
        self.assertEqual(
            adapter._xmpp_identity_lock_key("Emma@Example.ORG/laptop", "hermes"),
            "emma@example.org:hermes",
        )


class PasswordCommandDiagnosticsTests(unittest.TestCase):
    """N3: password-command failures must surface stderr, not swallow it."""

    def test_surfaces_stderr_on_nonzero_exit(self):
        completed = __import__("subprocess").CompletedProcess(
            args=["gpg"], returncode=2, stdout="", stderr="gpg: agent locked"
        )
        with patch("subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                adapter._read_secret_command("gpg --decrypt pw")
        self.assertIn("exited 2", str(ctx.exception))
        self.assertIn("gpg: agent locked", str(ctx.exception))

    def test_returns_stdout_on_success(self):
        completed = __import__("subprocess").CompletedProcess(
            args=["pass"], returncode=0, stdout="s3cr3t\n", stderr=""
        )
        with patch("subprocess.run", return_value=completed):
            self.assertEqual(adapter._read_secret_command("pass show xmpp"), "s3cr3t")

    def test_empty_command_returns_empty(self):
        self.assertEqual(adapter._read_secret_command(""), "")


if __name__ == "__main__":
    unittest.main()
