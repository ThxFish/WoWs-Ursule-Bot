import pytest

from ursule_bot.interfaces.qq.commands import build_kokomi_message, execute_command, parse_command


def test_command_format_is_strict():
    assert parse_command("/节日船团 进度") is None
    assert parse_command("  /节日船团 帮助  ") is None
    assert parse_command("<@!12345> /节日船团 资源") is None
    assert parse_command("普通聊天") is None
    assert parse_command("请执行 /节日船团 同步") is None
    assert parse_command("/节日船团 进度 多余参数") is None
    assert parse_command("x" * 257) is None
    assert parse_command("/战绩") is None
    assert parse_command("/stat") is None
    assert parse_command("/资讯") is None
    assert parse_command("/新闻") == "资讯"
    assert parse_command("/news") == "资讯"
    assert parse_command("帮助") == "帮助"
    assert parse_command("activity 活动") is None
    assert parse_command("请帮我看活动") is None


def test_updated_short_commands_and_arguments():
    assert parse_command("/帮助") == "帮助"
    assert parse_command("/help") == "帮助"
    assert parse_command("/活动") == "活动"
    assert parse_command("/event") == "活动"
    assert parse_command("/我") == "战绩"
    assert parse_command("/me") == "战绩"
    assert parse_command("/近期 7") == "近期 7"
    assert parse_command("/recent 7") == "近期 7"
    assert parse_command("/日报") == "日报"
    assert parse_command("/daily") == "日报"
    assert parse_command("/绑定 eu PlayerName") == "绑定 eu PlayerName"
    assert parse_command("/bind eu PlayerName") == "绑定 eu PlayerName"
    assert parse_command("/wws bind eu PlayerName") == "绑定 eu PlayerName"
    assert parse_command("/wws set eu PlayerName") == "绑定 eu PlayerName"
    assert parse_command("/wws 绑定 eu PlayerName") == "绑定 eu PlayerName"
    assert parse_command("/random 7") == "随机 7"
    assert parse_command("/排位 14") == "排位 14"
    assert parse_command("/ship  Des Moines ") == "单船 Des Moines"
    assert parse_command("/类别   美国 10 巡洋舰") == "类别 美国 10 巡洋舰"
    assert parse_command("/random") == "随机"
    assert parse_command("/unknown") is None
    assert parse_command("日报") == "日报"
    assert parse_command("daily") == "日报"
    assert parse_command("近期 7") == "近期 7"
    assert parse_command("bind eu PlayerName") == "绑定 eu PlayerName"
    assert parse_command("wws set eu PlayerName") == "绑定 eu PlayerName"


def test_short_commands_build_original_wws_arguments():
    assert build_kokomi_message("绑定 eu PlayerName", "500000001") == "bind eu PlayerName"
    assert build_kokomi_message("近期 7", "500000001") == "me recent 7"
    assert build_kokomi_message("随机 7", "500000001") == "me pvp recent 7"
    assert build_kokomi_message("排位 14", "500000001") == "me rank recent 14"
    assert build_kokomi_message("单船 Des Moines", "500000001") == "me ship Des Moines"
    assert build_kokomi_message("类别 美国 10 巡洋舰", "500000001") == "me ships 美国 10 巡洋舰"


@pytest.mark.asyncio
async def test_parameterized_command_reports_usage_before_external_call():
    response = await execute_command("随机")
    assert "用法：/随机 参数" in response.text

    response = await execute_command("近期")
    assert "用法：/近期 参数" in response.text


@pytest.mark.asyncio
async def test_daily_command_returns_built_reply(monkeypatch):
    from ursule_bot.interfaces.qq import commands

    async def fake_daily_reply():
        return commands.BotReply("日报", image=b"png", image_alt="日报图片")

    monkeypatch.setattr(commands, "_daily_reply", fake_daily_reply)
    response = await execute_command("日报")
    assert response.image == b"png"
