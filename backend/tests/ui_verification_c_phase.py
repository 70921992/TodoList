"""
C 阶段 19 项 UI 验证脚本
运行：python backend/tests/ui_verification_c_phase.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_api():
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    from backend.database import operations
    operations.get_app_data_file = lambda: Path(tmp.name)

    from backend.database.operations import TodoDatabase, UserManager
    from backend.api import todo_api

    db = TodoDatabase()
    um = UserManager(db)
    api = todo_api.TodoApi.__new__(todo_api.TodoApi)
    api.db = db
    api.user_manager = um
    api.category_manager = None
    api.is_android = False
    api.group_manager = None
    api.message_manager = None
    api.sync_manager = None
    api.network_engine = None
    api._connected_peers = []
    return api, tmp.name


PASS = '✓'
FAIL = '✗'


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


def main():
    print('\n=== C 阶段 19 项验收 ===\n')
    api, db_path = _make_api()
    total = 0
    passed = 0

    def tally(r):
        nonlocal total, passed
        total += 1
        if r:
            passed += 1

    # 1. 创建协作组 → 显示 6 位连接码
    def t1():
        r = api.auth_create_user(display_name='owner')
        assert r['success']
        r2 = api.group_create(name='研发组')
        assert r2['success']
        code = r2['group']['joinCode']
        assert len(code) == 7 and code[3] == '-'
        return True
    tally(check('1. 创建协作组自动生成 6 位连接码', t1))

    # 2. 重置连接码 → 旧码失效
    def t2():
        old = api.group_list()['groups'][0]['joinCode']
        gid = api.group_list()['groups'][0]['id']
        r = api.group_reset_code(gid)
        assert r['success'] and r['joinCode'] != old
        return True
    tally(check('2. 重置连接码（旧码失效）', t2))

    # 3. 第二台机器输入连接码 → 加入
    def t3():
        gid = api.group_list()['groups'][0]['id']
        new_code = api.group_list()['groups'][0]['joinCode']
        api.auth_logout()
        api.auth_create_user(display_name='newbie')
        rj = api.group_join(join_code=new_code)
        assert rj['success'] and rj['group']['id'] == gid
        return True
    tally(check('3. 输入连接码加入', t3))

    # 4. 列出成员
    def t4():
        gid = api.group_list()['groups'][0]['id']
        r = api.group_members(gid)
        assert r['success'] and len(r['members']) == 2
        return True
    tally(check('4. 列出成员（2 人）', t4))

    # 5. 发送消息 + 列出消息
    def t5():
        gid = api.group_list()['groups'][0]['id']
        s = api.message_send(group_id=gid, content='hello')
        assert s['success']
        lst = api.message_list(group_id=gid)
        assert any(m['content'] == 'hello' for m in lst['messages'])
        return True
    tally(check('5. 发送 + 列出消息', t5))

    # 6. 消息已读
    def t6():
        gid = api.group_list()['groups'][0]['id']
        mid = api.message_list(group_id=gid)['messages'][0]['id']
        r = api.message_mark_read(message_id=mid)
        assert r['success']
        return True
    tally(check('6. 消息标记已读', t6))

    # 7. 删除自己的消息
    def t7():
        gid = api.group_list()['groups'][0]['id']
        s = api.message_send(group_id=gid, content='to be deleted')
        mid = s['message']['id']
        d = api.message_delete(message_id=mid)
        assert d['success']
        return True
    tally(check('7. 删除消息', t7))

    # 8. Owner 踢人
    def t8():
        api.auth_logout()
        owner8_id = api.auth_create_user(display_name='owner8')['user']['id']
        g = api.group_create(name='g8')
        gid = g['group']['id']
        code = g['group']['joinCode']
        api.auth_logout()
        newbie_id = api.auth_create_user(display_name='new8')['user']['id']
        api.group_join(join_code=code)
        # 切回 owner8（不创建）
        api.auth_switch_user(owner8_id)
        rk = api.group_kick(group_id=gid, user_id=newbie_id)
        assert rk['success']
        return True
    tally(check('8. Owner 踢人', t8))

    # 9. 解散协作组
    def t9():
        g = api.group_create(name='g9')
        gid = g['group']['id']
        r = api.group_disband(group_id=gid)
        assert r['success']
        assert all(x['id'] != gid for x in api.group_list()['groups'])
        return True
    tally(check('9. 解散协作组', t9))

    # 10. 退出协作组
    def t10():
        g = api.group_create(name='g10')
        gid = g['group']['id']
        code = g['group']['joinCode']
        api.auth_logout()
        api.auth_create_user(display_name='leaver10')
        api.group_join(join_code=code)
        rl = api.group_leave(group_id=gid)
        assert rl['success']
        return True
    tally(check('10. 退出协作组', t10))

    # 11. 设置共享范围
    def t11():
        g = api.group_create(name='g11')
        gid = g['group']['id']
        r = api.group_set_share(gid, share_tasks=1, share_categories=0,
                                share_group_tasks=1, share_history=0)
        assert r['success']
        return True
    tally(check('11. 设置共享范围', t11))

    # 12. 同步状态
    def t12():
        r = api.sync_status()
        assert r['success']
        assert r['status']['groupCount'] >= 0
        return True
    tally(check('12. 获取同步状态', t12))

    # 13. 同步日志
    def t13():
        r = api.sync_log(limit=10)
        assert r['success']
        return True
    tally(check('13. 获取同步日志', t13))

    # 14. 同步引擎推送 + sync_log 记录
    def t14():
        from backend.network.sync_engine import SyncEngine
        from backend.database.operations import SyncManager
        sm = getattr(api, 'sync_manager', None) or SyncManager(api.db)
        se = SyncEngine(db=api.db, sync_manager=sm)
        se.apply_remote_change('task', {
            'id': 't1', 'title': 'remote-task', 'status': 'pending',
            'created_at': '2026-06-19T10:00:00Z',
            'updated_at': '2026-06-19T10:00:00Z', 'version': 1,
        }, peer_id='node-test')
        logs = se.sync_manager.list_recent_sync_logs()
        assert any(l.entity_id == 't1' for l in logs)
        return True
    tally(check('14. 同步引擎推送 + sync_log 记录', t14))

    # 15. 隐藏组（is_hidden 标志）
    def t15():
        g = api.group_create(name='hidden15', is_hidden=1)
        assert g['success'] and g['group']['isHidden'] == 1
        return True
    tally(check('15. 隐藏组 is_hidden=1', t15))

    # 16. 非 Owner 踢人失败
    def t16():
        g = api.group_create(name='g16')
        gid = g['group']['id']
        code = g['group']['joinCode']
        owner_id = g['group']['createdBy']
        api.auth_logout()
        api.auth_create_user(display_name='member16')
        api.group_join(join_code=code)
        rk = api.group_kick(group_id=gid, user_id=owner_id)
        assert not rk['success']
        return True
    tally(check('16. 非 Owner 踢人失败', t16))

    # 17. 协议编解码
    def t17():
        from backend.network.protocol import encode_message, decode_message
        msg = {'type': 'PING', 'node_id': 'n1', 'timestamp': '2026-06-19T10:00:00Z'}
        encoded = encode_message(msg)
        decoded = decode_message(encoded)
        assert decoded == msg
        return True
    tally(check('17. 协议编解码（encode/decode）', t17))

    # 18. UDP beacon 解析
    def t18():
        from backend.network.discovery import parse_beacon
        raw = {
            'type': 'discovery_beacon', 'node_id': 'n1', 'user_id': 'u1',
            'user_name': '郭', 'groups': [{'group_id': 'g1', 'join_code': 'A8B-3K9', 'is_hidden': False}],
            'tcp_port': 54722, 'timestamp': '2026-06-19T10:00:00Z',
        }
        b = parse_beacon(raw)
        assert b.node_id == 'n1' and b.groups[0].join_code == 'A8B-3K9'
        return True
    tally(check('18. UDP beacon 解析', t18))

    # 19. 前端 4 模块文件存在
    def t19():
        for js in ('group.js', 'chat.js', 'sync-status.js', 'network.js'):
            p = Path(__file__).parent.parent.parent / 'frontend' / 'js' / js
            assert p.exists(), f'缺失 {js}'
        return True
    tally(check('19. 前端 4 模块文件存在', t19))

    print(f'\n=== 通过 {passed}/{total} ===\n')
    Path(db_path).unlink(missing_ok=True)
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
