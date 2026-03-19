import asyncio
import json
from contextlib import suppress

import redis.asyncio as redis_async
from django.conf import settings
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


class DeviceMonitorConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device_id = int(self.scope["url_route"]["kwargs"]["device_id"])
        self.channel_name_key = f"device_monitor:{self.device_id}"
        self.redis = redis_async.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        self.reader_task = None
        await self.pubsub.subscribe(self.channel_name_key)
        await self.accept()
        self.reader_task = asyncio.create_task(self._forward_pubsub_messages())

    async def disconnect(self, close_code):
        if self.reader_task is not None:
            self.reader_task.cancel()
            with suppress(Exception):
                await self.reader_task
        if getattr(self, "pubsub", None) is not None:
            with suppress(Exception):
                await self.pubsub.unsubscribe(self.channel_name_key)
            with suppress(Exception):
                await self.pubsub.aclose()
        if getattr(self, "redis", None) is not None:
            with suppress(Exception):
                await self.redis.aclose()

    async def _forward_pubsub_messages(self):
        while True:
            message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message:
                continue
            if message.get("type") != "message":
                continue

            payload = message.get("data")
            if not payload:
                continue

            await self.send(text_data=payload)
