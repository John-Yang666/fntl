# models.py  —— sy 设备网管版
import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group, Permission, AbstractUser
from django.db.models.signals import post_migrate, post_save, m2m_changed
from django.dispatch import receiver

SYSTEM_ADMIN_GROUP_NAME = 'System Admin'
REGULAR_USER_GROUP_NAME = 'Regular User'


# -------------------------
# 1) 初始化用户组（保留你的逻辑）
# -------------------------
@receiver(post_migrate)
def create_user_groups(sender, **kwargs):
    admin_group, _ = Group.objects.get_or_create(name=SYSTEM_ADMIN_GROUP_NAME)
    admin_group.permissions.set(Permission.objects.filter(codename__startswith='view_'))

    user_group, _ = Group.objects.get_or_create(name=REGULAR_USER_GROUP_NAME)
    user_group.permissions.clear()


# -------------------------
# 2) 用户
# -------------------------
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


# -------------------------
# 3) 设备
# -------------------------
class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.IntegerField(unique=True, verbose_name="设备ID")
    name = models.CharField(max_length=100, default="Unnamed Device", verbose_name="设备名称")
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
    )
    ip_address = models.GenericIPAddressField(unique=True, verbose_name="IP地址", null=True, blank=True)

    # 拓扑
    x_coordinate = models.FloatField(default=0.0, verbose_name="X坐标")
    y_coordinate = models.FloatField(default=0.0, verbose_name="Y坐标")
    direction1_neighbor_id = models.IntegerField(null=True, blank=True, db_index=True, default=0, verbose_name="一方向邻站ID")
    direction1_neighbor_direction = models.IntegerField(null=True, blank=True, db_index=True, default=2, verbose_name="一方向邻站方向")
    direction2_neighbor_id = models.IntegerField(null=True, blank=True, db_index=True, default=0, verbose_name="二方向邻站ID")
    direction2_neighbor_direction = models.IntegerField(null=True, blank=True, db_index=True, default=1, verbose_name="二方向邻站方向")

    # sy 增强：第三方向 + 自动切换能力标记（来自 d4.D7，有/无自动切换）
    direction3_enabled = models.BooleanField(default=False, verbose_name="三方向启用")  # sy 特有
    supports_auto_switch = models.BooleanField(default=False, verbose_name="具备自动切换功能")  # 由状态量4.D7推断 :contentReference[oaicite:0]{index=0}
    direction3_neighbor_id = models.IntegerField(
    null=True,
    blank=True,
    db_index=True,
    default=0,
    verbose_name="三方向邻站ID"
    )
    direction3_neighbor_direction = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        default=1,  
        verbose_name="三方向邻站方向"
    )

    remark = models.TextField(blank=True, null=True, verbose_name="备注")
    alarm_filters = models.JSONField(blank=True, default=list, verbose_name="过滤告警码")
    direction1_enabled = models.BooleanField(default=True, verbose_name="一方向启用")
    direction2_enabled = models.BooleanField(default=True, verbose_name="二方向启用")

    direction1_cable_alarm_linkage = models.BooleanField(default=False, verbose_name="一方向电缆告警联动")
    direction2_cable_alarm_linkage = models.BooleanField(default=False, verbose_name="二方向电缆告警联动")

    # 动态地址派发设计（可选，用于配置/记录）
    manual_address = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="人工指定地址(非0)")
    is_dynamic_addressing = models.BooleanField(default=False, verbose_name="启用动态地址派发")  # 由上行封连决定的自动派发策略 :contentReference[oaicite:1]{index=1}
    sealed_base_addr_bcd = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="上行封连BCD首地址")  # D7..D0 描述封连位 :contentReference[oaicite:2]{index=2}

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

