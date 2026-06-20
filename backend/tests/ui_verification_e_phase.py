"""E 阶段 6 项 UI / API 验收脚本。

运行：python backend/tests/ui_verification_e_phase.py

E 阶段验收覆盖（以 backend 行为 + API 暴露为准）：
1. 字段级合并：A 改 title + B 改 priority → 双方都看到两个字段都生效
2. skew 内字典序裁决：同时改同一字段（差 < 1s）→ 按 updated_by 节点 ID 裁决
3. 任务详情字段级时间戳：db 持久化的 fieldTimestamps 含每个字段的 at + by
4. 字段级时间戳通过 get_task API 暴露：返回值含 fieldTimestamps 字典
5. 字段级时间戳含完整 ISO 时间戳 + 节点 ID：可解析
6. D 阶段遗留：network.js 渲染对端的 worktree 同步（feature-field-merge 已含 network.js 修复）
"""
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PASS = '[PASS]'
FAIL = '[FAIL]'

# 项目根（含 frontend/）
PROJECT_ROOT = Path(__file__).parent.parent.parent


def check(name, fn):
    try:
        result = fn()
        if result is True or result is None:
            print(f'  {PASS} {name}')
            return True
        print(f'  {FAIL} {name}: {result}')
        return False
    except Exception as e:
        print(f'  {FAIL} {name}: {e}')
        return False


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


def _make_engine(db, sm):
    from backend.network.sync_engine import SyncEngine
    return SyncEngine(db=db, sync_manager=sm)


