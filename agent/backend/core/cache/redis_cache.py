"""
Redis 缓存工具类
用于缓存 sync counts 等高频访问数据
"""
import redis
import logging
from typing import Optional, Dict, Any
from ..system import config

logger = logging.getLogger(__name__)

# 全局 Redis 客户端实例
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> Optional[redis.Redis]:
    """
    获取 Redis 客户端实例（单例模式）

    Returns:
        Redis 客户端，如果未启用或连接失败则返回 None
    """
    global _redis_client

    # 如果禁用缓存，直接返回 None
    if not config.SYNC_CACHE_ENABLED:
        return None

    # 如果已初始化，直接返回
    if _redis_client is not None:
        return _redis_client

    try:
        _redis_client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            password=config.REDIS_PASSWORD,
            decode_responses=False,  # 保持 bytes 类型，避免编码问题
            socket_connect_timeout=2,  # 连接超时 2 秒
            socket_timeout=2,  # 读写超时 2 秒
        )
        # 测试连接
        _redis_client.ping()
        logger.info(f"Redis 缓存已启用: {config.REDIS_HOST}:{config.REDIS_PORT}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis 连接失败，缓存功能已禁用: {e}")
        _redis_client = None  # 标记为不可用
        return None


def increment_sync_count(user_id: str, session_id: str) -> bool:
    """
    增加指定会话的消息计数（在保存新消息时调用）

    Args:
        user_id: 用户 ID
        session_id: 会话 ID

    Returns:
        是否更新成功
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        cache_key = f"sync:counts:{user_id}"
        # 使用 HINCRBY 原子性地增加计数
        client.hincrby(cache_key, session_id, 1)
        # 重新设置过期时间（兜底）
        client.expire(cache_key, config.SYNC_CACHE_TTL)
        return True
    except Exception as e:
        logger.warning(f"Redis 更新缓存失败: {e}")
        return False


def get_sync_counts(user_id: str) -> Optional[Dict[str, int]]:
    """
    获取用户的所有会话消息计数（从缓存）

    Args:
        user_id: 用户 ID

    Returns:
        {session_id: count} 字典，如果缓存未命中返回 None
    """
    client = get_redis_client()
    if not client:
        return None

    try:
        cache_key = f"sync:counts:{user_id}"
        cached = client.hgetall(cache_key)

        if not cached:
            return None

        # 将 bytes 转换为字符串和整数
        return {
            sid.decode(): int(count)
            for sid, count in cached.items()
        }
    except Exception as e:
        logger.warning(f"Redis 读取缓存失败: {e}")
        return None


def set_sync_counts(user_id: str, counts: Dict[str, int]) -> bool:
    """
    设置用户的所有会话消息计数（首次查询数据库后写入缓存）

    Args:
        user_id: 用户 ID
        counts: {session_id: count} 字典

    Returns:
        是否写入成功
    """
    client = get_redis_client()
    if not client:
        return False

    # 空字典不写入（新用户无会话是正常状态，缓存未命中即可）
    if not counts:
        return False

    try:
        cache_key = f"sync:counts:{user_id}"
        # 批量设置所有 session 的 count
        mapping = {str(sid): str(count) for sid, count in counts.items()}
        client.hset(cache_key, mapping=mapping)
        # 设置过期时间（兜底）
        client.expire(cache_key, config.SYNC_CACHE_TTL)
        return True
    except Exception as e:
        logger.warning(f"Redis 写入缓存失败: {e}")
        return False


def invalidate_sync_cache(user_id: str) -> bool:
    """
    使缓存失效（用于调试或强制刷新）

    Args:
        user_id: 用户 ID

    Returns:
        是否删除成功
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        cache_key = f"sync:counts:{user_id}"
        client.delete(cache_key)
        return True
    except Exception as e:
        logger.warning(f"Redis 删除缓存失败: {e}")
        return False


# ==================== session -> agent_id 映射缓存 ====================

