"""
会员订阅模块
包含：会员管理、配额检查、使用记录
"""
import uuid
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, Depends
from ..db.dbutil import DatabaseUtil
from ..system import config
from ..auth.auth_filter import get_current_user_id

router = APIRouter()
db = DatabaseUtil()

# ==================== 配置（从 config.py 导入） ====================
# 非会员限制配置
NON_MEMBER_LIMIT_HOURS = config.NON_MEMBER_LIMIT_HOURS
NON_MEMBER_LIMIT_MAX = config.NON_MEMBER_LIMIT_MAX

# 免费试用天数
FREE_TRIAL_DAYS = config.FREE_TRIAL_DAYS

# ==================== 数据库操作 ====================

class SubscriptionRepository:
    """会员订阅数据访问"""

    def __init__(self, db: DatabaseUtil):
        self.db = db

    def create_subscription(
        self,
        user_id: str,
        phone: str,
        membership_type: str = 'trial',
        membership_level: str = 'pro',
        start_date: datetime = None,
        end_date: datetime = None
    ) -> str:
        """创建会员订阅"""
        sub_id = str(uuid.uuid4())
        if not start_date:
            start_date = datetime.utcnow()
        if not end_date:
            end_date = start_date + timedelta(days=FREE_TRIAL_DAYS)

        query = '''
            INSERT INTO sub_pro
            (id, user_id, phone, membership_type, membership_level, start_date, end_date, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        '''
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (
                sub_id, user_id, phone, membership_type, membership_level,
                start_date, end_date, True
            ))
            conn.commit()
            print(f"[会员创建] 用户ID: {user_id}, 手机号: {phone}, 等级: {membership_level}, 过期时间: {end_date}")
            return sub_id
        except Exception as e:
            print(f"[会员创建失败] 错误: {str(e)}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_active_subscription(self, user_id: str) -> Optional[Dict]:
        """获取用户的活跃会员"""
        query = '''
            SELECT * FROM sub_pro
            WHERE user_id = %s AND is_active = TRUE AND end_date > CURRENT_TIMESTAMP
            ORDER BY created_at DESC LIMIT 1
        '''
        result = self.db.execute_query(query, (user_id,), "one")
        return dict(result) if result else None

    def has_valid_subscription(self, user_id: str) -> bool:
        """检查用户是否有有效会员"""
        sub = self.get_active_subscription(user_id)
        return sub is not None

    def get_user_subscription_by_phone(self, phone: str) -> Optional[Dict]:
        """根据手机号获取会员信息"""
        query = '''
            SELECT * FROM sub_pro
            WHERE phone = %s AND is_active = TRUE AND end_date > CURRENT_TIMESTAMP
            ORDER BY created_at DESC LIMIT 1
        '''
        result = self.db.execute_query(query, (phone,), "one")
        return dict(result) if result else None

# ==================== 配额检查 ====================

class UsageTracker:
    """使用记录跟踪（使用独立的配额表）"""

    def __init__(self, db: DatabaseUtil):
        self.db = db

    def _get_current_window_start(self) -> datetime:
        """
        计算当前时间窗口的开始时间
        5小时窗口，整点对齐
        例如：14:23 → 10:00（窗口：10:00-15:00）
        """
        now = datetime.utcnow()
        # 计算当前小时在5小时窗口中的偏移
        hour_offset = now.hour % NON_MEMBER_LIMIT_HOURS
        # 窗口开始时间：当前时间 - 小时偏移，分钟秒清零
        window_start = (now.replace(minute=0, second=0, microsecond=0) -
                       timedelta(hours=hour_offset))
        return window_start

    def _get_or_create_quota_record(self, user_id: str, window_start: datetime) -> Dict:
        """获取或创建配额记录"""
        # 先尝试获取现有记录
        query = '''
            SELECT * FROM quota_usage
            WHERE user_id = %s AND window_start = %s
        '''
        result = self.db.execute_query(query, (user_id, window_start), "one")

        if result:
            return dict(result)

        # 不存在则创建新记录
        record_id = str(uuid.uuid4())
        insert_query = '''
            INSERT INTO quota_usage (id, user_id, window_start, message_count)
            VALUES (%s, %s, %s, 0)
        '''
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(insert_query, (record_id, user_id, window_start))
            conn.commit()
            return {
                'id': record_id,
                'user_id': user_id,
                'window_start': window_start,
                'message_count': 0
            }
        except Exception as e:
            print(f"[配额记录创建失败] 错误: {str(e)}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def _increment_quota_count(self, user_id: str, window_start: datetime) -> bool:
        """增加配额计数"""
        update_query = '''
            UPDATE quota_usage
            SET message_count = message_count + 1, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND window_start = %s
        '''
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(update_query, (user_id, window_start))
            conn.commit()
            return True
        except Exception as e:
            print(f"[配额计数更新失败] 错误: {str(e)}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def check_message_quota(self, user_id: str, increment: bool = False) -> Dict:
        """
        检查用户消息配额（使用配额表，不查聊天表）

        Args:
            user_id: 用户ID
            increment: 是否增加计数（发送消息时传True）

        Returns:
            dict: {
                'allowed': bool,  # 是否允许发送
                'is_member': bool,  # 是否是会员
                'count': int,  # 当前窗口已发送次数
                'limit': int,  # 限制次数
                'remaining': int,  # 剩余次数
                'reset_at': datetime  # 重置时间
            }
        """
        sub_repo = SubscriptionRepository(self.db)
        is_member = sub_repo.has_valid_subscription(user_id)

        if is_member:
            # 会员无限制
            return {
                'allowed': True,
                'is_member': True,
                'count': 0,
                'limit': -1,  # -1 表示无限制
                'remaining': -1,
                'reset_at': None
            }

        # 非会员：使用配额表查询
        window_start = self._get_current_window_start()
        record = self._get_or_create_quota_record(user_id, window_start)
        count = record.get('message_count', 0)

        allowed = count < NON_MEMBER_LIMIT_MAX
        remaining = max(0, NON_MEMBER_LIMIT_MAX - count)
        reset_at = window_start + timedelta(hours=NON_MEMBER_LIMIT_HOURS)

        # 如果需要且允许，增加计数（异步执行，失败不影响主流程）
        if increment and allowed:
            try:
                self._increment_quota_count(user_id, window_start)
                remaining -= 1
            except Exception as e:
                # 计数失败只记录日志，不影响返回
                print(f"[配额计数失败] 错误: {str(e)}", file=sys.stderr)

        return {
            'allowed': allowed,
            'is_member': False,
            'count': count,
            'limit': NON_MEMBER_LIMIT_MAX,
            'remaining': remaining,
            'reset_at': reset_at
        }

# ==================== 公共接口函数 ====================

def create_free_trial_subscription(user_id: str, phone: str) -> str:
    """
    为用户创建免费试用会员（首次登录时调用）

    Args:
        user_id: 用户ID
        phone: 手机号

    Returns:
        str: 会员订阅ID
    """
    db = DatabaseUtil()
    sub_repo = SubscriptionRepository(db)
    return sub_repo.create_subscription(
        user_id=user_id,
        phone=phone,
        membership_type='weekly',
        membership_level='pro'
    )

def check_user_message_quota(user_id: str, increment: bool = False) -> Dict:
    """
    检查用户消息配额（供 chat_api.py 调用）

    Args:
        user_id: 用户ID
        increment: 是否增加计数（发送消息成功后传True）

    Returns:
        dict: 配额信息
    """
    db = DatabaseUtil()
    tracker = UsageTracker(db)
    return tracker.check_message_quota(user_id, increment=increment)

def get_user_membership_info(user_id: str) -> Optional[Dict]:
    """
    获取用户会员信息（供前端调用）

    Args:
        user_id: 用户ID

    Returns:
        dict: {
            'is_member': bool,  # 是否是会员
            'membership_type': str,  # 会员类型：weekly/monthly/quarterly/yearly
            'membership_level': str,  # 会员等级：lite/pro/max
            'start_date': datetime,  # 开始时间
            'end_date': datetime,  # 结束时间
            'remaining_days': int,  # 剩余天数
            'phone': str  # 手机号
        }
        如果不是会员返回 None
    """
    db = DatabaseUtil()
    sub_repo = SubscriptionRepository(db)
    subscription = sub_repo.get_active_subscription(user_id)

    if not subscription:
        return None

    # 计算剩余天数
    end_date = subscription['end_date']
    now = datetime.utcnow()
    remaining_days = (end_date - now).days + 1  # +1 包含当天

    return {
        'is_member': True,
        'membership_type': subscription['membership_type'],
        'membership_level': subscription['membership_level'],
        'start_date': subscription['start_date'].isoformat(),
        'end_date': end_date.isoformat(),
        'remaining_days': max(0, remaining_days),
        'phone': subscription['phone']
    }

# ==================== API 路由 ====================

# 管理员密钥
ADMIN_SECRET_KEY = 'usyttnm-uygbmm776sw65doj-suucnnu997sdscerefghhhheedddtgfdl'

# 套餐配置
PACKAGE_CONFIG = {
    '39': {'type': 'monthly', 'days': 30, 'name': '月卡'},
    '99': {'type': 'quarterly', 'days': 90, 'name': '季卡'},
    '299': {'type': 'yearly', 'days': 365, 'name': '年卡'}
}


@router.post("/subscription/admin-activate")
async def admin_activate_membership(request: dict):
    """
    管理员开通会员（需要密钥验证）
    同一手机号多次开通会累加天数

    Request body:
        phone: 手机号
        package: 套餐价格 (39/99/299)
        secret_key: 密钥
    """
    try:
        print(f"[管理员开通] ========== 开始处理请求 ==========")
        print(f"[管理员开通] 请求数据: {request}")

        phone = request.get('phone')
        package_price = request.get('package')
        secret_key = request.get('secret_key')

        print(f"[管理员开通] 解析后 - 手机号: {phone}, 套餐: {package_price}, 密钥: {secret_key}")

        # 验证密钥
        if secret_key != ADMIN_SECRET_KEY:
            print(f"[管理员开通] ❌ 密钥错误: {secret_key}")
            return {
                "status": "error",
                "detail": "密钥错误"
            }

        # 验证套餐
        if package_price not in PACKAGE_CONFIG:
            print(f"[管理员开通] ❌ 无效套餐: {package_price}")
            return {
                "status": "error",
                "detail": "无效的套餐"
            }

        # 验证手机号
        if not phone or len(phone) != 11:
            print(f"[管理员开通] ❌ 手机号格式错误: {phone}")
            return {
                "status": "error",
                "detail": "手机号格式错误"
            }

        print(f"[管理员开通] ✓ 基本验证通过")

        # 查询用户ID
        query = "SELECT id FROM users WHERE phone = %s"
        result = db.execute_query(query, (phone,), "one")

        if not result:
            print(f"[管理员开通] ❌ 用户不存在: {phone}")
            return {
                "status": "error",
                "detail": "用户不存在，请确认手机号是否正确"
            }

        user_id = result['id']
        print(f"[管理员开通] ✓ 找到用户ID: {user_id}")

        package_info = PACKAGE_CONFIG[package_price]
        print(f"[管理员开通] 套餐信息: {package_info}")

        sub_repo = SubscriptionRepository(db)

        # 检查会员记录（所有用户首次登录都会创建7天试用）
        print(f"[管理员开通] 检查会员状态...")
        existing_sub = sub_repo.get_active_subscription(user_id)

        if existing_sub:
            print(f"[管理员开通] ✓ 找到活跃会员: {existing_sub}")
            # 会员未过期：在原结束时间基础上累加天数
            old_end_date = existing_sub['end_date']
            base_date = old_end_date
            new_end_date = base_date + timedelta(days=package_info['days'])

            print(f"[管理员开通] 会员未过期，原过期: {old_end_date}, 新过期: {new_end_date}")

            # 更新数据库
            update_query = '''
                UPDATE sub_pro
                SET end_date = %s, membership_type = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            '''
            conn = db.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(update_query, (new_end_date, package_info['type'], existing_sub['id']))
                conn.commit()
                print(f"[管理员开通] ✅ [续费成功] 手机号: {phone}, 套餐: {package_info['name']}, 原过期: {old_end_date}, 新过期: {new_end_date}")
            finally:
                conn.close()

            return {
                "status": "success",
                "message": f"已成功续费{package_info['name']}会员，有效期延长至 {new_end_date.strftime('%Y-%m-%d %H:%M')}",
                "data": {
                    "phone": phone,
                    "package": package_info['name'],
                    "old_end_date": old_end_date.isoformat(),
                    "new_end_date": new_end_date.isoformat(),
                    "subscription_id": existing_sub['id']
                }
            }
        else:
            print(f"[管理员开通] 无活跃会员，查找历史记录...")
            # 会员已过期，从今天开始算新天数
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=package_info['days'])

            print(f"[管理员开通] 重新开通 - 开始: {start_date}, 结束: {end_date}")

            # 查找该用户最近的会员记录并更新
            query = '''
                SELECT id FROM sub_pro
                WHERE user_id = %s
                ORDER BY created_at DESC LIMIT 1
            '''
            sub_result = db.execute_query(query, (user_id,), "one")

            print(f"[管理员开通] 查询结果: {sub_result}")

            if sub_result:
                print(f"[管理员开通] ✓ 找到历史记录ID: {sub_result['id']}")
                # 更新现有记录
                update_query = '''
                    UPDATE sub_pro
                    SET start_date = %s, end_date = %s, membership_type = %s, is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                '''
                conn = db.get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(update_query, (start_date, end_date, package_info['type'], sub_result['id']))
                    affected_row = cursor.rowcount
                    conn.commit()
                    print(f"[管理员开通] ✅ [重新开通成功] 手机号: {phone}, 套餐: {package_info['name']}, 新过期: {end_date}, 影响行数: {affected_row}")
                finally:
                    conn.close()

                return {
                    "status": "success",
                    "message": f"已成功开通{package_info['name']}会员，有效期至 {end_date.strftime('%Y-%m-%d %H:%M')}",
                    "data": {
                        "phone": phone,
                        "package": package_info['name'],
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "subscription_id": sub_result['id']
                    }
                }
            else:
                # 理论上不会到这里，因为登录会创建会员记录
                print(f"[管理员开通] ❌ 错误：找不到会员记录")
                return {
                    "status": "error",
                    "detail": "用户会员记录不存在，请先登录"
                }

    except Exception as e:
        print(f"[管理员开通] ❌ 异常错误: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "detail": f"开通失败: {str(e)}"
        }


@router.get("/subscription/admin-list")
async def get_admin_membership_list(page: int = 1, page_size: int = 50, secret_key: str = None):
    """
    获取会员列表（管理员接口，需要密钥）

    Args:
        page: 页码（从1开始）
        page_size: 每页数量
        secret_key: 密钥
    """
    try:
        # 验证密钥
        if secret_key != ADMIN_SECRET_KEY:
            raise HTTPException(
                status_code=403,
                detail="密钥错误"
            )

        # 计算偏移量
        offset = (page - 1) * page_size

        # 查询总数
        count_query = "SELECT COUNT(*) as total FROM sub_pro"
        count_result = db.execute_query(count_query, (), "one")
        total = count_result['total']

        # 查询会员列表
        query = '''
            SELECT s.*, u.phone as user_phone, u.username
            FROM sub_pro s
            LEFT JOIN users u ON s.user_id = u.id
            ORDER BY s.updated_at DESC
            LIMIT %s OFFSET %s
        '''
        results = db.execute_query(query, (page_size, offset), "all")

        members = []
        for row in results:
            members.append({
                'id': row['id'],
                'user_id': row['user_id'],
                'phone': row['phone'],
                'username': row['username'],
                'membership_type': row['membership_type'],
                'membership_level': row['membership_level'],
                'start_date': row['start_date'].isoformat() if row['start_date'] else None,
                'end_date': row['end_date'].isoformat() if row['end_date'] else None,
                'is_active': row['is_active'],
                'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
            })

        return {
            "status": "success",
            "data": {
                "members": members,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[管理员会员列表] 错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=500,
            detail=f"获取列表失败: {str(e)}"
        )


@router.get("/subscription/membership")
async def get_membership(user_id: str = Depends(get_current_user_id)):
    """获取当前用户的会员信息"""
    try:
        membership_info = get_user_membership_info(user_id)
        return {
            "status": "success",
            "data": membership_info  # 如果不是会员返回 null
        }
    except Exception as e:
        print(f"获取会员信息错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=500,
            detail="获取会员信息失败"
        )
