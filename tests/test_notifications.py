import pytest

from tracker.notifications import QQ_API_BASE, qq_targets, render_message_template


def test_qq_uses_current_official_api_domain():
    assert QQ_API_BASE == "https://api.bot.qq.com"


def test_both_qq_targets_are_generated():
    assert qq_targets("user-id", "group-id", "both") == [
        ("好友", "/v2/users/user-id/messages"),
        ("群", "/v2/groups/group-id/messages"),
    ]
    assert qq_targets("user-id", "group-id", "user") == [("好友", "/v2/users/user-id/messages")]
    assert qq_targets("user-id", "group-id", "group") == [("群", "/v2/groups/group-id/messages")]


def test_editable_message_template():
    assert render_message_template("标题：{subject}\n{report}\n记得上线", "日报", "代币：1200") == "标题：日报\n代币：1200\n记得上线"
    assert render_message_template("{{测试}} {report}", "日报", "内容") == "{测试} 内容"


def test_unknown_message_placeholder_is_rejected():
    with pytest.raises(RuntimeError, match="仅支持"):
        render_message_template("{unknown}", "日报", "内容")
