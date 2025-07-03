# models.py
import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group, Permission, AbstractUser
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_migrate
from django.dispatch import receiver

@receiver(post_migrate)
def create_user_groups(sender, **kwargs):
    # 创建系统管理员组
    admin_group, created = Group.objects.get_or_create(name='System Admin')
    if created:
        # 给系统管理员组添加所有权限
        permissions = Permission.objects.all()
        admin_group.permissions.set(permissions)

    # 创建普通用户组
    user_group, created = Group.objects.get_or_create(name='Regular User')
    if created:
        # 给普通用户组添加查看权限
        view_permission = Permission.objects.filter(codename__startswith='view_')
        user_group.permissions.set(view_permission)

class CustomUser(AbstractUser):
    depots = models.JSONField(default=list, blank=True, verbose_name="可管理车间")

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"

class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device_id = models.IntegerField(unique=True, verbose_name="设备ID")  # 设备ID列
    name = models.CharField(max_length=100, default="Unnamed Device", verbose_name="设备名称")  # 设备名称列
    depot = models.CharField(max_length=100, default="Unknown Depot", verbose_name="车间")
    line = models.CharField(max_length=100, default="Unknown Line", verbose_name="线路")  # 所属线路列
    ip_address = models.GenericIPAddressField(unique=True, verbose_name="IP地址")  # IP地址列
    x_coordinate = models.FloatField(default=0.0, verbose_name="X坐标")  # X坐标
    y_coordinate = models.FloatField(default=0.0, verbose_name="Y坐标")  # Y坐标
    direction1_neighbor_id = models.IntegerField(null=True, blank=True, db_index=True, default=0, verbose_name="一方向邻站ID")
    direction1_neighbor_direction = models.IntegerField(null=True, blank=True, db_index=True, default=2, verbose_name="一方向邻站方向")
    direction2_neighbor_id = models.IntegerField(null=True, blank=True, db_index=True, default=0, verbose_name="二方向邻站ID")
    direction2_neighbor_direction = models.IntegerField(null=True, blank=True, db_index=True, default=1, verbose_name="二方向邻站方向")
    remark = models.TextField(blank=True, null=True, verbose_name="备注")# 新增的备注字段 20241205
    alarm_filters = models.JSONField(blank=True, default=list, verbose_name="过滤告警码")#20241205新增过滤告警码字段

    class Meta:
        verbose_name = "设备信息"
        verbose_name_plural = "设备信息"
        ordering = ['device_id']

    def __str__(self):
        return f"{self.name} ID: {self.device_id} - IP: {self.ip_address}"

class SwitchData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    switch_status = models.BinaryField()  # 存储开关量数据
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '开关量数据记录'
        verbose_name_plural = '开关量数据'

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

class AnalogData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    voltage_1 = models.FloatField(verbose_name="电压1(V)")
    current_1 = models.FloatField(verbose_name="电流1(A)")
    voltage_2 = models.FloatField(verbose_name="电压2(V)")
    current_2 = models.FloatField(verbose_name="电流2(A)")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '电压电流数据'
        verbose_name_plural = '电压电流数据'

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
    
    def __str__(self):
        return f"Device {self.device.device_id} - Relay {self.relay} - Action {self.action} at {self.timestamp}"

class UserOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 使用 UUID 作为主键
    device = models.ForeignKey(Device, to_field='device_id', on_delete=models.CASCADE, verbose_name="设备")
    function_code = models.CharField(max_length=100, verbose_name="操作码")
    operation = models.CharField(max_length=100, verbose_name="操作名称")
    username = models.CharField(max_length=100, verbose_name="用户名", null=True, blank=True)  # 新增字段
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        verbose_name = "用户操作记录"
        verbose_name_plural = "用户操作"
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.device} - {self.function_code} - {self.operation} by {self.username} at {self.timestamp}"

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
