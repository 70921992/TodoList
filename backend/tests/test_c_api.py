"""
C 阶段 API 集成测试（6 个核心端到端测试）
运行：python backend/tests/test_c_api.py
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


def _login(api, name='测试'):
    r = api.auth_create_user(display_name=name)
    assert r['success'], f'登录失败: {r}'
    return r.get('user', {}).get('id')


def test_api_group_create_and_list():
    api, path = _make_api()
    try:
        _login(api)
        r = api.group_create(name='研发组')
        assert r['success'], f'创建失败: {r}'
        assert r['group']['joinCode']
        assert len(r['group']['joinCode']) == 7

        rl = api.group_list()
        assert rl['success'] and len(rl['groups']) == 1
        assert rl['groups'][0]['memberCount'] == 1  # 创建者自动加入
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_group_join():
    api, path = _make_api()
    try:
        uid1 = _login(api, 'A')
        r = api.group_create(name='研发组')
        join_code = r['group']['joinCode']
        gid = r['group']['id']

        api.auth_logout()
        uid2 = _login(api, 'B')
        rj = api.group_join(join_code=join_code)
        assert rj['success'], f'加入失败: {rj}'
        assert rj['group']['id'] == gid

        members = api.group_members(gid)
        assert len(members['members']) == 2
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_message_send_and_list():
    api, path = _make_api()
    try:
        _login(api)
        r = api.group_create(name='研发组')
        gid = r['group']['id']
        s = api.message_send(group_id=gid, content='hello')
        assert s['success'], f'发送失败: {s}'

        lst = api.message_list(group_id=gid)
        assert lst['success'] and len(lst['messages']) == 1
        assert lst['messages'][0]['content'] == 'hello'
        assert lst['messages'][0]['msgType'] == 'text'
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_sync_status():
    api, path = _make_api()
    try:
        _login(api)
        r = api.sync_status()
        assert r['success']
        assert 'groupCount' in r['status']
        assert 'onlineCount' in r['status']
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_group_kick_not_owner_rejected():
    api, path = _make_api()
    try:
        uid1 = _login(api, 'owner')
        r = api.group_create(name='g1')
        gid = r['group']['id']
        join_code = r['group']['joinCode']

        api.auth_logout()
        uid2 = _login(api, 'member')
        api.group_join(join_code=join_code)
        # member 尝试踢 owner
        rk = api.group_kick(group_id=gid, user_id=uid1)
        assert not rk['success'], '非 Owner 应无法踢人'
        assert rk.get('error') == 'NOT_OWNER'
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_group_disband_by_owner():
    api, path = _make_api()
    try:
        _login(api)
        r = api.group_create(name='g1')
        gid = r['group']['id']
        rd = api.group_disband(group_id=gid)
        assert rd['success']

        rl = api.group_list()
        assert all(g['id'] != gid for g in rl['groups'])
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_group_reset_code():
    api, path = _make_api()
    try:
        _login(api)
        r = api.group_create(name='g1')
        gid = r['group']['id']
        old_code = r['group']['joinCode']

        r2 = api.group_reset_code(gid)
        assert r2['success']
        assert r2['joinCode'] != old_code
        assert len(r2['joinCode']) == 7
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_message_mark_read():
    api, path = _make_api()
    try:
        _login(api)
        r = api.group_create(name='g1')
        gid = r['group']['id']
        s = api.message_send(group_id=gid, content='test')
        mid = s['message']['id']

        r2 = api.message_mark_read(message_id=mid)
        assert r2['success']
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_message_delete():
    api, path = _make_api()
    try:
        _login(api)
        r = api.group_create(name='g1')
        gid = r['group']['id']
        s = api.message_send(group_id=gid, content='to-del')
        mid = s['message']['id']

        d = api.message_delete(message_id=mid)
        assert d['success']

        lst = api.message_list(group_id=gid)
        assert all(m['id'] != mid for m in lst['messages'])
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_group_set_share():
    api, path = _make_api()
    try:
        _login(api)
        r = api.group_create(name='g1')
        gid = r['group']['id']
        r2 = api.group_set_share(gid, share_tasks=1, share_categories=0,
                                  share_group_tasks=1, share_history=0)
        assert r2['success']
    finally:
        Path(path).unlink(missing_ok=True)


def test_api_sync_log():
    api, path = _make_api()
    try:
        _login(api)
        r = api.sync_log(limit=10)
        assert r['success']
        assert isinstance(r['logs'], list)
    finally:
        Path(path).unlink(missing_ok=True)
