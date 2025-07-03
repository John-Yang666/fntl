#myapp/tasks/relay_processing.py
from datetime import datetime
from celery import shared_task
from django.core.cache import cache
from myapp.models import RelayAction
from .process_tasks_helpers import get_switch_bit_value

@shared_task
def record_relay_actions(device_id, switch_status):
    actions = extract_relay_actions(device_id, switch_status)
    for action in actions:
        RelayAction.objects.create(device_id=device_id, relay=action['relay'], action=action['action'], timestamp=action['timestamp'])

def extract_relay_actions(device_id, switch_status):
    actions = []
    current_time = datetime.now()
    
    # 确保 switch_status 是 bytes 类型
    if isinstance(switch_status, str):
        switch_status = bytes(switch_status, 'utf-8')
    
    # 获取缓存中上一次的继电器状态
    previous_relay_status = cache.get(f'device_{device_id}_relay_status', {})
    
    # 设置一个提取数据时字节码的偏移量i
    i = 9
    
    # 定义继电器和其对应的字节序号和位序号
    relay_mapping = [
        ("一方向本站QHJ", 7, 0),
        ("一方向邻站QHJ", 9, 0),
        ("二方向本站QHJ", 11, 0),
        ("二方向邻站QHJ", 13, 0),
        ("一方向本站ZDJ(A系)", 14, 0),
        ("一方向本站FDJ(A系)", 14, 2),
        ("一方向本站ZXJ(A系)", 14, 4),
        ("一方向本站FXJ(A系)", 14, 6),
        ("一方向邻站ZDJ(A系)", 22, 0),
        ("一方向邻站FDJ(A系)", 22, 2),
        ("一方向邻站ZXJ(A系)", 22, 4),
        ("一方向邻站FXJ(A系)", 22, 6),
        ("二方向本站ZDJ(A系)", 32, 0),
        ("二方向本站FDJ(A系)", 32, 2),
        ("二方向本站ZXJ(A系)", 32, 4),
        ("二方向本站FXJ(A系)", 32, 6),
        ("二方向邻站ZDJ(A系)", 40, 0),
        ("二方向邻站FDJ(A系)", 40, 2),
        ("二方向邻站ZXJ(A系)", 40, 4),
        ("二方向邻站FXJ(A系)", 40, 6),
        ("一方向本站ZDJ(B系)", 14 + i, 0),
        ("一方向本站FDJ(B系)", 14 + i, 2),
        ("一方向本站ZXJ(B系)", 14 + i, 4),
        ("一方向本站FXJ(B系)", 14 + i, 6),
        ("一方向邻站ZDJ(B系)", 22 + i, 0),
        ("一方向邻站FDJ(B系)", 22 + i, 2),
        ("一方向邻站ZXJ(B系)", 22 + i, 4),
        ("一方向邻站FXJ(B系)", 22 + i, 6),
        ("二方向本站ZDJ(B系)", 32 + i, 0),
        ("二方向本站FDJ(B系)", 32 + i, 2),
        ("二方向本站ZXJ(B系)", 32 + i, 4),
        ("二方向本站FXJ(B系)", 32 + i, 6),
        ("二方向邻站ZDJ(B系)", 40 + i, 0),
        ("二方向邻站FDJ(B系)", 40 + i, 2),
        ("二方向邻站ZXJ(B系)", 40 + i, 4),
        ("二方向邻站FXJ(B系)", 40 + i, 6),
    ]
    
    current_relay_status = {}

    for relay, byte_index, bit_index in relay_mapping:
        bit_value = get_switch_bit_value(switch_status, byte_index, bit_index)
        action = "吸起" if bit_value == 1 else "落下"
        current_relay_status[relay] = bit_value

        # 仅在继电器状态发生变化时记录动作
        if previous_relay_status.get(relay) != bit_value:
            actions.append({
                'relay': relay,
                'action': action,
                'timestamp': current_time
            })
    
    # 更新缓存中的继电器状态
    cache.set(f'device_{device_id}_relay_status', current_relay_status, timeout=None)
    
    if previous_relay_status:
        return actions
    else:
        return []