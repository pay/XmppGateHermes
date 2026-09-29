import asyncio
import os
import types
import unittest

from hermes_xmpp import adapter


def clear_xmpp_env():
    for key in list(os.environ):
        if key.startswith("XMPP_"):
            os.environ.pop(key, None)


class FakeContext:
    def __init__(self):
        self.calls = []

    def register_platform(self, **kwargs):
        self.calls.append(kwargs)


class PluginRegistrationTests(unittest.TestCase):
    def setUp(self):
        clear_xmpp_env()

    def tearDown(self):
        clear_xmpp_env()

    def test_register_exposes_hermes_platform_hooks(self):
        ctx = FakeContext()
        adapter.register(ctx)
        self.assertEqual(len(ctx.calls), 1)
        entry = ctx.calls[0]
        self.assertEqual(entry["name"], "xmpp")
        self.assertEqual(entry["label"], "XMPP")
        self.assertEqual(entry["cron_deliver_env_var"], "XMPP_HOME_CHAT")
        self.assertEqual(entry["allowed_users_env"], "XMPP_ALLOWED_USERS")
        self.assertEqual(entry["allow_all_env"], "XMPP_ALLOW_ALL_USERS")
        self.assertTrue(callable(entry["adapter_factory"]))
        self.assertTrue(callable(entry["standalone_sender_fn"]))
        self.assertIn("XMPP", entry["platform_hint"])
        self.assertEqual(entry["max_message_length"], adapter.DEFAULT_TEXT_CHUNK_LIMIT)
        self.assertTrue(entry["adapter_factory"](types.SimpleNamespace(extra={})).splits_long_messages)

    def test_validate_config_accepts_password_file_or_command_resolution(self):
        cfg = types.SimpleNamespace(extra={"jid": "bot@example.org", "server": "chat.example.org", "password": "secret"})
        self.assertTrue(adapter.validate_config(cfg))
        missing = types.SimpleNamespace(extra={"jid": "bot@example.org", "server": "chat.example.org"})
        self.assertFalse(adapter.validate_config(missing))

    def test_env_enablement_accepts_compatibility_aliases(self):
        os.environ["XMPP_JID"] = "bot@example.org"
        os.environ["XMPP_HOST"] = "chat.example.org"
        os.environ["XMPP_PASSWORD"] = "secret"
        os.environ["XMPP_MUC_ROOMS"] = "room@muc.example.org"
        os.environ["XMPP_HOME_CHANNEL"] = "home@example.org"
        os.environ["XMPP_REACTION_START_CHOICES"] = "👀,😘"
        os.environ["XMPP_ANONYMOUS_MUC_POLICY"] = "deny"
        os.environ["XMPP_TOOL_PROGRESS_BUBBLE_LIMIT"] = "17"
        os.environ["XMPP_EDITABLE_PROGRESS"] = "disabled"

        enabled = adapter._env_enablement()

        if enabled is None:
            self.fail("expected XMPP aliases to enable platform config")
        self.assertNotIn("extra", enabled)
        self.assertEqual(enabled["jid"], "bot@example.org")
        self.assertEqual(enabled["server"], "chat.example.org")
        self.assertEqual(enabled["rooms"], ["room@muc.example.org"])
        self.assertEqual(enabled["home_chat"], "home@example.org")
        self.assertEqual(enabled["reaction_start_choices"], ["👀", "😘"])
        self.assertEqual(enabled["anonymous_muc_policy"], "deny")
        self.assertEqual(enabled["tool_progress_bubble_limit"], 17)
        self.assertEqual(enabled["editable_progress_policy"], "disabled")
        self.assertEqual(enabled["home_channel"]["chat_id"], "home@example.org")

        seed = dict(enabled)
        seed.pop("home_channel")
        platform_extra = {}
        platform_extra.update(seed)
        self.assertEqual(platform_extra["jid"], "bot@example.org")
        self.assertEqual(platform_extra["rooms"], ["room@muc.example.org"])
        self.assertEqual(platform_extra["anonymous_muc_policy"], "deny")
        self.assertEqual(platform_extra["tool_progress_bubble_limit"], 17)
        self.assertEqual(platform_extra["editable_progress_policy"], "disabled")

    def test_yaml_allowed_users_survive_env_enablement_with_env_precedence(self):
        for yaml_users in (["friend@example.org", "other@example.org"],
                           "friend@example.org,other@example.org"):
            for env_users in (None, "", "operator@example.org"):
                with self.subTest(yaml_users=yaml_users, env_users=env_users):
                    clear_xmpp_env()
                    if env_users is not None:
                        os.environ["XMPP_ALLOWED_USERS"] = env_users
                    extra = adapter._apply_yaml_config({}, {"extra": {
                        "jid": "bot@example.org",
                        "server": "chat.example.org",
                        "allowed_users": yaml_users,
                    }})
                    seed = adapter._env_enablement()
                    if seed is None or extra is None:
                        self.fail("expected YAML bridge and env enablement")
                    seed.pop("home_channel")
                    extra.update(seed)
                    settings = adapter.XmppSettings.from_config(
                        types.SimpleNamespace(extra=extra)
                    )
                    expected = ({"operator@example.org"} if env_users else
                                {"friend@example.org", "other@example.org"})
                    self.assertEqual(settings.allowed_users, expected)
                    self.assertEqual(set(seed["allowed_users"]), expected)
                    self.assertEqual(
                        os.environ["XMPP_ALLOWED_USERS"],
                        env_users or "friend@example.org,other@example.org",
                    )
                    for sender in expected:
                        self.assertTrue(adapter._authorized_direct_message(settings, sender))
                    self.assertFalse(adapter._authorized_direct_message(
                        settings, "stranger@example.org"
                    ))
                    if env_users:
                        self.assertFalse(adapter._authorized_direct_message(
                            settings, "friend@example.org"
                        ))

    def test_env_enablement_omits_allowed_rooms_when_unset_so_rooms_fallback_survives_merge(self):
        """Unset XMPP_ALLOWED_ROOMS must not seed empty list that blocks rooms fallback."""
        os.environ["XMPP_JID"] = "bot@example.org"
        os.environ["XMPP_SERVER"] = "chat.example.org"
        os.environ["XMPP_PASSWORD"] = "secret"
        os.environ["XMPP_ROOMS"] = "room@muc.example.org"
        os.environ["XMPP_GROUP_POLICY"] = "allowlist"
        os.environ["XMPP_GROUP_ALLOW_FROM"] = "*@example.org"
        os.environ["XMPP_NICKNAME"] = "Bot"

        enabled = adapter._env_enablement()
        if enabled is None:
            self.fail("expected env enablement")
        self.assertNotIn("allowed_rooms", enabled)

        seed = dict(enabled)
        seed.pop("home_channel")
        platform_extra = {}
        platform_extra.update(seed)
        settings = adapter.XmppSettings.from_config(types.SimpleNamespace(extra=platform_extra))
        self.assertEqual(settings.allowed_rooms, {"room@muc.example.org"})
        self.assertTrue(
            adapter._authorized_group_message(
                settings,
                "friend@example.org",
                "Bot: hi",
                room_jid="room@muc.example.org",
                sender_authenticated=True,
            )
        )

        os.environ["XMPP_ALLOWED_ROOMS"] = ""
        enabled_empty = adapter._env_enablement()
        if enabled_empty is None:
            self.fail("expected env enablement with empty allowed rooms")
        self.assertIn("allowed_rooms", enabled_empty)
        self.assertEqual(enabled_empty["allowed_rooms"], [])
        seed_empty = dict(enabled_empty)
        seed_empty.pop("home_channel")
        settings_empty = adapter.XmppSettings.from_config(
            types.SimpleNamespace(extra=dict(seed_empty))
        )
        self.assertEqual(settings_empty.allowed_rooms, set())
        self.assertFalse(
            adapter._authorized_group_message(
                settings_empty,
                "friend@example.org",
                "Bot: hi",
                room_jid="room@muc.example.org",
                sender_authenticated=True,
            )
        )

    def test_standalone_sender_reports_unconfigured_without_crashing(self):
        cfg = types.SimpleNamespace(extra={})
        result = asyncio.run(adapter._standalone_send(cfg, "user@example.org", "hello"))
        self.assertIn("error", result)
        self.assertIn("required", result["error"])


if __name__ == "__main__":
    unittest.main()
