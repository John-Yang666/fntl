# models.py
import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group, Permission, AbstractUser
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_migrate, post_save, m2m_changed
from django.dispatch import receiver

SYSTEM_ADMIN_GROUP_NAME = 'System Admin'
REGULAR_USER_GROUP_NAME = 'Regular User'


@receiver(post_migrate)
def create_user_groups(sender, **kwargs):
    # 创建系统管理员组，仅授予浏览后台所需的只读权限
    admin_group, created = Group.objects.get_or_create(name=SYSTEM_ADMIN_GROUP_NAME)
    admin_group.permissions.set(Permission.objects.filter(codename__startswith='view_'))

    # 创建普通用户组
    user_group, created = Group.objects.get_or_create(name=REGULAR_USER_GROUP_NAME)
    # 普通用户只允许登录前端，不授予后台权限
    user_group.permissions.clear()

class CustomUser(AbstractUser):
    email = models.EmailField(null=True, blank=True, verbose_name="邮箱")
    depots = models.ManyToManyField("myapp.Depot", blank=True, verbose_name="可管理车间")

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def managed_depots_qs(self):
        if self.is_superuser:
            return self.depots.model.objects.all()
        return self.depots.all()

    @property
    def manages_all_depots(self):
        return self.is_superuser


def _desired_staff_status(user: CustomUser) -> bool:
    if user.is_superuser:
        return True
    if not user.pk:
        return False
    return user.groups.filter(name=SYSTEM_ADMIN_GROUP_NAME).exists()


def sync_user_role_flags(user: CustomUser, *, save: bool = True) -> None:
    desired_is_staff = _desired_staff_status(user)
    if user.is_staff == desired_is_staff:
        return
    user.is_staff = desired_is_staff
    if save and user.pk:
        user.save(update_fields=['is_staff'])


@receiver(post_save, sender=CustomUser)
def sync_user_role_flags_on_save(sender, instance, **kwargs):
    desired_is_staff = _desired_staff_status(instance)
    if instance.is_staff != desired_is_staff:
        sender.objects.filter(pk=instance.pk).update(is_staff=desired_is_staff)


@receiver(m2m_changed, sender=CustomUser.groups.through)
def sync_user_role_flags_on_group_change(sender, instance, action, reverse, **kwargs):
    if reverse or action not in {'post_add', 'post_remove', 'post_clear'}:
        return
    sync_user_role_flags(instance)


class Depot(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="车间名称")
    is_active = models.BooleanField(default=True, verbose_name="启用")
    remark = models.CharField(max_length=200, blank=True, default="", verbose_name="备注")
    ordering = models.PositiveIntegerField(default=0, verbose_name="排序")

    class Meta:
        verbose_name = "车间"
        verbose_name_plural = "车间"
        ordering = ["ordering", "name"]

    def __str__(self):
        return self.name


class Line(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="线路名称")
    is_active = models.BooleanField(default=True, verbose_name="启用")
    remark = models.CharField(max_length=200, blank=True, default="", verbose_name="备注")
    ordering = models.PositiveIntegerField(default=0, verbose_name="排序")

    class Meta:
        verbose_name = "线路"
        verbose_name_plural = "线路"
        ordering = ["ordering", "name"]

    def __str__(self):
        return self.name


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device_id = models.IntegerField(unique=True, verbose_name="设备ID")  # 设备ID列
    name = models.CharField(max_length=100, default="Unnamed Device", verbose_name="设备名称")  # 设备名称列
    depot = models.ForeignKey(
        "myapp.Depot",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="车间",
    )
    line = models.ForeignKey(
        "myapp.Line",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="线路",
    )  # 所属线路列
    ip_address = models.GenericIPAddressField(unique=True, verbose_name="IP地址")  # IP地址列
    x_coordinate = models.FloatField(default=0.0, verbose_name="X坐标")  # X坐标
    y_coordinate = models.FloatField(default=0.0, verbose_name="Y坐标")  # Y坐标
    direction1_neighbor_id = models.IntegerField(null=True, blank=True, db_index=True, default=0, verbose_name="一方向邻站ID")
    direction1_neighbor_direction = models.IntegerField(null=True, blank=True, db_index=True, default=2, verbose_name="一方向邻站方向")
    direction2_neighbor_id = models.IntegerField(null=True, blank=True, db_index=True, default=0, verbose_name="二方向邻站ID")
    direction2_neighbor_direction = models.IntegerField(null=True, blank=True, db_index=True, default=1, verbose_name="二方向邻站方向")
    remark = models.TextField(blank=True, null=True, verbose_name="备注")# 新增的备注字段 20241205
    alarm_filters = models.JSONField(blank=True, default=list, verbose_name="过滤告警码")#20241205新增过滤告警码字段
    direction1_enabled = models.BooleanField(default=True, verbose_name="一方向启用")# 20250814新增
    direction2_enabled = models.BooleanField(default=True, verbose_name="二方向启用")# 20250814新增

    class Meta:
        verbose_name = "设备信息"
        verbose_name_plural = "设备信息"
        ordering = ['device_id']

    def __str__(self):
        return f"{self.name} ID: {self.device_id} - IP: {self.ip_address}"

    @property
    def depot_name(self) -> str:
        return self.depot.name if self.depot else ""

    @property
    def line_name(self) -> str:
        return self.line.name if self.line else ""


