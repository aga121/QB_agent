"""
短信验证码模块（单表设计）
包含：数据库操作、互亿无线短信发送、验证码验证
"""
import os
import uuid
import time
import hashlib
import random
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict
from ..db.dbutil import DatabaseUtil
from ..system import config
from ..cache.redis_cache import check_sms_verify_lock, increment_sms_verify_fail, clear_sms_verify_fail

# ==================== 配置（从 config.py 导入） ====================
# 使用 config.py 中的配置
IHYI_ACCOUNT = config.IHYI_ACCOUNT
IHYI_PASSWORD = config.IHYI_PASSWORD
IHYI_TEMPLATE_ID = config.IHYI_TEMPLATE_ID
IHYI_API_URL = config.IHYI_API_URL

SMS_CODE_LENGTH = config.SMS_CODE_LENGTH
SMS_CODE_VALID_DAYS = config.SMS_CODE_VALID_DAYS
SMS_CODE_RESEND_BLOCK_DAYS = config.SMS_CODE_RESEND_BLOCK_DAYS
SMS_CODE_RESEND_COOLDOWN_SECONDS = config.SMS_CODE_RESEND_COOLDOWN_SECONDS
SMS_RATE_LIMIT_MAX = config.SMS_RATE_LIMIT_MAX
SMS_RATE_LIMIT_WINDOW_HOURS = config.SMS_RATE_LIMIT_WINDOW_HOURS

# ==================== 数据库操作（单表） ====================