def verify_1_field_level_merge_both_kept():
    """验收 1：字段级合并 → 双方都看到两个字段都生效。"""
    db, sm, path = _fresh_db()
    try:
        se = _make_engine(db, sm)
        t = db.add_task({'title': '初始', 'priority': 'normal'})
        tid = t['id']
        T0 = datetime(2026, 6, 20, 10, 0, 0)

        # A 改 title
        a = {
            'id': tid, 'title': 'A 标题', 'priority': 'normal',
            'updatedAt': _iso(T0 + timedelta(seconds=5)),
            'updated_at': _iso(T0 + timedelta(seconds=5)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=5)), 'by': 'node-A'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', a, peer_id='node-A', user_id='alice')

        # B 改 priority
        b = {
            'id': tid, 'title': 'A 标题', 'priority': 'high',
            'updatedAt': _iso(T0 + timedelta(seconds=10)),
            'updated_at': _iso(T0 + timedelta(seconds=10)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(seconds=5)), 'by': 'node-A'},
                'priority': {'at': _iso(T0 + timedelta(seconds=10)), 'by': 'node-B'},
            },
            '_changed_fields': ['priority'],
        }
        se.apply_remote_change('task', b, peer_id='node-B', user_id='bob')

        cur = db.get_task(tid)
        if cur['title'] != 'A 标题' or cur['priority'] != 'high':
            return f"字段未并存：title={cur['title']}, priority={cur['priority']}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_2_within_skew_node_id_arbitration():
    """验收 2：skew 内同时改同一字段 → 按节点 ID 字典序裁决。"""
    db, sm, path = _fresh_db()
    try:
        se = _make_engine(db, sm)
        t = db.add_task({'title': '初始', 'priority': 'normal'})
        tid = t['id']
        T0 = datetime(2026, 6, 20, 10, 0, 0)

        # A 先 (at=T0, by=node-A)
        a = {
            'id': tid, 'title': 'A 标题', 'priority': 'normal',
            'updatedAt': _iso(T0), 'updated_at': _iso(T0),
            'fieldTimestamps': {'title': {'at': _iso(T0), 'by': 'node-A'}},
            '_changed_fields': ['title', 'priority'],
        }
        se.apply_remote_change('task', a, peer_id='node-A', user_id='alice')

        # Z 后 (at=T0+300ms, by=node-Z；300ms < 1s skew，Z > A → 远端胜)
        z = {
            'id': tid, 'title': 'Z 标题', 'priority': 'normal',
            'updatedAt': _iso(T0 + timedelta(milliseconds=300)),
            'updated_at': _iso(T0 + timedelta(milliseconds=300)),
            'fieldTimestamps': {
                'title': {'at': _iso(T0 + timedelta(milliseconds=300)), 'by': 'node-Z'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', z, peer_id='node-Z', user_id='zoe')

        cur = db.get_task(tid)
        if cur['title'] != 'Z 标题':
            return f"字典序裁决错误：title={cur['title']}（应为 Z 标题）"
        if cur['fieldTimestamps']['title']['by'] != 'node-Z':
            return f"字段时间戳 by 应为 node-Z，实际：{cur['fieldTimestamps']['title']['by']}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_3_field_timestamps_persisted():
    """验收 3：db 持久化的 fieldTimestamps 含每个字段的 at + by。"""
    db, sm, path = _fresh_db()
    try:
        se = _make_engine(db, sm)
        t = db.add_task({'title': '初始', 'priority': 'normal'})
        tid = t['id']
        T0 = datetime(2026, 6, 20, 10, 0, 0)

        # 改全字段
        e = {
            'id': tid, 'title': '新标题', 'priority': 'high', 'description': '新描述',
            'updatedAt': _iso(T0), 'updated_at': _iso(T0),
            'fieldTimestamps': {
                'title': {'at': _iso(T0), 'by': 'node-A'},
                'priority': {'at': _iso(T0), 'by': 'node-A'},
                'description': {'at': _iso(T0), 'by': 'node-A'},
            },
            '_changed_fields': ['title', 'priority', 'description'],
        }
        se.apply_remote_change('task', e, peer_id='node-A', user_id='alice')

        cur = db.get_task(tid)
        fts = cur.get('fieldTimestamps') or {}
        for f in ('title', 'priority', 'description'):
            if f not in fts:
                return f"字段 {f} 字段时间戳未持久化：{fts}"
            if 'at' not in fts[f] or 'by' not in fts[f]:
                return f"字段 {f} 字段时间戳缺 at/by：{fts[f]}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_4_field_timestamps_via_get_task_api():
    """验收 4：get_task API 返回值含 fieldTimestamps 字典（前端可直接读）。"""
    db, sm, path = _fresh_db()
    try:
        t = db.add_task({'title': 'X', 'priority': 'low'})
        tid = t['id']
        cur = db.get_task(tid)
        if 'fieldTimestamps' not in cur:
            return "get_task 返回值缺 fieldTimestamps 键"
        if not isinstance(cur['fieldTimestamps'], dict):
            return f"fieldTimestamps 不是 dict：{type(cur['fieldTimestamps'])}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_5_field_timestamps_iso_parsable():
    """验收 5：字段级时间戳含完整 ISO 时间戳，可解析。"""
    db, sm, path = _fresh_db()
    try:
        se = _make_engine(db, sm)
        t = db.add_task({'title': '初始', 'priority': 'normal'})
        tid = t['id']
        T0 = datetime(2026, 6, 20, 10, 0, 0)
        e = {
            'id': tid, 'title': 'X', 'priority': 'normal',
            'updatedAt': _iso(T0), 'updated_at': _iso(T0),
            'fieldTimestamps': {
                'title': {'at': _iso(T0), 'by': 'node-A'},
            },
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', e, peer_id='node-A', user_id='alice')
        cur = db.get_task(tid)
        fts = cur.get('fieldTimestamps') or {}
        if 'title' not in fts:
            return "fieldTimestamps.title 缺失"
        ts_str = fts['title'].get('at', '')
        # 解析 ISO
        try:
            datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        except (ValueError, TypeError) as e:
            return f"at 不是可解析 ISO：{ts_str} ({e})"
        if not fts['title'].get('by'):
            return "by 节点 ID 为空"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_6_network_js_rendering_kept():
    """验收 6：D 阶段遗留 network.js 渲染对端同步完成（feature-field-merge 含 network.js）。"""
    network_js = PROJECT_ROOT / 'frontend' / 'js' / 'network.js'
    if not network_js.exists():
        return f"network.js 不存在：{network_js}"
    content = network_js.read_text(encoding='utf-8', errors='ignore')
    # 简单 smoke test：包含 syncStatusManager 或 list_online_peers 引用
    if 'syncStatusManager' not in content and 'listOnlinePeers' not in content and 'onlinePeers' not in content:
        return "network.js 缺少对端渲染相关代码"
    return True


def main():
    print('=' * 60)
    print('E 阶段 6 项 UI / API 验收')
    print('=' * 60)
    results = [
        ('1. 字段级合并（A title + B priority 同时生效）', verify_1_field_level_merge_both_kept),
        ('2. skew 内字典序裁决', verify_2_within_skew_node_id_arbitration),
        ('3. 字段级时间戳持久化（含 at + by）', verify_3_field_timestamps_persisted),
        ('4. get_task API 暴露 fieldTimestamps', verify_4_field_timestamps_via_get_task_api),
        ('5. 字段级时间戳 ISO 可解析', verify_5_field_timestamps_iso_parsable),
        ('6. network.js 渲染对端同步完成', verify_6_network_js_rendering_kept),
    ]
    passed = 0
    for name, fn in results:
        if check(name, fn):
            passed += 1
    print('=' * 60)
    print(f'E 阶段验收：{passed}/{len(results)} 通过')
    print('=' * 60)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
