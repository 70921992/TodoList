"""E 阶段 M4：字段级合并端到端 4 场景。

通过 SyncEngine.apply_remote_change 模拟"B 端 apply A 端广播"，验证：
1. A 改 title + B 改 priority → 字段级合并，两者并存
2. A、B 同时改 title（差 < 1s）→ 节点 ID 字典序裁决
3. A 改 title + B 改 title（差 > 1s）→ 较新者胜
4. A 改全字段 + B 改全字段 → 退化为实体级 LWW（远端整体胜）
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _fresh_db():
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    from backend.database import operations
    operations.get_app_data_file = lambda: Path(tmp.name)
    from backend.database.operations import TodoDatabase, SyncManager
    db = TodoDatabase()
    return db, SyncManager(db), tmp.name


def _iso(dt):
    return dt.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')


T0 = datetime(2026, 6, 20, 10, 0, 0)


def test_e1_a_title_b_priority_both_kept():
    """场景 1：A 改 title，B 改 priority → 字段级合并，两者并存。"""
    db, sm, path = _fresh_db()
    try:
        from backend.network.sync_engine import SyncEngine
        se = SyncEngine(db=db, sync_manager=sm)
        t = db.add_task({'title': '初始', 'priority': 'normal'})
        tid = t['id']

        # 模拟：A 端改 title（带字段时间戳）
        a_change = {
            'id': tid,
            'title': 'A 的新标题',
            'priority': 'normal',  # A 没动
            'updatedAt': _iso(T0 + timedelta(seconds=5)),
            'updated_at': _iso(T0 + timedelta(seconds=5)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=5)), 'by': 'node-A'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', a_change, peer_id='node-A', user_id='alice')
        cur = db.get_task(tid)
        assert cur['title'] == 'A 的新标题'
        assert cur['priority'] == 'normal'

        # 模拟：B 端改 priority 后广播到 A
        b_change = {
            'id': tid,
            'title': 'A 的新标题',  # B 收到 A 后的最新本地值
            'priority': 'high',
            'updatedAt': _iso(T0 + timedelta(seconds=10)),
            'updated_at': _iso(T0 + timedelta(seconds=10)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=5)), 'by': 'node-A'},
                'priority': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
            },
            '_changed_fields': ['priority'],
        }
        se.apply_remote_change('task', b_change, peer_id='node-B', user_id='bob')
        cur = db.get_task(tid)
        assert cur['title'] == 'A 的新标题', f"title 应为 A 的版本，实际：{cur['title']}"
        assert cur['priority'] == 'high', f"priority 应为 B 的版本，实际：{cur['priority']}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_e2_concurrent_title_within_skew_uses_node_id():
    """场景 2：A、B 同时改 title（差 < 1s）→ 节点 ID 字典序。

    字典序：'node-Z' > 'node-A'，skew 内按字典序裁决。
    """
    db, sm, path = _fresh_db()
    try:
        from backend.network.sync_engine import SyncEngine
        se = SyncEngine(db=db, sync_manager=sm)
        t = db.add_task({'title': '初始', 'priority': 'normal'})
        tid = t['id']

        # A 先 broadcast（at=T0, by=node-A）→ 本机 apply 后 local_ts.title={at:T0, by:node-A}
        se.apply_remote_change('task', {
            'id': tid, 'title': 'A 标题', 'priority': 'normal',
            'updatedAt': _iso(T0), 'updated_at': _iso(T0),
            'fieldTimestamps': {
                'title': {'at': _iso(T0), 'by': 'node-A'},
            },
            '_changed_fields': ['title', 'priority'],
        }, peer_id='node-A', user_id='alice')
        assert db.get_task(tid)['title'] == 'A 标题'

        # Z 后 broadcast（at=T0+300ms, by=node-Z；300ms < 1s skew）
        # 字典序：'node-Z' > 'node-A' → 远端胜 → title 变成 'Z 标题'
        z_change = {
            'id': tid, 'title': 'Z 标题', 'priority': 'normal',
            'updatedAt': _iso(T0 + timedelta(milliseconds=300)),
            'updated_at': _iso(T0 + timedelta(milliseconds=300)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(milliseconds=300)), 'by': 'node-Z'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', z_change, peer_id='node-Z', user_id='zoe')
        cur = db.get_task(tid)
        assert cur['title'] == 'Z 标题', f"字典序 Z>A 应取 Z，实际：{cur['title']}"
        assert cur['fieldTimestamps']['title']['by'] == 'node-Z'

        # 反向：A 再 broadcast（at=T0+200ms, by=node-A；本机现在 by=node-Z）
        # 字典序：'node-A' < 'node-Z' → 本机胜 → title 保留 'Z 标题'
        a_change = {
            'id': tid, 'title': 'A 标题（再来一次）', 'priority': 'normal',
            'updatedAt': _iso(T0 + timedelta(milliseconds=200)),
            'updated_at': _iso(T0 + timedelta(milliseconds=200)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(milliseconds=200)), 'by': 'node-A'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', a_change, peer_id='node-A', user_id='alice')
        cur = db.get_task(tid)
        assert cur['title'] == 'Z 标题', (
            f"字典序 A<Z 应保留本地 Z 标题，实际：{cur['title']}"
        )
    finally:
        Path(path).unlink(missing_ok=True)


def test_e3_concurrent_title_outside_skew_takes_newer():
    """场景 3：A 改 title + B 改 title（差 > 1s）→ 较新者胜。"""
    db, sm, path = _fresh_db()
    try:
        from backend.network.sync_engine import SyncEngine
        se = SyncEngine(db=db, sync_manager=sm)
        t = db.add_task({'title': '初始', 'priority': 'normal'})
        tid = t['id']

        a_change = {
            'id': tid, 'title': 'A 标题', 'priority': 'normal',
            'updatedAt': _iso(T0 + timedelta(seconds=5)),
            'updated_at': _iso(T0 + timedelta(seconds=5)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=5)), 'by': 'node-A'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', a_change, peer_id='node-A', user_id='alice')
        assert db.get_task(tid)['title'] == 'A 标题'

        b_change = {
            'id': tid, 'title': 'B 标题', 'priority': 'normal',
            'updatedAt': _iso(T0 + timedelta(seconds=15)),
            'updated_at': _iso(T0 + timedelta(seconds=15)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=15)), 'by': 'node-B'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', b_change, peer_id='node-B', user_id='bob')
        cur = db.get_task(tid)
        assert cur['title'] == 'B 标题', f"较新者应胜出（B），实际：{cur['title']}"
        assert cur['fieldTimestamps']['title']['by'] == 'node-B'
    finally:
        Path(path).unlink(missing_ok=True)


def test_e4_full_entity_overwrite_degrades_to_entity_lww():
    """场景 4：A 改全字段 + B 改全字段 → 退化为实体级 LWW（远端整体胜）。"""
    db, sm, path = _fresh_db()
    try:
        from backend.network.sync_engine import SyncEngine
        se = SyncEngine(db=db, sync_manager=sm)
        t = db.add_task({'title': '初始', 'priority': 'normal', 'description': '初始描述'})
        tid = t['id']

        a_change = {
            'id': tid,
            'title': 'A 标题', 'priority': 'high', 'description': 'A 描述',
            'updatedAt': _iso(T0 + timedelta(seconds=20)),
            'updated_at': _iso(T0 + timedelta(seconds=20)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=20)), 'by': 'node-A'},
                'priority': {'at': _iso(T0 + timedelta(seconds=20)), 'by': 'node-A'},
                'description': {'at': _iso(T0 + timedelta(seconds=20)), 'by': 'node-A'},
            },
            '_changed_fields': ['title', 'priority', 'description'],
        }
        se.apply_remote_change('task', a_change, peer_id='node-A', user_id='alice')
        cur = db.get_task(tid)
        assert cur['title'] == 'A 标题'
        assert cur['priority'] == 'high'
        assert cur['description'] == 'A 描述'

        b_change = {
            'id': tid,
            'title': 'B 标题', 'priority': 'low', 'description': 'B 描述',
            'updatedAt': _iso(T0 + timedelta(seconds=30)),
            'updated_at': _iso(T0 + timedelta(seconds=30)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=30)), 'by': 'node-B'},
                'priority': {'at': _iso(T0 + timedelta(seconds=30)), 'by': 'node-B'},
                'description': {'at': _iso(T0 + timedelta(seconds=30)), 'by': 'node-B'},
            },
            '_changed_fields': ['title', 'priority', 'description'],
        }
        se.apply_remote_change('task', b_change, peer_id='node-B', user_id='bob')
        cur = db.get_task(tid)
        assert cur['title'] == 'B 标题'
        assert cur['priority'] == 'low'
        assert cur['description'] == 'B 描述'
        for f in ('title', 'priority', 'description'):
            assert cur['fieldTimestamps'][f]['by'] == 'node-B', (
                f"{f} 字段级时间戳应为 B，实际：{cur['fieldTimestamps'][f]}"
            )
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == '__main__':
    test_e1_a_title_b_priority_both_kept()
    test_e2_concurrent_title_within_skew_uses_node_id()
    test_e3_concurrent_title_outside_skew_takes_newer()
    test_e4_full_entity_overwrite_degrades_to_entity_lww()
    print('all field_merge_e2e tests passed')
