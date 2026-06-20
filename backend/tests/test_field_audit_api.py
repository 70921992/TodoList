"""E+2 阶段：API 测试（task_get_field_history / task_get_field_contribution）。

直接构造 db + TodoApi 验证返回结构。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _setup_db_and_api():
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    from backend.database import operations
    operations.get_app_data_file = lambda: Path(tmp.name)
    from backend.database.operations import TodoDatabase, SyncManager
    from backend.api.todo_api import TodoApi
    db = TodoDatabase()
    sm = SyncManager(db)
    api = TodoApi(db, sm)
    return db, api, tmp.name


def test_1_field_history_groups_by_field():
    """task_get_field_history 按字段分组返回最后修改者 + 历史。"""
    db, api, path = _setup_db_and_api()
    try:
        t = db.add_task({'title': 'v1', 'priority': 'low', 'currentUserId': 'alice'})
        tid = t['id']
        db.set_current_user('alice')
        db.update_task(tid, {'title': 'v2', 'currentUserId': 'alice', 'byNode': 'node-A'})
        import time as _t
        _t.sleep(0.01)
        db.update_task(tid, {'title': 'v3', 'priority': 'high', 'currentUserId': 'bob', 'byNode': 'node-B'})

        result = api.task_get_field_history(tid)
        assert result['success']
        fields = result['fields']
        assert 'title' in fields
        title_data = fields['title']
        assert len(title_data['history']) == 2
        assert title_data['lastBy']['userId'] == 'bob'
        assert title_data['lastBy']['nodeId'] == 'node-B'
        assert 'priority' in fields
        assert len(fields['priority']['history']) == 1
        assert fields['priority']['lastBy']['userId'] == 'bob'
    finally:
        Path(path).unlink(missing_ok=True)


def test_2_field_history_truncates_to_history_per_field():
    """history_per_field 限制：超过限制的旧历史被截断。"""
    db, api, path = _setup_db_and_api()
    try:
        t = db.add_task({'title': 'v0', 'currentUserId': 'alice'})
        tid = t['id']
        db.set_current_user('alice')
        for i in range(1, 6):
            db.update_task(tid, {'title': f'v{i}', 'currentUserId': 'alice'})
        result = api.task_get_field_history(tid, history_per_field=3)
        assert result['success']
        title_history = result['fields']['title']['history']
        assert len(title_history) == 3
        assert title_history[-1]['newValue'] == 'v5'
    finally:
        Path(path).unlink(missing_ok=True)


def test_3_field_contribution_aggregates_per_user():
    """task_get_field_contribution 按 user 聚合字段改动数。"""
    db, api, path = _setup_db_and_api()
    try:
        t = db.add_task({'title': 'v0', 'priority': 'low', 'currentUserId': 'alice'})
        tid = t['id']
        db.set_current_user('alice')
        db.update_task(tid, {'title': 'v1', 'currentUserId': 'alice', 'byNode': 'node-A'})
        db.update_task(tid, {'priority': 'high', 'currentUserId': 'alice', 'byNode': 'node-A'})
        db.update_task(tid, {'title': 'v2', 'currentUserId': 'bob', 'byNode': 'node-B'})

        result = api.task_get_field_contribution(tid)
        assert result['success']
        users = result['users']
        user_keys = {(u['userId'], u['nodeId']) for u in users}
        assert ('alice', 'node-A') in user_keys
        assert ('bob', 'node-B') in user_keys
        alice_row = next(u for u in users if u['userId'] == 'alice' and u['nodeId'] == 'node-A')
        assert alice_row['fieldChangeCount'] == 2
        bob_row = next(u for u in users if u['userId'] == 'bob' and u['nodeId'] == 'node-B')
        assert bob_row['fieldChangeCount'] == 1
    finally:
        Path(path).unlink(missing_ok=True)


def test_4_field_history_handles_unknown_user():
    """字段历史：user_id 已被删除时 userName 兜底为"已删除用户"。"""
    db, api, path = _setup_db_and_api()
    try:
        t = db.add_task({'title': 'v0', 'currentUserId': 'ghost'})
        tid = t['id']
        db.set_current_user('ghost')
        db.update_task(tid, {'title': 'v1', 'currentUserId': 'ghost'})
        result = api.task_get_field_history(tid)
        assert result['success']
        title = result['fields']['title']
        assert title['lastBy']['userId'] == 'ghost'
        assert title['lastBy']['userName'] == '已删除用户'
    finally:
        Path(path).unlink(missing_ok=True)


def test_5_field_history_empty_for_no_updates():
    """从未 update 的任务：fields 为空 dict。"""
    db, api, path = _setup_db_and_api()
    try:
        t = db.add_task({'title': 'only create', 'currentUserId': 'alice'})
        tid = t['id']
        result = api.task_get_field_history(tid)
        assert result['success']
        assert result['fields'] == {}
    finally:
        Path(path).unlink(missing_ok=True)


def test_6_field_contribution_empty_for_no_updates():
    """从未 update 的任务：users 为空列表。"""
    db, api, path = _setup_db_and_api()
    try:
        t = db.add_task({'title': 'only create', 'currentUserId': 'alice'})
        tid = t['id']
        result = api.task_get_field_contribution(tid)
        assert result['success']
        assert result['users'] == []
    finally:
        Path(path).unlink(missing_ok=True)


def test_7_field_history_records_node_id():
    """字段历史：lastBy.nodeId 反映真实远端节点（sync 场景）。"""
    db, api, path = _setup_db_and_api()
    try:
        from backend.network.sync_engine import SyncEngine
        se = SyncEngine(db=db, sync_manager=__import__('backend.database.operations', fromlist=['SyncManager']).SyncManager(db))
        t = db.add_task({'title': 'init', 'priority': 'normal'})
        tid = t['id']
        entity = {
            'id': tid, 'title': 'B 改的', 'priority': 'normal',
            'updatedAt': '2026-06-20T10:00:00Z', 'updated_at': '2026-06-20T10:00:00Z',
            'fieldTimestamps': {'title': {'at': '2026-06-20T10:00:00Z', 'by': 'node-B'}},
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', entity, peer_id='node-B', user_id='bob')

        result = api.task_get_field_history(tid)
        assert result['success']
        title = result['fields']['title']
        assert title['lastBy']['userId'] == 'bob'
        assert title['lastBy']['nodeId'] == 'node-B'
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == '__main__':
    test_1_field_history_groups_by_field()
    test_2_field_history_truncates_to_history_per_field()
    test_3_field_contribution_aggregates_per_user()
    test_4_field_history_handles_unknown_user()
    test_5_field_history_empty_for_no_updates()
    test_6_field_contribution_empty_for_no_updates()
    test_7_field_history_records_node_id()
    print('all field_audit_api tests passed')
