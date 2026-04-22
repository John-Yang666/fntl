from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import format_lazy
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .runtime_config import get_jwt_access_token_lifetime, get_jwt_refresh_token_lifetime


class RuntimeConfigTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token.set_exp(lifetime=get_jwt_refresh_token_lifetime())
        return token

    def validate(self, attrs):
        super(TokenObtainPairSerializer, self).validate(attrs)
        refresh = self.get_token(self.user)
        access = refresh.access_token
        access.set_exp(lifetime=get_jwt_access_token_lifetime())
        data = {
            "refresh": str(refresh),
            "access": str(access),
        }

        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)

        return data


class RuntimeConfigTokenRefreshSerializer(TokenRefreshSerializer):
    default_error_messages = {
        "no_active_account": format_lazy("No active account found for the given token.")
    }

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])

        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM, None)
        if user_id:
            user = get_user_model().objects.get(**{api_settings.USER_ID_FIELD: user_id})
            if not api_settings.USER_AUTHENTICATION_RULE(user):
                raise AuthenticationFailed(
                    self.error_messages["no_active_account"],
                    "no_active_account",
                )

        access = refresh.access_token
        access.set_exp(lifetime=get_jwt_access_token_lifetime())
        data = {"access": str(access)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass

            refresh.set_jti()
            refresh.set_iat()
            refresh.set_exp(lifetime=get_jwt_refresh_token_lifetime())

            try:
                refresh.outstand()
            except AttributeError:
                pass

            data["refresh"] = str(refresh)

        return data


class RuntimeConfigTokenObtainPairView(TokenObtainPairView):
    serializer_class = RuntimeConfigTokenObtainPairSerializer


class RuntimeConfigTokenRefreshView(TokenRefreshView):
    serializer_class = RuntimeConfigTokenRefreshSerializer
