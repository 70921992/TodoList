"""
UserManager 测试（Task 4-7）
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.database.operations import TodoDatabase, UserManager


def _fresh_db():
    """返回新 TodoDatabase 实例 + 临时 db path"""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    from backend.database import operations
    operations.get_app_data_file = lambda: Path(tmp.name)
    db = TodoDatabase()
    return db, tmp.name


def test_user_manager_create():
    db, path = _fresh_db()
    try:
        um = UserManager(db)
        u = um.create_user(display_name='郭世锋', unit='某公司', department='研发部')
        assert u.display_name == '郭世锋'
        assert u.id is not None
        assert u.unit == '某公司'
        assert u.department == '研发部'
    finally:
        Path(path).unlink(missing_ok=True)


def test_user_manager_duplicate_triple_rejected():
    db, path = _fresh_db()
    try:
        um = UserManager(db)
        um.create_user(display_name='郭世锋', unit='某公司', department='研发部')
        try:
            um.create_user(display_name='郭世锋', unit='某公司', department='研发部')
            assert False, '应该抛错'
        except ValueError as e:
            assert '已存在' in str(e) or 'DUPLICATE' in str(e).upper()
    finally:
        Path(path).unlink(missing_ok=True)


def test_user_manager_same_name_different_unit_ok():
    """同 display_name 但不同 unit+department 应可共存"""
    db, path = _fresh_db()
    try:
        um = UserManager(db)
        u1 = um.create_user(display_name='郭世锋', unit='A公司', department='研发部')
        u2 = um.create_user(display_name='郭世锋', unit='B公司', department='研发部')
        assert u1.id != u2.id
    finally:
        Path(path).unlink(missing_ok=True)


def test_user_manager_create_with_optional_fields():
    """可选字段 role/avatar_color 应被保存"""
    db, path = _fresh_db()
    try:
        um = UserManager(db)
        u = um.create_user(
            display_name='李明', role='产品经理', avatar_color='#ff00ff'
        )
        assert u.role == '产品经理'
        assert u.avatar_color == '#ff00ff'
    finally:
        Path(path).unlink(missing_ok=True)