# -------------------------
# 4.1) 原始协议帧日志（sy_agent 上送的完整帧
# -------------------------
class RawFrameLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id',
                               on_delete=models.CASCADE, verbose_name="设备",
                               null=True, blank=True)
    raw_frame = models.BinaryField(verbose_name="完整协议帧")  # 含7F7F...F7F7
    cmd = models.CharField(max_length=4, verbose_name="命令字", null=True, blank=True)  # 如 "A1"/"A2"/"??"
    note = models.CharField(max_length=100, verbose_name="备注", null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "原始协议帧"
        verbose_name_plural = "原始协议帧"
        indexes = [
            models.Index(fields=["timestamp"], name="sy_rawframe_ts_idx"),
        ]


# ---------------------------------------
# 4.2) sy 协议状态数据（核心：4字节 d1~d4）
#    兼容老版 6 字节：protocol_bytes 存储原始帧；version 标识
# ---------------------------------------
class SwitchData(models.Model):
    """
    sy 设备的“全部开关量”快照（A1 命令返回 d1~d4），以及版本标记。
    - 现行版：4 字节（d1 一方向, d2 二方向, d3 三方向, d4 系统）
    - 老版：最多 6 字节（为了兼容，version 做一个标记）
    数据实际存放在 switch_status 里，admin、导出等都还能沿用原来的名字。
    """
    VERSION_CHOICES = (
        ("v4", "4-byte (d1~d4)"),
        ("v6", "6-byte (legacy)"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    switch_status = models.BinaryField(verbose_name="原始状态字节")
    version = models.CharField(max_length=4, choices=VERSION_CHOICES, default="v4")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "状态字快照"
        verbose_name_plural = "状态字快照"
        indexes = [
            models.Index(fields=["timestamp"], name="sy_switch_ts_idx"),
        ]

    # ====== 通用 bit 工具 ======
    def _byte_at(self, idx: int) -> int:
        b = bytes(self.switch_status or b"")
        return b[idx] if len(b) > idx else 0

    @staticmethod
    def _bit(byte_val: int, pos: int) -> int:
        return (byte_val >> pos) & 0x01

    # 提供一个通用的按位访问，兼容老代码可能用的 get_bit(position)
    def get_bit(self, position: int) -> int:
        """
        position 从 0 开始，按从高位到低位展开：
        byte0.D7 -> position=0, byte0.D6 -> 1, ... 依次类推
        """
        b = bytes(self.switch_status or b"")
        total_bits = len(b) * 8
        if total_bits == 0 or position < 0 or position >= total_bits:
            return 0
        # 高位在前
        adjusted = total_bits - 1 - position
        return (int.from_bytes(b, byteorder="big") >> adjusted) & 1

    def get_status_bits(self) -> str:
        """
        兼容 admin 中导出用的函数：
        把当前所有字节展开成 0/1 字符串（长度 = 8 * 字节数）
        """
        b = bytes(self.switch_status or b"")
        total_bits = len(b) * 8
        if total_bits == 0:
            return ""
        val = int.from_bytes(b, byteorder="big")
        bits = [(val >> (total_bits - 1 - i)) & 1 for i in range(total_bits)]
        return "".join(str(bit) for bit in bits)

    # ====== 按 d1~d4 字节解析（sy 协议） ======
    def d1(self):  # 一方向
        return self._byte_at(0)

    def d2(self):  # 二方向
        return self._byte_at(1)

    def d3(self):  # 三方向 / 自动切换 & 电缆测试
        return self._byte_at(2)

    def d4(self):  # 系统状态
        return self._byte_at(3)

    # 一方向 d1：D7 1ZXJ, D6 1FXJ, D5 1ZDJ, D4 1FDJ, D3 IA, D2 IB, D1 使用位, D0 故障位
    @property
    def dir1_ZXJ(self):  # D7
        return self._bit(self.d1(), 7)

    @property
    def dir1_FXJ(self):  # D6
        return self._bit(self.d1(), 6)

    @property
    def dir1_ZDJ(self):  # D5
        return self._bit(self.d1(), 5)

    @property
    def dir1_FDJ(self):  # D4
        return self._bit(self.d1(), 4)

    @property
    def IA_ok(self):     # D3: IA 1=正常
        return self._bit(self.d1(), 3) == 1

    @property
    def IB_ok(self):     # D2: IB 1=正常
        return self._bit(self.d1(), 2) == 1

    @property
    def dir1_used(self): # D1 使用位
        return self._bit(self.d1(), 1) == 1

    @property
    def dir1_fault(self):# D0 故障
        return self._bit(self.d1(), 0) == 1

    # 二方向 d2（位义同 d1）
    @property
    def dir2_ZXJ(self):
        return self._bit(self.d2(), 7)

    @property
    def dir2_FXJ(self):
        return self._bit(self.d2(), 6)

    @property
    def dir2_ZDJ(self):
        return self._bit(self.d2(), 5)

    @property
    def dir2_FDJ(self):
        return self._bit(self.d2(), 4)

    @property
    def IIA_ok(self):
        return self._bit(self.d2(), 3) == 1

    @property
    def IIB_ok(self):
        return self._bit(self.d2(), 2) == 1

    @property
    def dir2_used(self):
        return self._bit(self.d2(), 1) == 1

    @property
    def dir2_fault(self):
        return self._bit(self.d2(), 0) == 1

    # 三方向 / 自动切换 & 电缆测试（d3）
    @property
    def dir3_ZXJ(self):
        return self._bit(self.d3(), 7)

    @property
    def dir3_FXJ(self):
        return self._bit(self.d3(), 6)

    @property
    def dir3_ZDJ(self):
        return self._bit(self.d3(), 5)

    @property
    def dir3_FDJ(self):
        return self._bit(self.d3(), 4)

    @property
    def IIIA_cable_up_ok(self):
        return self._bit(self.d3(), 3) == 1

    @property
    def IIIB_cable_dn_ok(self):
        return self._bit(self.d3(), 2) == 1

    @property
    def has_cable_test(self):
        return self._bit(self.d3(), 1) == 1

    # 系统状态 d4
    @property
    def auto_switch_capable(self):  # D7=1 有自动切换功能
        return self._bit(self.d4(), 7) == 1

    @property
    def system_fault(self):         # D6
        return self._bit(self.d4(), 6) == 1

    @property
    def excitation_fault(self):     # D5
        return self._bit(self.d4(), 5) == 1

    @property
    def channel_fault(self):        # D4
        return self._bit(self.d4(), 4) == 1

    @property
    def BGZJ(self):                 # D1
        return self._bit(self.d4(), 1) == 1

    @property
    def AGZJ(self):                 # D0
        return self._bit(self.d4(), 0) == 1

    def __str__(self):
        b = bytes(self.switch_status or b"")
        return f"Device {self.device.device_id} sy状态帧 len={len(b)}, ver={self.version}"

# A2（单点变化）；不落库也行（只做前端实时推送）。
class ChangeBitEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    bit_index = models.PositiveIntegerField(verbose_name="位序号(0-based, 按 d1~d4 展开共32位)")
    value = models.BooleanField(verbose_name="变为(0/1)")
    source = models.CharField(max_length=32, default="A2", verbose_name="来源")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        indexes = [
            models.Index(fields=["device", "timestamp"]),
            models.Index(fields=["timestamp"], name="sy_changebit_ts_idx"),
        ]
        ordering = ["-timestamp"]
        verbose_name = "变化量事件"
        verbose_name_plural = "变化量事件"

# -------------------------
# 5) 告警（保留）
# -------------------------
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
        return settings.SY_ALARM_MEANINGS.get(self.alarm_code, "未知告警")

    def confirmed_status_display(self):
        return "已确认" if self.is_confirmed else "未确认"

    def __str__(self):
        return f"{self.device.name} 当前告警: {self.alarm_code}（{self.alarm_meaning}）"


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
            models.Index(fields=['-timestamp_start'], name='sy_alarmdata_ts_desc_idx'),
            models.Index(fields=['is_confirmed', '-timestamp_start'], name='sy_alarmdata_conf_ts_idx'),
            models.Index(fields=['device', '-timestamp_start'], name='sy_alarmdata_dev_ts_idx'),
            models.Index(fields=['device', 'is_confirmed'], name='sy_alarmdata_dev_conf_idx'),
        ]

    @property
    def alarm_meaning(self):
        return settings.SY_ALARM_MEANINGS.get(self.alarm_code, "未知告警")

    def confirmed_status_display(self):
        return "已确认" if self.is_confirmed else "未确认"

    def __str__(self):
        return f"{self.device.name} 历史告警: {self.alarm_code}（{self.alarm_meaning}）"


# -------------------------
# 7) 继电器动作 & 用户操作（保留）
# -------------------------
class RelayAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    relay = models.CharField(max_length=100, verbose_name="继电器")
    action = models.CharField(max_length=100, verbose_name="动作")
    source = models.CharField(max_length=16, null=True, blank=True, verbose_name="来源")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "继电器动作记录"
        verbose_name_plural = "继电器动作"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=["timestamp"], name="sy_relay_ts_idx"),
            models.Index(fields=["device", "-timestamp"], name="sy_relay_dev_ts_desc_idx"),
        ]

    def __str__(self):
        return f"Device {self.device.device_id} - Relay {self.relay} - Action {self.action} at {self.timestamp}"


class UserOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备", null=True, blank=True)
    function_code = models.CharField(max_length=100, verbose_name="操作类型")
    operation = models.CharField(max_length=100, verbose_name="操作名称")
    username = models.CharField(max_length=100, verbose_name="用户名", null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        verbose_name = "用户操作记录"
        verbose_name_plural = "用户操作"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=["timestamp"], name="sy_userop_ts_idx"),
        ]

    def __str__(self):
        device_label = str(self.device) if self.device_id is not None else "系统级操作"
        return f"{device_label} - {self.function_code} - {self.operation} by {self.username} at {self.timestamp}"


# -------------------------
# 8) 远程控制发令与回执（新增，追溯 BB 命令 BB xx）#功能与用户操作重复，暂时不用20251212
# -------------------------
class RemoteControlLog(models.Model):
    """
    记录 sy 远程控制（BB 指令族）与结果：
      0x37 启动本站；0x12 强制A落下；0x24 强制B落下；
      0x03 上行自动；0x05 上行强制电缆；
      0x17 下行自动；0x18 下行强制电缆；
      0x32/0x38 上行第一/第二故障点；0x82/0x88 下行第一/第二故障点 等等。:contentReference[oaicite:9]{index=9}
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    code_hex = models.CharField(max_length=4, verbose_name="控制码(十六进制字符串)")  # 如 "0x37"
    description = models.CharField(max_length=100, verbose_name="含义")             # 例如 “远程启动本站/上行自动…”
    issued_by = models.CharField(max_length=100, null=True, blank=True, verbose_name="下发人/程序")
    success = models.BooleanField(default=False, verbose_name="执行是否成功")
    reply_raw = models.BinaryField(null=True, blank=True, verbose_name="回执原文")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="时间")

    class Meta:
        verbose_name = "远程控制日志"
        verbose_name_plural = "远程控制日志"
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.device.device_id} BB {self.code_hex} {self.description} success={self.success}"


# -------------------------
# 9) 文件（保留）
# -------------------------
class UploadedFile(models.Model):
    file = models.FileField(upload_to='uploads/', verbose_name="文件")
    name = models.CharField(max_length=255, verbose_name="备注名称")
    upload_time = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

    class Meta:
        verbose_name = "文件"
        verbose_name_plural = "文件管理"
        ordering = ['-upload_time']

    def __str__(self):
        return f"{self.name} ({self.upload_time.strftime('%Y-%m-%d %H:%M:%S')})"


class RuntimeConfig(models.Model):
    values = models.JSONField(default=dict, verbose_name="运行时配置")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sy_runtime_config_updates",
        verbose_name="更新人",
    )

    class Meta:
        verbose_name = "运行时配置"
        verbose_name_plural = "运行时配置"

    def __str__(self):
        return f"RuntimeConfig#{self.pk}"
