import asyncio
import json
from contextlib import suppress

import redis.asyncio as redis_async
from django.conf import settings
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from myapp.jwt_auth_middleware import AUTH_WEBSOCKET_PROTOCOL
from myapp.models import Device


def _accepted_subprotocol(scope) -> str | None:
    return AUTH_WEBSOCKET_PROTOCOL if AUTH_WEBSOCKET_PROTOCOL in scope.get("subprotocols", []) else None


@database_sync_to_async
def _load_allowed_device_ids(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return None
    if hasattr(user, "managed_depots_qs"):
        depots_qs = user.managed_depots_qs()
        if depots_qs.exists():
            return set(Device.objects.filter(depot__in=depots_qs).values_list("device_id", flat=True))
    return set()


@database_sync_to_async
def _user_can_access_device(user, device_id: int) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if hasattr(user, "managed_depots_qs"):
        depots_qs = user.managed_depots_qs()
        if depots_qs.exists():
            return Device.objects.filter(device_id=device_id, depot__in=depots_qs).exists()
    return False

class TopologyConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return
        self.allowed_device_ids = await _load_allowed_device_ids(user)
        await self.channel_layer.group_add("topology_updates", self.channel_name)
        await self.accept(subprotocol=_accepted_subprotocol(self.scope))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("topology_updates", self.channel_name)

    async def topology_update(self, event):
        if self.allowed_device_ids is not None:
            device_id = event["data"].get("device_id")
            if device_id not in self.allowed_device_ids:
                return
        await self.send(text_data=json.dumps(event["data"]))


class DeviceMonitorConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device_id = int(self.scope["url_route"]["kwargs"]["device_id"])
        user = self.scope.get("user")
        if not await _user_can_access_device(user, self.device_id):
            await self.close(code=4403)
            return
        self.channel_name_key = f"device_monitor:{self.device_id}"
        self.redis = redis_async.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        self.reader_task = None
        await self.pubsub.subscribe(self.channel_name_key)
        await self.accept(subprotocol=_accepted_subprotocol(self.scope))
        self.reader_task = asyncio.create_task(self._forward_pubsub_messages())

    async def disconnect(self, close_code):
        if self.reader_task is not None:
            self.reader_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
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
