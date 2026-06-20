"""E 阶段 M1：字段级时间戳（schema + Task 模型 + update_task 改动检测）。"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.database.operations import TodoDatabase, _migrate_database


def _make_db():
    """新建临时 db + init 完整 schema。"""
    tmp = tempfile.NamedTemporaryFile(suffix='_fts.db', delete=False)
    tmp.close()
    from backend.database import operations
    operations.get_app_data_file = lambda: Path(tmp.name)
    db = TodoDatabase()
    return db, tmp.name


def test_1_migrate_adds_field_timestamps_column():
    """旧库（无 field_timestamps 列）→ 启动 init → 列自动加。"""
    with tempfile.NamedTemporaryFile(suffix='_mig.db', delete=False) as f:
        path = f.name
    try:
        # 模拟旧库：只创建 tasks 表（无 field_timestamps）
        conn = sqlite3.connect(path)
        conn.execute('''
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        conn.commit()
        _migrate_database(conn.cursor())
        conn.commit()

        cols = [r[1] for r in conn.execute('PRAGMA table_info(tasks)').fetchall()]
        assert 'field_timestamps' in cols, f"field_timestamps 列未自动加入：{cols}"
    finally:
        conn.close()
        Path(path).unlink(missing_ok=True)


def test_2_add_task_empty_field_timestamps():
    """新建任务 → field_timestamps = {}（空 dict）。"""
    db, path = _make_db()
    try:
        result = db.add_task({'title': '新任务', 'description': 'desc'})
        assert 'fieldTimestamps' in result
        assert result['fieldTimestamps'] == {}, f"期望空 dict，实际：{result['fieldTimestamps']}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_3_update_task_writes_field_timestamp():
    """更新 title（真改）→ fieldTimestamps.title = {at, by}，其他键不存在。"""
    db, path = _make_db()
    try:
        db.add_task({'title': '原标题', 'currentUserId': 'alice'})
        db.set_current_user('alice')
        result = db.update_task(
            result_id := db.get_all_tasks()[0]['id'],
            {'title': '新标题', 'currentUserId': 'alice'},
        )
        # 重新 get_task
        fresh = db.get_task(result_id)
        ft = fresh['fieldTimestamps']
        assert 'title' in ft, f"title 字段时间戳未写入：{ft}"
        assert ft['title']['by'] == 'alice'
        assert 'at' in ft['title']
        # 解析时间戳
        try:
            datetime.fromisoformat(ft['title']['at'])
        except (ValueError, TypeError) as e:
            raise AssertionError(f"at 不是 ISO 格式：{ft['title']['at']}")
        # 其他字段未在本次改动
        assert 'priority' not in ft
    finally:
        Path(path).unlink(missing_ok=True)


def test_4_update_task_preserves_other_field_timestamps():
    """改 title 不影响 priority 旧时间戳。"""
    db, path = _make_db()
    try:
        db.add_task({'title': 'A', 'priority': 'normal', 'currentUserId': 'alice'})
        tid = db.get_all_tasks()[0]['id']
        # 第一次：改 priority
        db.set_current_user('bob')
        db.update_task(tid, {'priority': 'high', 'currentUserId': 'bob'})
        # 第二次：改 title
        db.set_current_user('carol')
        db.update_task(tid, {'title': '新标题', 'currentUserId': 'carol'})

        fresh = db.get_task(tid)
        ft = fresh['fieldTimestamps']
        assert ft['priority']['by'] == 'bob', f"priority 旧时间戳被覆盖：{ft}"
        assert ft['title']['by'] == 'carol'
    finally:
        Path(path).unlink(missing_ok=True)


def test_5_update_task_no_change_keeps_field_timestamps_intact():
    """值未变 → 不写字段时间戳（保留旧值）。"""
    db, path = _make_db()
    try:
        db.add_task({'title': 'A', 'currentUserId': 'alice'})
        tid = db.get_all_tasks()[0]['id']
        # 第一次：改 title
        db.set_current_user('bob')
        db.update_task(tid, {'title': 'B', 'currentUserId': 'bob'})
        first_at = db.get_task(tid)['fieldTimestamps']['title']['at']

        # 第二次：传相同 title
        import time
        time.sleep(0.01)  # 确保时间不同
        db.set_current_user('carol')
        db.update_task(tid, {'title': 'B', 'currentUserId': 'carol'})
        second_at = db.get_task(tid)['fieldTimestamps']['title']['at']

        assert first_at == second_at, f"值未变但时间戳变了：{first_at} -> {second_at}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_6_update_task_multiple_fields_all_recorded():
    """同时改 title + priority → 两者都记录。"""
    db, path = _make_db()
    try:
        db.add_task({'title': 'A', 'priority': 'normal', 'currentUserId': 'alice'})
        tid = db.get_all_tasks()[0]['id']
        db.set_current_user('bob')
        db.update_task(tid, {'title': 'B', 'priority': 'high', 'currentUserId': 'bob'})

        ft = db.get_task(tid)['fieldTimestamps']
        assert ft['title']['by'] == 'bob'
        assert ft['priority']['by'] == 'bob'
    finally:
        Path(path).unlink(missing_ok=True)


def test_7_corrupted_field_timestamps_falls_back_to_empty():
    """损坏 JSON（DB 中被外部改坏）→ 读取时兜底为 {}。"""
    db, path = _make_db()
    try:
        db.add_task({'title': 'A', 'currentUserId': 'alice'})
        tid = db.get_all_tasks()[0]['id']
        # 手动改坏 field_timestamps
        conn = sqlite3.connect(path)
        conn.execute("UPDATE tasks SET field_timestamps = ? WHERE id = ?", ('not-valid-json{', tid))
        conn.commit()
        conn.close()

        # 重新读取应不抛错
        fresh = db.get_task(tid)
        assert fresh['fieldTimestamps'] == {}, f"损坏 JSON 未兜底：{fresh['fieldTimestamps']}"

        # update_task 应能继续工作（从 {} 重新开始）
        db.set_current_user('bob')
        db.update_task(tid, {'title': 'B', 'currentUserId': 'bob'})
        ft = db.get_task(tid)['fieldTimestamps']
        assert ft['title']['by'] == 'bob'
    finally:
        Path(path).unlink(missing_ok=True)


def test_8_task_model_default_and_roundtrip():
    """Task 模型：默认 field_timestamps={}，to_dict / from_dict 往返。"""
    from backend.database.models import Task

    t1 = Task(title='X', priority='high')
    assert t1.field_timestamps == {}
    d = t1.to_dict()
    assert d['fieldTimestamps'] == {}

    # from_dict 还原
    d['fieldTimestamps'] = {'title': {'at': '2026-06-20T10:00:00', 'by': 'alice'}}
    t2 = Task.from_dict(d)
    assert t2.field_timestamps == {'title': {'at': '2026-06-20T10:00:00', 'by': 'alice'}}
    # to_dict 再次输出
    assert t2.to_dict()['fieldTimestamps'] == d['fieldTimestamps']


if __name__ == '__main__':
    test_1_migrate_adds_field_timestamps_column()
    print('test 1 PASS')
    test_2_add_task_empty_field_timestamps()
    print('test 2 PASS')
    test_3_update_task_writes_field_timestamp()
    print('test 3 PASS')
    test_4_update_task_preserves_other_field_timestamps()
    print('test 4 PASS')
    test_5_update_task_no_change_keeps_field_timestamps_intact()
    print('test 5 PASS')
    test_6_update_task_multiple_fields_all_recorded()
    print('test 6 PASS')
    test_7_corrupted_field_timestamps_falls_back_to_empty()
    print('test 7 PASS')
    test_8_task_model_default_and_roundtrip()
    print('test 8 PASS')
    print('\nALL PASSED')
