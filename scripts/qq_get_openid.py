import os

import botpy
from botpy.message import C2CMessage, GroupMessage


class OpenIdClient(botpy.Client):
    async def on_ready(self):
        print(f"机器人已连接：{self.robot.name}")
        print("现在请给机器人发送私聊消息，或者在目标群里 @机器人。")

    async def on_c2c_message_create(self, message: C2CMessage):
        print("\n收到单聊消息")
        print("user_openid =", message.author.user_openid)
        print("请复制上面的 user_openid。")

    async def on_group_at_message_create(self, message: GroupMessage):
        print("\n收到群聊消息")
        print("group_openid =", message.group_openid)
        print("user_openid  =", message.author.user_openid)
        print("请复制上面的 group_openid。")


intents = botpy.Intents(public_messages=True)
client = OpenIdClient(intents=intents)

client.run(
    appid=os.environ["QQ_BOT_APP_ID"],
    secret=os.environ["QQ_BOT_APP_SECRET"],
)