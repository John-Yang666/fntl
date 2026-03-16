import json
from channels.generic.websocket import AsyncWebsocketConsumer

class TopologyConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("topology_updates", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("topology_updates", self.channel_name)

    async def topology_update(self, event):
        # 后端推送数据
        await self.send(text_data=json.dumps(event["data"]))
