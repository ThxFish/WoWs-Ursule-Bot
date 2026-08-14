import pytest

from ursule_bot.interfaces.qq.commands import execute_command, parse_command


def test_command_format_is_strict():
    assert parse_command("/节日船团 进度") == "进度"
    assert parse_command("  /节日船团 帮助  ") == "帮助"
    assert parse_command("<@!12345> /节日船团 资源") == "资源"
    assert parse_command("普通聊天") is None
    assert parse_command("请执行 /节日船团 同步") is None
    assert parse_command("/节日船团 进度 多余参数") == "未知"
    assert parse_command("x" * 257) is None


@pytest.mark.asyncio
async def test_group_cannot_trigger_sync():
    response = await execute_command("同步", allow_sync=False)
    assert "群聊不允许" in response.text
