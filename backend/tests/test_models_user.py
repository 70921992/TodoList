"""
User 相关数据模型测试
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.database.models import User


def test_user_to_dict():
    u = User(
        id='u-1', display_name='郭世锋', unit='某公司',
        department='研发部', role='工程师', avatar_color='#ff0000'
    )
    d = u.to_dict()
    assert d['id'] == 'u-1'
    assert d['displayName'] == '郭世锋'
    assert d['unit'] == '某公司'
    assert d['department'] == '研发部'
    assert d['role'] == '工程师'
    assert d['avatarColor'] == '#ff0000'
    assert d['isDeleted'] is False


def test_user_from_dict():
    data = {
        'id': 'u-2', 'displayName': '李明', 'unit': '某公司',
        'department': '产品部', 'role': 'PM', 'avatarColor': '#00ff00',
        'isDeleted': True
    }
    u = User.from_dict(data)
    assert u.id == 'u-2'
    assert u.display_name == '李明'
    assert u.unit == '某公司'
    assert u.department == '产品部'
    assert u.role == 'PM'
    assert u.avatar_color == '#00ff00'
    assert u.is_deleted is True


def test_user_default_avatar_color():
    u = User(display_name='测试')
    assert u.avatar_color == '#4f46e5'


def test_user_from_dict_preserves_timestamps():
    """from_dict 必须正确反序列化 createdAt / lastActiveAt，否则时间会被覆盖"""
    data = {
        'id': 'u-3',
        'displayName': '时间测试',
        'createdAt': '2024-01-15T10:30:00',
        'lastActiveAt': '2025-06-01T08:00:00',
    }
    u = User.from_dict(data)
    assert u.created_at is not None
    assert u.created_at.year == 2024
    assert u.created_at.month == 1
    assert u.created_at.day == 15
    assert u.last_active_at is not None
    assert u.last_active_at.year == 2025
    assert u.last_active_at.month == 6


def test_user_roundtrip_preserves_timestamps():
    """to_dict → from_dict 往返必须保留 createdAt / lastActiveAt"""
    original = User(
        id='u-4', display_name='往返测试',
        created_at=datetime(2023, 5, 20, 12, 0, 0),
        last_active_at=datetime(2024, 12, 31, 23, 59, 59),
    )
    restored = User.from_dict(original.to_dict())
    assert restored.created_at == original.created_at
    assert restored.last_active_at == original.last_active_at


def test_user_auto_generates_id_and_created_at():
    """id / created_at 默认值"""
    u = User(display_name='默认')
    assert u.id is not None
    assert len(u.id) >= 32  # UUID
    assert u.created_at is not None
    assert isinstance(u.created_at, datetime)


def test_user_from_empty_dict():
    """空字典应不抛异常，落到默认值"""
    u = User.from_dict({})
    assert u.id is None or isinstance(u.id, str)
    assert u.display_name == ''
    assert u.unit is None
    assert u.avatar_color == '#4f46e5'
    assert u.is_deleted is False