def set_sync_agents(user_id: str, agents: Dict[str, str]) -> bool:
    """
    设置用户的所有会话 agent_id 映射（首次查询数据库后写入缓存）

    Args:
        user_id: 用户 ID
        agents: {session_id: agent_id} 字典

    Returns:
        是否写入成功
    """
    client = get_redis_client()
    if not client:
        return False

    # 空字典不写入（新用户无会话是正常状态，缓存未命中即可）
    if not agents:
        return False

    try:
        cache_key = f"sync:agents:{user_id}"
        # 批量设置所有 session 的 agent_id
        mapping = {str(sid): str(agent_id) for sid, agent_id in agents.items()}
        client.hset(cache_key, mapping=mapping)
        # 设置过期时间（兜底）
        client.expire(cache_key, config.SYNC_CACHE_TTL)
        return True
    except Exception as e:
        logger.warning(f"Redis 写入 agent 缓存失败: {e}")
        return False


def get_sync_agents(user_id: str) -> Optional[Dict[str, str]]:
    """
    获取用户的所有会话 agent_id 映射（从缓存）

    Args:
        user_id: 用户 ID

    Returns:
        {session_id: agent_id} 字典，如果缓存未命中返回 None
    """
    client = get_redis_client()
    if not client:
        return None

    try:
        cache_key = f"sync:agents:{user_id}"
        cached = client.hgetall(cache_key)

        if not cached:
            return None

        # 将 bytes 转换为字符串
        return {
            sid.decode(): agent_id.decode()
            for sid, agent_id in cached.items()
        }
    except Exception as e:
        logger.warning(f"Redis 读取 agent 缓存失败: {e}")
        return None


# ==================== 验证码验证失败次数限制 ====================

import time

MAX_VERIFY_ATTEMPTS = 10  # 最大验证失败次数
VERIFY_LOCK_MINUTES = 30  # 锁定时长（分钟）


def check_sms_verify_lock(phone: str) -> bool:
    """
    检查手机号是否被锁定

    Args:
        phone: 手机号

    Returns:
        True 表示已锁定（不可验证），False 表示未锁定
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        lock_key = f"sms:verify:locked:{phone}"
        locked_until = client.get(lock_key)
        if locked_until:
            if int(time.time()) < int(locked_until):
                logger.info(f"[验证码锁定] 手机号 {phone} 已锁定")
                return True
            else:
                # 锁定已过期，删除相关记录
                client.delete(lock_key)
                client.delete(f"sms:verify:fail:{phone}")
        return False
    except Exception as e:
        logger.warning(f"Redis 检查验证码锁定失败: {e}")
        return False


def increment_sms_verify_fail(phone: str) -> int:
    """
    增加验证失败次数

    Args:
        phone: 手机号

    Returns:
        当前失败次数
    """
    client = get_redis_client()
    if not client:
        return 0

    try:
        fail_key = f"sms:verify:fail:{phone}"
        fail_count = client.incr(fail_key)
        # 设置过期时间为锁定时长+60秒
        client.expire(fail_key, VERIFY_LOCK_MINUTES * 60 + 60)

        logger.info(f"[验证码验证] 手机号 {phone} 验证失败，失败次数: {fail_count}/{MAX_VERIFY_ATTEMPTS}")

        # 达到最大失败次数，锁定
        if fail_count >= MAX_VERIFY_ATTEMPTS:
            lock_until = int(time.time()) + VERIFY_LOCK_MINUTES * 60
            lock_key = f"sms:verify:locked:{phone}"
            client.set(lock_key, str(lock_until))
            client.expire(lock_key, VERIFY_LOCK_MINUTES * 60 + 60)
            logger.warning(f"[验证码锁定] 手机号 {phone} 已锁定 {VERIFY_LOCK_MINUTES} 分钟")

        return fail_count
    except Exception as e:
        logger.warning(f"Redis 更新验证失败次数失败: {e}")
        return 0


def clear_sms_verify_fail(phone: str) -> bool:
    """
    清除验证失败次数（验证成功时调用）

    Args:
        phone: 手机号

    Returns:
        是否清除成功
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        fail_key = f"sms:verify:fail:{phone}"
        client.delete(fail_key)
        return True
    except Exception as e:
        logger.warning(f"Redis 清除验证失败次数失败: {e}")
        return False