class UserMonitoringPreference(models.Model):
    MODE_ALL = "all"
    MODE_CUSTOM = "custom"
    MODE_CHOICES = (
        (MODE_ALL, "全部有权设备"),
        (MODE_CUSTOM, "自定义设备"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monitoring_preference",
        verbose_name="用户",
    )
    selection_mode = models.CharField(
        max_length=10,
        choices=MODE_CHOICES,
        default=MODE_ALL,
        verbose_name="监控范围",
    )
    monitored_devices = models.ManyToManyField(
        Device,
        blank=True,
        related_name="monitoring_preferences",
        verbose_name="监控设备",
    )

    class Meta:
        verbose_name = "用户监控配置"
        verbose_name_plural = "用户监控配置"

class SwitchData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    switch_status = models.BinaryField()  # 存储开关量数据
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '开关量数据记录'
        verbose_name_plural = '开关量数据'
        indexes = [
            models.Index(fields=['timestamp'], name='bt_switch_ts_idx'),
        ]

    def __str__(self):
        status_bits = self.get_status_bits()
        return f"Device {self.device.device_id} - Switch Status: {status_bits}"
    
    def get_bit(self, position):
        # 将二进制数据转换为整数
        status_int = int.from_bytes(self.switch_status, byteorder='big')
        # 计算总位数
        total_bits = 368
        # 从左到右的位索引
        adjusted_position = total_bits - 1 - position
        # 右移到指定位置并与1进行按位与运算
        return (status_int >> adjusted_position) & 1

    def get_status_bits(self):
        # 将二进制数据转换为整数
        status_int = int.from_bytes(self.switch_status, byteorder='big')
        # 计算总位数
        total_bits = 368
        # 将所有位转换为0和1
        bits = [(status_int >> (total_bits - 1 - i)) & 1 for i in range(total_bits)]
        return ''.join(str(bit) for bit in bits)

    def get_status_bits_grouped_by_byte(self, start_byte=4):
        """按字节显示开关量：例如 (4)01010101 (5)11001100 ..."""
        if not self.switch_status:
            return ""

        raw_status = self.switch_status
        if isinstance(raw_status, memoryview):
            raw_status = raw_status.tobytes()
        elif isinstance(raw_status, bytearray):
            raw_status = bytes(raw_status)

        grouped = []
        for idx, byte_value in enumerate(raw_status):
            if isinstance(byte_value, int):
                value = byte_value
            elif isinstance(byte_value, (bytes, bytearray, memoryview)):
                value = int.from_bytes(bytes(byte_value)[:1], byteorder="big")
            else:
                value = int(byte_value)
            grouped.append(f"({start_byte + idx}){value:08b}")
        return " ".join(grouped)

class AnalogData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    voltage_1 = models.FloatField(verbose_name="电压1(V)")
    current_1 = models.FloatField(verbose_name="电流1(mA)")
    voltage_2 = models.FloatField(verbose_name="电压2(V)")
    current_2 = models.FloatField(verbose_name="电流2(mA)")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '电压电流数据'
        verbose_name_plural = '电压电流数据'
        indexes = [
            models.Index(fields=['timestamp'], name='bt_analog_ts_idx'),
        ]

    def __str__(self):
        return f"Device {self.device.device_id} - Voltage 1: {self.voltage_1} - Current 1: {self.current_1} - Voltage 2: {self.voltage_2} - Current 2: {self.current_2}"

class AlarmActive(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    alarm_code = models.IntegerField(verbose_name="告警码")
    timestamp_start = models.DateTimeField(auto_now_add=True, verbose_name="告警开始时间")
    is_confirmed = models.BooleanField(default=False, verbose_name="确认状态")

    class Meta:
        verbose_name = "当前告警信息"
        verbose_name_plural = "当前告警"
        unique_together = ('device', 'alarm_code')
        ordering = ['-timestamp_start']

    @property
    def alarm_meaning(self):
        return settings.ALARM_MEANINGS.get(self.alarm_code, "未知告警")

    def confirmed_status_display(self):
        return "已确认" if self.is_confirmed else "未确认"

    def __str__(self):
        return f"{self.device.name} 当前告警: {self.alarm_code}（{self.alarm_meaning}）"

#历史告警
class AlarmData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    alarm_code = models.IntegerField(verbose_name="告警码")
    timestamp_start = models.DateTimeField(verbose_name="告警开始时间")
    timestamp_end = models.DateTimeField(null=True, blank=True, verbose_name="告警结束时间")
    is_confirmed = models.BooleanField(default=False, verbose_name="确认状态")

    class Meta:
        ordering = ['-timestamp_start']
        verbose_name = '历史告警记录'
        verbose_name_plural = '历史告警'
        indexes = [
            models.Index(fields=['-timestamp_start'], name='bt_alarmdata_ts_desc_idx'),
            models.Index(fields=['is_confirmed', '-timestamp_start'], name='bt_alarmdata_conf_ts_idx'),
            models.Index(fields=['device', '-timestamp_start'], name='bt_alarmdata_dev_ts_idx'),
            models.Index(fields=['device', 'is_confirmed'], name='bt_alarmdata_dev_conf_idx'),
        ]

    @property
    def alarm_meaning(self):
        return settings.ALARM_MEANINGS.get(self.alarm_code, "未知告警")

    def confirmed_status_display(self):
        return "已确认" if self.is_confirmed else "未确认"

    def __str__(self):
        return f"{self.device.name} 历史告警: {self.alarm_code}（{self.alarm_meaning}）"
    
class RelayAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    relay = models.CharField(max_length=100, verbose_name="继电器")
    action = models.CharField(max_length=100, verbose_name="动作")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="时间")
    
    class Meta:
        verbose_name = "继电器动作记录"
        verbose_name_plural = "继电器动作"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp'], name='bt_relay_ts_idx'),
            models.Index(fields=['device', '-timestamp'], name='bt_relay_dev_ts_desc_idx'),
        ]
    
    def __str__(self):
        return f"Device {self.device.device_id} - Relay {self.relay} - Action {self.action} at {self.timestamp}"

class UserOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备", null=True, blank=True)
    function_code = models.CharField(max_length=100, verbose_name="操作码")
    operation = models.CharField(max_length=100, verbose_name="操作名称")
    username = models.CharField(max_length=100, verbose_name="用户名", null=True, blank=True)  # 新增字段
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        verbose_name = "用户操作记录"
        verbose_name_plural = "用户操作"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp'], name='bt_userop_ts_idx'),
        ]

    def __str__(self):
        device_label = str(self.device) if self.device_id is not None else "系统级操作"
        return f"{device_label} - {self.function_code} - {self.operation} by {self.username} at {self.timestamp}"

class UploadedFile(models.Model):
    file = models.FileField(upload_to='uploads/', verbose_name="文件")
    name = models.CharField(max_length=255, verbose_name= "备注名称")
    upload_time = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

    class Meta:
        verbose_name = "文件"
        verbose_name_plural = "文件管理"
        ordering = ['-upload_time']

    def __str__(self):
        return f"{self.name} ({self.upload_time.strftime('%Y-%m-%d %H:%M:%S')})"


class HelpFaqEntry(models.Model):
    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(verbose_name="内容")
    display_order = models.PositiveIntegerField(default=0, db_index=True, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "帮助页常见问题"
        verbose_name_plural = "帮助页常见问题"
        ordering = ["display_order", "id"]

    def __str__(self):
        return f"{self.display_order}. {self.title}"


class RuntimeConfig(models.Model):
    values = models.JSONField(default=dict, verbose_name="运行时配置")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bt_runtime_config_updates",
        verbose_name="更新人",
    )

    class Meta:
        verbose_name = "运行时配置"
        verbose_name_plural = "运行时配置"

    def __str__(self):
        return f"RuntimeConfig#{self.pk}"
