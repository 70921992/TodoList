"""
TodoList应用的数据模型定义
"""

from datetime import datetime
import uuid


class Task:
    """任务数据模型"""
    
    def __init__(self, id=None, title='', description='', completed=False, 
                 priority='none', category_id=None, due_date=None, 
                 is_recurring=False, recurrence_type=None, recurrence_interval=1, 
                 recurrence_count=None, parent_task_id=None):
        self.id = id or str(uuid.uuid4())
        self.title = title
        self.description = description
        self.completed = completed
        self.priority = priority  # 'high', 'medium', 'low', 'none'
        self.category_id = category_id
        self.due_date = due_date
        self.is_recurring = is_recurring  # 是否为周期性任务
        self.recurrence_type = recurrence_type  # 'daily', 'weekly', 'monthly', 'yearly'
        self.recurrence_interval = recurrence_interval  # 间隔数
        self.recurrence_count = recurrence_count  # 循环次数，None表示无限循环
        self.parent_task_id = parent_task_id  # 父任务ID，用于周期性任务的子任务
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'completed': self.completed,
            'priority': self.priority,
            'categoryId': self.category_id,
            'dueDate': self.due_date.isoformat() if self.due_date else None,
            'isRecurring': self.is_recurring,
            'recurrenceType': self.recurrence_type,
            'recurrenceInterval': self.recurrence_interval,
            'recurrenceCount': self.recurrence_count,
            'parentTaskId': self.parent_task_id,
            'createdAt': self.created_at.isoformat(),
            'updatedAt': self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建Task实例"""
        task = cls(
            id=data.get('id'),
            title=data.get('title', ''),
            description=data.get('description', ''),
            completed=data.get('completed', False),
            priority=data.get('priority', 'none'),
            category_id=data.get('categoryId'),
            due_date=datetime.fromisoformat(data['dueDate']) if data.get('dueDate') else None,
            is_recurring=data.get('isRecurring', False),
            recurrence_type=data.get('recurrenceType'),
            recurrence_interval=data.get('recurrenceInterval', 1),
            recurrence_count=data.get('recurrenceCount'),
            parent_task_id=data.get('parentTaskId')
        )
        if 'createdAt' in data:
            task.created_at = datetime.fromisoformat(data['createdAt'])
        if 'updatedAt' in data:
            task.updated_at = datetime.fromisoformat(data['updatedAt'])
        return task


class Category:
    """分类数据模型"""
    
    def __init__(self, id=None, name='', color='#007bff'):
        self.id = id or str(uuid.uuid4())
        self.name = name
        self.color = color
        self.created_at = datetime.now()
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'createdAt': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建Category实例"""
        category = cls(
            id=data.get('id'),
            name=data.get('name', ''),
            color=data.get('color', '#007bff')
        )
        if 'createdAt' in data:
            category.created_at = datetime.fromisoformat(data['createdAt'])
        return category


class Tag:
    """标签数据模型"""

    def __init__(self, id=None, name='', color='#6c757d'):
        self.id = id or str(uuid.uuid4())
        self.name = name  # 标签名称，不包含#符号
        self.color = color
        self.created_at = datetime.now()

    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'createdAt': self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建Tag实例"""
        tag = cls(
            id=data.get('id'),
            name=data.get('name', ''),
            color=data.get('color', '#6c757d')
        )
        if 'createdAt' in data:
            tag.created_at = datetime.fromisoformat(data['createdAt'])
        return tag


class User:
    """用户数据模型"""

    def __init__(self, id=None, display_name='', unit=None, department=None,
                 role=None, avatar_color='#4f46e5', created_at=None,
                 last_active_at=None, is_deleted=False):
        self.id = id or str(uuid.uuid4())
        self.display_name = display_name
        self.unit = unit
        self.department = department
        self.role = role
        self.avatar_color = avatar_color
        self.created_at = created_at or datetime.now()
        self.last_active_at = last_active_at
        self.is_deleted = is_deleted

    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'displayName': self.display_name,
            'unit': self.unit,
            'department': self.department,
            'role': self.role,
            'avatarColor': self.avatar_color,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'lastActiveAt': self.last_active_at.isoformat() if self.last_active_at else None,
            'isDeleted': self.is_deleted
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建User实例"""
        user = cls(
            id=data.get('id'),
            display_name=data.get('displayName', ''),
            unit=data.get('unit'),
            department=data.get('department'),
            role=data.get('role'),
            avatar_color=data.get('avatarColor', '#4f46e5'),
            is_deleted=bool(data.get('isDeleted', False))
        )
        if data.get('createdAt'):
            user.created_at = datetime.fromisoformat(data['createdAt'])
        if data.get('lastActiveAt'):
            user.last_active_at = datetime.fromisoformat(data['lastActiveAt'])
        return user


class UserSession:
    """用户会话模型"""

    def __init__(self, token, user_id, created_at=None, last_used_at=None):
        self.token = token
        self.user_id = user_id
        self.created_at = created_at or datetime.now()
        self.last_used_at = last_used_at or datetime.now()

    def to_dict(self):
        """转换为字典格式"""
        return {
            'token': self.token,
            'userId': self.user_id,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'lastUsedAt': self.last_used_at.isoformat() if self.last_used_at else None
        }


class TaskAuditLog:
    """任务审计日志模型"""

    def __init__(self, id=None, task_id='', user_id='', action='',
                 field=None, old_value=None, new_value=None, created_at=None):
        self.id = id or str(uuid.uuid4())
        self.task_id = task_id
        self.user_id = user_id
        self.action = action  # create/update/complete/delete/restore
        self.field = field
        self.old_value = old_value
        self.new_value = new_value
        self.created_at = created_at or datetime.now()

    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'taskId': self.task_id,
            'userId': self.user_id,
            'action': self.action,
            'field': self.field,
            'oldValue': self.old_value,
            'newValue': self.new_value,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }