import asyncio
import json
import time
from contextlib import suppress
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer, AsyncWebsocketConsumer
from myapp.jwt_auth_middleware import AUTH_WEBSOCKET_PROTOCOL
from myapp.models import Device
from myapp.alarm_monitoring import ALARM_GROUP, build_alarm_snapshot


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


class AlarmConsumer(AsyncJsonWebsocketConsumer):
    heartbeat_interval_seconds = 30
    heartbeat_timeout_seconds = 75

    async def connect(self):
        self.user = self.scope.get("user")
        if not getattr(self.user, "is_authenticated", False):
            await self.close(code=4401)
            return
        self.last_pong_at = time.monotonic()
        self.heartbeat_task = None
        await self.channel_layer.group_add(ALARM_GROUP, self.channel_name)
        await self.accept(subprotocol=_accepted_subprotocol(self.scope))
        await self._send_snapshot()
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(ALARM_GROUP, self.channel_name)
        task = getattr(self, "heartbeat_task", None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "alarm.pong":
            self.last_pong_at = time.monotonic()

    async def alarm_state_changed(self, event):
        await self._send_snapshot(revision=event.get("revision"), reason=event.get("reason"))

    async def _send_snapshot(self, *, revision=None, reason=None):
        payload = await database_sync_to_async(build_alarm_snapshot)(self.user, revision=revision)
        if reason:
            payload["reason"] = reason
        await self.send_json(payload)

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            if time.monotonic() - self.last_pong_at > self.heartbeat_timeout_seconds:
                await self.close(code=4408)
                return
            await self.send_json({"type": "alarm.ping"})
