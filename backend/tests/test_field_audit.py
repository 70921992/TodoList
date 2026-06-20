"""E+2 阶段：字段级审计 + 贡献度。

覆盖：
1. 审计表 by_node 列迁移（旧库补全）
2. update_task 透传 byNode（sync 场景下审计记录远端节点）
3. add_task 透传 byNode
4. audit 缺 byNode 时为 NULL（本地写）
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _fresh_db():
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    from backend.database import operations
    operations.get_app_data_file = lambda: Path(tmp.name)
    from backend.database.operations import TodoDatabase
    db = TodoDatabase()
    return db, tmp.name


def _audit_rows(db, task_id):
    """直接读 task_audit_log 全部行（按 created_at 升序），返回 list[tuple]。"""
    with db.get_connection() as c:
        cur = c.cursor()
        cur.execute(
            'SELECT action, field, by_node FROM task_audit_log WHERE task_id = ? ORDER BY created_at ASC',
            (task_id,)
        )
        return [tuple(r) for r in cur.fetchall()]


def test_1_audit_table_has_by_node_column():
    """审计表迁移：by_node 列存在。"""
    db, path = _fresh_db()
    try:
        with db.get_connection() as c:
            cur = c.cursor()
            cur.execute("PRAGMA table_info(task_audit_log)")
            cols = [row[1] for row in cur.fetchall()]
        assert 'by_node' in cols, f"by_node 列缺失：{cols}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_2_local_update_writes_audit_without_by_node():
    """本地 update：审计 by_node 为 NULL（无 peer_id）。"""
    db, path = _fresh_db()
    try:
        db.add_task({'title': '原', 'currentUserId': 'alice'})
        db.set_current_user('alice')
        tasks = db.get_all_tasks()
        tid = tasks[0]['id']
        db.update_task(tid, {'title': '新', 'currentUserId': 'alice'})
        rows = _audit_rows(db, tid)
        # create + update(title)
        actions = [(r[0], r[1], r[2]) for r in rows]
        assert ('create', None, None) in actions, f"缺 create 审计：{actions}"
        update_rows = [r for r in rows if r[0] == 'update']
        assert len(update_rows) >= 1
        for r in update_rows:
            assert r[2] is None, f"本地写不应有 by_node：{r}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_3_local_update_with_by_node_writes_audit():
    """本地 update 显式传 byNode：审计 by_node 写入。"""
    db, path = _fresh_db()
    try:
        db.add_task({'title': '原', 'currentUserId': 'alice', 'byNode': 'node-local-1'})
        db.set_current_user('alice')
        tid = db.get_all_tasks()[0]['id']
        db.update_task(tid, {'title': '新', 'currentUserId': 'alice', 'byNode': 'node-local-1'})
        rows = _audit_rows(db, tid)
        # 所有审计行 by_node 应为 'node-local-1'
        for r in rows:
            assert r[2] == 'node-local-1', f"by_node 应为 node-local-1，实际：{r}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_4_sync_apply_writes_audit_with_peer_by_node():
    """sync 场景：A 端 apply B 广播 → 审计 by_node=B。"""
    db, path = _fresh_db()
    try:
        from backend.network.sync_engine import SyncEngine
        from backend.database.operations import SyncManager
        sm = SyncManager(db)
        se = SyncEngine(db=db, sync_manager=sm)
        t = db.add_task({'title': '原', 'priority': 'normal'})
        tid = t['id']
        entity = {
            'id': tid, 'title': '远端新', 'priority': 'normal',
            'updatedAt': '2026-06-20T10:00:00Z', 'updated_at': '2026-06-20T10:00:00Z',
            'fieldTimestamps': {
                'title': {'at': '2026-06-20T10:00:00Z', 'by': 'node-B'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', entity, peer_id='node-B', user_id='bob')
        rows = _audit_rows(db, tid)
        # update(title) 行的 by_node 应为 'node-B'
        update_title_rows = [r for r in rows if r[0] == 'update' and r[1] == 'title']
        assert len(update_title_rows) >= 1
        for r in update_title_rows:
            assert r[2] == 'node-B', f"sync 写 by_node 应为 node-B，实际：{r}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_5_sync_create_writes_audit_with_peer_by_node():
    """sync 场景：远端新增任务 → 审计 by_node=peer_id。"""
    db, path = _fresh_db()
    try:
        from backend.network.sync_engine import SyncEngine
        from backend.database.operations import SyncManager
        sm = SyncManager(db)
        se = SyncEngine(db=db, sync_manager=sm)
        entity = {
            'id': 'sync-task-1', 'title': '远端新建', 'priority': 'normal',
            'updatedAt': '2026-06-20T10:00:00Z', 'updated_at': '2026-06-20T10:00:00Z',
        }
        se.apply_remote_change('task', entity, peer_id='node-X', user_id='xavier')
        rows = _audit_rows(db, 'sync-task-1')
        assert len(rows) == 1
        assert rows[0] == ('create', None, 'node-X'), f"create 审计 by_node 应为 node-X：{rows[0]}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_6_field_level_audit_one_row_per_field():
    """字段级审计：一次 update 改 2 个字段 → 写 2 行 audit（每字段一行）。"""
    db, path = _fresh_db()
    try:
        db.add_task({'title': '原', 'priority': 'normal'})
        db.set_current_user('alice')
        tid = db.get_all_tasks()[0]['id']
        db.update_task(tid, {
            'title': '新标题',
            'priority': 'high',
            'currentUserId': 'alice',
            'byNode': 'node-1',
        })
        rows = _audit_rows(db, tid)
        update_rows = [r for r in rows if r[0] == 'update']
        # 至少 title + priority 两行
        fields_updated = [r[1] for r in update_rows]
        assert 'title' in fields_updated
        assert 'priority' in fields_updated
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == '__main__':
    test_1_audit_table_has_by_node_column()
    test_2_local_update_writes_audit_without_by_node()
    test_3_local_update_with_by_node_writes_audit()
    test_4_sync_apply_writes_audit_with_peer_by_node()
    test_5_sync_create_writes_audit_with_peer_by_node()
    test_6_field_level_audit_one_row_per_field()
    print('all field_audit tests passed')
