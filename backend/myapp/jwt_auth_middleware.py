from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from rest_framework_simplejwt.authentication import JWTAuthentication

AUTH_WEBSOCKET_PROTOCOL = "bt-nms"


@database_sync_to_async
def _get_user_for_token(raw_token: str):
    authenticator = JWTAuthentication()
    validated_token = authenticator.get_validated_token(raw_token)
    return authenticator.get_user(validated_token)


class QueryStringJWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        close_old_connections()
        query_string = scope.get("query_string", b"").decode()
        token = parse_qs(query_string).get("token", [None])[0]
        if not token:
            token = _token_from_subprotocols(scope.get("headers", []))

        if token:
            try:
                scope["user"] = await _get_user_for_token(token)
            except Exception:
                scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    return QueryStringJWTAuthMiddleware(AuthMiddlewareStack(inner))


def _token_from_subprotocols(headers) -> str | None:
    for name, value in headers:
        if name.lower() != b"sec-websocket-protocol":
            continue
        protocols = value.decode("ascii", errors="ignore").split(",")
        for protocol in protocols:
            protocol = protocol.strip()
            if protocol.startswith("jwt."):
                return protocol.removeprefix("jwt.")
    return None
