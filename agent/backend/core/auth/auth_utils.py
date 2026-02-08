"""
简单的认证工具模块
"""
import hashlib
import hmac
import json
import base64
from datetime import datetime, timedelta
import os
from ..system import config

# 密钥，从配置文件读取
SECRET_KEY = config.SECRET_KEY

def generate_token(user_id: str, username: str) -> str:
    """
    生成简单的认证token

    Args:
        user_id: 用户ID
        username: 用户名

    Returns:
        token字符串
    """
    # 创建token数据
    header = {
        'alg': 'HS256',
        'typ': 'JWT'
    }

    payload = {
        'user_id': user_id,
        'username': username,
        'exp': (datetime.now() + timedelta(days=config.TOKEN_EXPIRE_DAYS)).timestamp(),
        'iat': datetime.now().timestamp()
    }

    # 简单的编码（不是真正的JWT，只是类似）
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')

    # 创建签名
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    return f"{message}.{signature}"

def verify_token(token: str) -> dict:
    """
    验证token

    Args:
        token: token字符串

    Returns:
        用户信息字典，如果验证失败返回None
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature = parts

        # 重建消息并验证签名
        message = f"{header_b64}.{payload_b64}"
        expected_signature = hmac.new(
            SECRET_KEY.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        # 使用hmac比较防止时序攻击
        if not hmac.compare_digest(signature, expected_signature):
            return None

        # 解码payload
        # 添加填充
        payload_b64 += '=' * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode())

        # 检查过期时间
        if payload.get('exp') and payload['exp'] < datetime.now().timestamp():
            return None

        return payload

    except Exception as e:
        print(f"Token验证错误: {e}")
        return None

def create_session_token(user_id: str, username: str, password: str) -> str:
    """
    创建会话token（结合用户密码的哈希值）

    Args:
        user_id: 用户ID
        username: 用户名
        password: 用户密码

    Returns:
        session_token
    """
    # 使用用户ID、用户名和密码的哈希值创建会话密钥
    password_hash = hashlib.sha256(password.encode()).hexdigest()[:16]
    session_key = f"{user_id}:{username}:{password_hash}"

    # 使用会话密钥加密用户信息
    session_data = {
        'user_id': user_id,
        'username': username,
        'timestamp': datetime.now().timestamp()
    }

    # 简单加密
    json_data = json.dumps(session_data)
    encrypted = base64.urlsafe_b64encode(
        hmac.new(session_key.encode(), json_data.encode(), hashlib.sha256).digest()
    ).decode()

    # 组合token
    token = f"{base64.urlsafe_b64encode(session_key.encode()).decode()}.{encrypted}"
    return token.rstrip('=')

def verify_session_token(session_token: str, user_password: str) -> dict:
    """
    验证会话token

    Args:
        session_token: 会话token
        user_password: 用户的密码（从数据库获取）

    Returns:
        用户信息字典，验证失败返回None
    """
    try:
        parts = session_token.split('.')
        if len(parts) != 2:
            return None

        session_key_b64, encrypted = parts

        # 解码会话密钥
        session_key_b64 += '=' * (-len(session_key_b64) % 4)
        session_key = base64.urlsafe_b64decode(session_key_b64).decode()

        # 验证密码哈希部分
        user_password_hash = hashlib.sha256(user_password.encode()).hexdigest()[:16]
        if user_password_hash not in session_key:
            return None

        # 解密数据
        decrypted = hmac.new(session_key.encode(), encrypted.encode(), hashlib.sha256).digest()

        # 尝试解密（这里简化处理，实际应该更复杂）
        return {'verified': True}

    except Exception as e:
        print(f"Session token验证错误: {e}")
        return None
