"""E+2 阶段 6 项 UI/API 验收脚本。

运行：python -m backend.tests.ui_verification_e_plus_2

E+2 验收覆盖：
1. 字段级审计：本地 update_task 改 title → audit 表新增 1 行（field=title, by_node=本机 node_id）
2. 字段级审计：sync 场景下 A 端 apply B 广播 → audit 表新增 1 行（field=title, by_node=B）
3. task_get_field_history 返回每个字段的最后修改者
4. task_get_field_history 返回每个字段的最近 N 条历史
5. task_get_field_contribution 按 user 聚合字段改动数
6. 前端：taskCollaboration.js 暴露 renderFieldBadges + renderContributionPanel + task_field_badges 容器 + 贡献度容器
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

PASS = '[PASS]'
FAIL = '[FAIL]'

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
    from backend.api.todo_api import TodoApi
    db = TodoDatabase()
    sm = SyncManager(db)
    api = TodoApi(db, sm)
    return db, api, tmp.name


def verify_1_local_update_writes_audit_with_by_node():
    """验收 1：本地 update 改 title → audit 表新增 1 行（by_node=本机 node_id）。"""
    db, api, path = _fresh_db()
    try:
        t = db.add_task({'title': '原', 'currentUserId': 'alice'})
        tid = t['id']
        db.set_current_user('alice')
        db.update_task(tid, {'title': '新', 'currentUserId': 'alice', 'byNode': 'node-local-1'})
        with db.get_connection() as c:
            cur = c.cursor()
            cur.execute(
                "SELECT action, field, by_node FROM task_audit_log WHERE task_id = ? AND action = 'update' AND field = 'title'",
                (tid,)
            )
            rows = [tuple(r) for r in cur.fetchall()]
        if len(rows) != 1:
            return f"期望 1 行 update 审计，实际 {len(rows)}"
        if rows[0] != ('update', 'title', 'node-local-1'):
            return f"by_node 不匹配：{rows[0]}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_2_sync_apply_writes_audit_with_peer_by_node():
    """验收 2：sync 场景下 A 端 apply B 广播 → audit 表新增 1 行（by_node=B）。"""
    db, api, path = _fresh_db()
    try:
        from backend.network.sync_engine import SyncEngine
        se = SyncEngine(db=db, sync_manager=__import__('backend.database.operations', fromlist=['SyncManager']).SyncManager(db))
        t = db.add_task({'title': '原', 'priority': 'normal'})
        tid = t['id']
        entity = {
            'id': tid, 'title': '远端新', 'priority': 'normal',
            'updatedAt': '2026-06-20T10:00:00Z', 'updated_at': '2026-06-20T10:00:00Z',
            'fieldTimestamps': {'title': {'at': '2026-06-20T10:00:00Z', 'by': 'node-B'}},
            '_changed_fields': ['title'],
        }
        se.apply_remote_change('task', entity, peer_id='node-B', user_id='bob')
        with db.get_connection() as c:
            cur = c.cursor()
            cur.execute(
                "SELECT action, field, by_node, user_id FROM task_audit_log WHERE task_id = ? AND action = 'update' AND field = 'title'",
                (tid,)
            )
            rows = [tuple(r) for r in cur.fetchall()]
        if len(rows) != 1:
            return f"期望 1 行 update 审计，实际 {len(rows)}"
        # user_id 应是真实操作者（bob），by_node 应是节点（node-B）
        if rows[0] != ('update', 'title', 'node-B', 'bob'):
            return f"sync 审计字段不匹配：{rows[0]}（期望 user_id=bob, by_node=node-B）"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_3_field_history_returns_last_by_per_field():
    """验收 3：task_get_field_history 返回每个字段的最后修改者。"""
    db, api, path = _fresh_db()
    try:
        t = db.add_task({'title': 'v1', 'priority': 'low', 'currentUserId': 'alice'})
        tid = t['id']
        db.set_current_user('alice')
        db.update_task(tid, {'title': 'v2', 'currentUserId': 'bob', 'byNode': 'node-B'})
        result = api.task_get_field_history(tid)
        if not result.get('success'):
            return f"API 失败：{result}"
        fields = result.get('fields', {})
        for f in ('title', 'priority'):
            if f not in fields:
                return f"字段 {f} 缺历史"
            last = fields[f].get('lastBy')
            if not last or last.get('userId') != 'bob':
                return f"字段 {f} 最后修改者错误：{last}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_4_field_history_returns_per_field_history_list():
    """验收 4：task_get_field_history 返回每个字段的最近 N 条历史。"""
    db, api, path = _fresh_db()
    try:
        t = db.add_task({'title': 'v0', 'currentUserId': 'alice'})
        tid = t['id']
        db.set_current_user('alice')
        for i in range(1, 6):
            db.update_task(tid, {'title': f'v{i}', 'currentUserId': 'alice'})
        result = api.task_get_field_history(tid, history_per_field=3)
        if not result.get('success'):
            return f"API 失败：{result}"
        history = result.get('fields', {}).get('title', {}).get('history', [])
        if len(history) != 3:
            return f"history 应为 3 条，实际 {len(history)}"
        # 最近一条应是 v5
        if history[-1].get('newValue') != 'v5':
            return f"最近一条 newValue 应为 v5，实际 {history[-1].get('newValue')}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_5_field_contribution_aggregates_per_user():
    """验收 5：task_get_field_contribution 按 user 聚合字段改动数。"""
    db, api, path = _fresh_db()
    try:
        t = db.add_task({'title': 'v0', 'priority': 'low', 'currentUserId': 'alice'})
        tid = t['id']
        db.set_current_user('alice')
        db.update_task(tid, {'title': 'v1', 'currentUserId': 'alice', 'byNode': 'node-A'})
        db.update_task(tid, {'priority': 'high', 'currentUserId': 'alice', 'byNode': 'node-A'})
        db.update_task(tid, {'title': 'v2', 'currentUserId': 'bob', 'byNode': 'node-B'})
        result = api.task_get_field_contribution(tid)
        if not result.get('success'):
            return f"API 失败：{result}"
        users = result.get('users', [])
        # alice 改 2 个字段
        alice_row = next((u for u in users if u['userId'] == 'alice' and u['nodeId'] == 'node-A'), None)
        if not alice_row or alice_row.get('fieldChangeCount') != 2:
            return f"alice 贡献度不对：{alice_row}"
        # bob 改 1 个字段
        bob_row = next((u for u in users if u['userId'] == 'bob' and u['nodeId'] == 'node-B'), None)
        if not bob_row or bob_row.get('fieldChangeCount') != 1:
            return f"bob 贡献度不对：{bob_row}"
        return True
    finally:
        Path(path).unlink(missing_ok=True)


def verify_6_frontend_renders_field_badges_and_contribution():
    """验收 6：前端 taskCollaboration.js 暴露字段徽章/贡献度渲染函数 + 容器。"""
    # 6.1 taskCollaboration.js 暴露 renderFieldBadges + renderContributionPanel
    js = (PROJECT_ROOT / 'frontend' / 'js' / 'taskCollaboration.js').read_text(encoding='utf-8', errors='ignore')
    if 'function renderFieldBadges' not in js:
        return "taskCollaboration.js 缺 renderFieldBadges"
    if 'function renderContributionPanel' not in js:
        return "taskCollaboration.js 缺 renderContributionPanel"
    # 6.2 容器 #task-field-badges + #task-contribution 存在
    html = (PROJECT_ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8', errors='ignore')
    if 'id="task-field-badges"' not in html:
        return "index.html 缺 #task-field-badges 容器"
    if 'id="task-contribution"' not in html:
        return "index.html 缺 #task-contribution 容器"
    # 6.3 CSS 样式存在
    css = (PROJECT_ROOT / 'frontend' / 'css' / 'components.css').read_text(encoding='utf-8', errors='ignore')
    if '.field-badge' not in css:
        return "components.css 缺 .field-badge 样式"
    if '.contribution-panel' not in css:
        return "components.css 缺 .contribution-panel 样式"
    # 6.4 api.js 注册 getFieldHistory + getFieldContribution
    api_js = (PROJECT_ROOT / 'frontend' / 'js' / 'api.js').read_text(encoding='utf-8', errors='ignore')
    if 'getFieldHistory' not in api_js:
        return "api.js 缺 getFieldHistory 注册"
    if 'getFieldContribution' not in api_js:
        return "api.js 缺 getFieldContribution 注册"
    return True


def main():
    print('=' * 60)
    print('E+2 阶段 6 项 UI/API 验收')
    print('=' * 60)
    results = [
        ('1. 本地 update 写审计 by_node=本机 node', verify_1_local_update_writes_audit_with_by_node),
        ('2. sync 写审计 by_node=远端节点', verify_2_sync_apply_writes_audit_with_peer_by_node),
        ('3. task_get_field_history 返回每字段 lastBy', verify_3_field_history_returns_last_by_per_field),
        ('4. task_get_field_history 返回 history 列表', verify_4_field_history_returns_per_field_history_list),
        ('5. task_get_field_contribution 按 user 聚合', verify_5_field_contribution_aggregates_per_user),
        ('6. 前端字段徽章 + 贡献度面板渲染', verify_6_frontend_renders_field_badges_and_contribution),
    ]
    passed = 0
    for name, fn in results:
        if check(name, fn):
            passed += 1
    print('=' * 60)
    print(f'E+2 阶段验收：{passed}/{len(results)} 通过')
    print('=' * 60)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