class SMSRepository:
    """短信验证码数据访问（单表设计）"""

    def __init__(self, db: DatabaseUtil):
        self.db = db

    def create_code(self, phone: str, code: str, expires_at: datetime,
                    client_ip: str = None, user_agent: str = None,
                    fingerprint: str = None) -> str:
        """创建验证码记录"""
        code_id = str(uuid.uuid4())
        query = '''
            INSERT INTO sms_verification_codes
            (id, phone, code, expires_at, sent_at, client_ip, user_agent, fingerprint)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        '''
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (code_id, phone, code, expires_at,
                                   datetime.utcnow(), client_ip, user_agent, fingerprint))
            conn.commit()
            print(f"[验证码保存成功] 手机号: {phone}, 验证码: {code}, ID: {code_id}")
            return code_id
        except Exception as e:
            print(f"[验证码保存失败] 错误: {str(e)}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_latest_valid_code(self, phone: str) -> Optional[Dict]:
        """获取最新的有效验证码"""
        query = '''
            SELECT * FROM sms_verification_codes
            WHERE phone = %s AND expires_at > NOW() AT TIME ZONE 'UTC'
            ORDER BY sent_at DESC LIMIT 1
        '''
        result = self.db.execute_query(query, (phone,), "one")
        return dict(result) if result else None

    def verify_code(self, phone: str, code: str) -> bool:
        """验证验证码（30天内可重复使用）"""

        # 万能验证码（用于测试）
        if config.UNIVERSAL_SMS_CODE and code == config.UNIVERSAL_SMS_CODE:
            print(f"[验证码验证] 使用万能验证码: {phone}")
            return True

        query = '''
            SELECT id, phone, code, expires_at FROM sms_verification_codes
            WHERE phone = %s AND code = %s AND expires_at > NOW() AT TIME ZONE 'UTC'
            ORDER BY sent_at DESC LIMIT 1
        '''
        result = self.db.execute_query(query, (phone, code), "one")

        # 调试日志
        print(f"[验证码验证] 手机号: {phone}, 验证码: {code}")
        print(f"[验证码验证] 查询结果: {result}")

        if not result:
            print(f"[验证码验证] 未找到有效验证码")
            return False

        print(f"[验证码验证] 验证成功，ID: {result['id']}")
        return True

    def check_rate_limit(self, phone: str, client_ip: str = None) -> bool:
        """检查速率限制（查询过去24小时内的记录数量）"""
        window_start = datetime.utcnow() - timedelta(hours=SMS_RATE_LIMIT_WINDOW_HOURS)

        # 检查手机号限制
        query = '''
            SELECT COUNT(*) as count FROM sms_verification_codes
            WHERE phone = %s AND sent_at > %s
        '''
        result = self.db.execute_query(query, (phone, window_start), "one")
        if result['count'] >= SMS_RATE_LIMIT_MAX:
            return False

        # 检查IP限制
        if client_ip:
            query = '''
                SELECT COUNT(*) as count FROM sms_verification_codes
                WHERE client_ip = %s AND sent_at > %s
            '''
            result = self.db.execute_query(query, (client_ip, window_start), "one")
            if result['count'] >= SMS_RATE_LIMIT_MAX:
                return False

        return True

    def check_cooldown(self, phone: str, client_ip: str = None) -> bool:
        """检查冷却时间（查询最后发送时间）"""
        # 检查手机号冷却时间
        query = '''
            SELECT sent_at FROM sms_verification_codes
            WHERE phone = %s ORDER BY sent_at DESC LIMIT 1
        '''
        result = self.db.execute_query(query, (phone,), "one")

        if result:
            last_sent = result['sent_at']
            elapsed = (datetime.utcnow() - last_sent).total_seconds()
            if elapsed < SMS_CODE_RESEND_COOLDOWN_SECONDS:
                return False

        # 检查IP冷却时间
        if client_ip:
            query = '''
                SELECT sent_at FROM sms_verification_codes
                WHERE client_ip = %s ORDER BY sent_at DESC LIMIT 1
            '''
            result = self.db.execute_query(query, (client_ip,), "one")
            if result:
                last_sent = result['sent_at']
                elapsed = (datetime.utcnow() - last_sent).total_seconds()
                if elapsed < SMS_CODE_RESEND_COOLDOWN_SECONDS:
                    return False

        return True

# ==================== 短信发送 ====================

async def send_sms_ihyi(phone: str, code: str) -> bool:
    """使用互亿无线发送短信"""
    try:
        # 生成动态密码
        timestamp = str(int(time.time()))
        # 动态密码生成方式：md5(account + password + mobile + content + time)
        content = str(code)  # 模板变量
        password_sign = hashlib.md5(
            (IHYI_ACCOUNT + IHYI_PASSWORD + phone + content + timestamp).encode('utf-8')
        ).hexdigest()

        # 构建请求参数
        params = {
            'account': IHYI_ACCOUNT,
            'password': password_sign,
            'mobile': phone,
            'content': content,
            'templateid': IHYI_TEMPLATE_ID,
            'time': timestamp
        }

        # 发送请求
        async with httpx.AsyncClient() as client:
            response = await client.post(
                IHYI_API_URL,
                data=params,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=10.0
            )
            result = response.json()

            # 调试日志：查看完整响应
            print(f"[短信API响应] 手机号: {phone}, 完整响应: {result}")

            # 检查返回结果（code可能是字符串或整数）
            response_code = result.get('code')
            if response_code == '2' or response_code == 2:
                print(f"[短信发送成功] 手机号: {phone}, 验证码: {code}, 短信ID: {result.get('smsid')}")
                return True
            else:
                print(f"[短信发送失败] 手机号: {phone}, code={response_code}, 错误: {result.get('msg')}")
                return False

    except Exception as e:
        print(f"[短信发送异常] 手机号: {phone}, 错误: {str(e)}")
        return False

# ==================== 公共接口函数 ====================

def generate_code() -> str:
    """生成随机验证码"""
    return ''.join([str(random.randint(0, 9)) for _ in range(SMS_CODE_LENGTH)])

async def send_verification_code(phone: str, client_ip: str = None,
                                  user_agent: str = None, fingerprint: str = None) -> Dict:
    """
    发送验证码接口（供 user_api.py 调用）

    Args:
        phone: 手机号
        client_ip: 客户端IP
        user_agent: 用户代理
        fingerprint: 设备指纹

    Returns:
        dict: {'success': bool, 'message': str}
    """
    now = datetime.utcnow()
    db = DatabaseUtil()
    sms_repo = SMSRepository(db)

    # 检查速率限制
    if not sms_repo.check_rate_limit(phone, client_ip):
        return {'success': False, 'message': '请求过于频繁，24小时内最多发送10次'}

    # 检查冷却时间
    if not sms_repo.check_cooldown(phone, client_ip):
        return {'success': False, 'message': '请求过于频繁，请稍后再试'}

    # 检查现有验证码（30天重发阻塞期）
    existing = sms_repo.get_latest_valid_code(phone)
    if existing:
        sent_at = existing['sent_at']
        if (now - sent_at).days < SMS_CODE_RESEND_BLOCK_DAYS:
            return {'success': False, 'message': '验证码有效30天，请查看手机短信【达信通】'}

    # 生成验证码
    code = generate_code()
    expires_at = now + timedelta(days=SMS_CODE_VALID_DAYS)

    # 发送短信
    send_success = await send_sms_ihyi(phone, code)
    if not send_success:
        return {'success': False, 'message': '短信发送失败，请稍后再试'}

    # 保存到数据库
    sms_repo.create_code(
        phone=phone,
        code=code,
        expires_at=expires_at,
        client_ip=client_ip,
        user_agent=user_agent,
        fingerprint=fingerprint
    )

    return {
        'success': True,
        'message': '验证码已发送',
        'expires_at': expires_at.isoformat()
    }

def verify_login_code(phone: str, code: str) -> Dict:
    """
    验证登录验证码（供 user_api.py 调用）

    Args:
        phone: 手机号
        code: 验证码

    Returns:
        dict: {'success': bool, 'message': str}
    """
    # 检查是否被锁定
    if check_sms_verify_lock(phone):
        return {
            'success': False,
            'message': '验证码已锁定，请30分钟后再试'
        }

    # 验证验证码
    db = DatabaseUtil()
    sms_repo = SMSRepository(db)
    is_valid = sms_repo.verify_code(phone, code)

    if is_valid:
        # 验证成功，清除失败次数
        clear_sms_verify_fail(phone)
        return {
            'success': True,
            'message': '验证成功'
        }
    else:
        # 验证失败，增加失败次数
        fail_count = increment_sms_verify_fail(phone)
        remaining = 10 - fail_count
        if remaining > 0:
            return {
                'success': False,
                'message': f'验证码错误，还剩{remaining}次尝试机会'
            }
        else:
            return {
                'success': False,
                'message': '验证码错误次数过多，已锁定30分钟'
            }
