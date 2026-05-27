import json
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
