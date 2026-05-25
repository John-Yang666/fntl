from .models import UserOperation


def _username(user) -> str:
    return getattr(user, "username", "") or ""


def log_system_operation(*, user, function_code: str, operation: str) -> UserOperation:
    return UserOperation.objects.create(
        device=None,
        function_code=function_code,
        operation=operation,
        username=_username(user),
    )


def log_device_operation(*, user, device, function_code: str, operation: str) -> UserOperation:
    return UserOperation.objects.create(
        device=device,
        function_code=function_code,
        operation=operation,
        username=_username(user),
    )
