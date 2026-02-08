"""
好友管理API
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
import sys
import uuid
import psycopg2.extras
from typing import List, Dict, Optional
from ..db.dbutil import DatabaseUtil
from ..auth.auth_filter import get_current_user_id

router = APIRouter()

# 初始化数据库
db = DatabaseUtil()


# ==================== 好友关系辅助函数 ====================

def create_friend_request(user_id: str, friend_id: str) -> str:
    """
    创建好友请求

    Args:
        user_id: 发起请求的用户ID
        friend_id: 目标好友ID

    Returns:
        好友关系ID
    """
    friendship_id = str(uuid.uuid4())
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute('''
            INSERT INTO friendships (id, user_id, friend_id, status)
            VALUES (%s, %s, %s, 'pending')
        ''', (friendship_id, user_id, friend_id))
        conn.commit()
        return friendship_id
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def accept_friend_request(user_id: str, friend_id: str) -> bool:
    """
    接受好友请求

    Args:
        user_id: 接受请求的用户ID
        friend_id: 发起请求的用户ID

    Returns:
        是否成功
    """
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute('''
            UPDATE friendships
            SET status = 'accepted', updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s AND friend_id = %s AND status = 'pending'
        ''', (friend_id, user_id))
        success = cursor.rowcount > 0
        conn.commit()
        return success
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_friend_requests(user_id: str) -> List[Dict]:
    """
    获取用户的好友请求列表

    Args:
        user_id: 用户ID

    Returns:
        好友请求列表
    """
    query = '''
        SELECT f.id, f.user_id, u.username, u.full_name, u.avatar_url, f.created_at
        FROM friendships f
        JOIN users u ON f.user_id = u.id
        WHERE f.friend_id = %s AND f.status = 'pending'
        ORDER BY f.created_at DESC
    '''
    results = db.execute_query(query, (user_id,))
    return [dict(row) for row in results]


def get_friends(user_id: str) -> List[Dict]:
    """
    获取用户的好友列表

    Args:
        user_id: 用户ID

    Returns:
        好友列表
    """
    query = '''
        SELECT DISTINCT u.id, u.username, u.full_name, u.avatar_url, u.user_type
        FROM users u
        WHERE u.id IN (
            SELECT friend_id FROM friendships WHERE user_id = %s AND status = 'accepted'
            UNION
            SELECT user_id FROM friendships WHERE friend_id = %s AND status = 'accepted'
        )
        ORDER BY u.username
    '''
    results = db.execute_query(query, (user_id, user_id))
    return [dict(row) for row in results]


def get_users_by_relationship(user_id: str, relationship_type: str) -> List[Dict]:
    """
    根据关系获取用户列表（使用friendships表）

    Args:
        user_id: 用户ID
        relationship_type: 'parent' - 获取已接受的好友列表

    Returns:
        用户列表
    """
    if relationship_type == 'parent' or relationship_type == 'friends':
        # 获取已接受的好友
        query = '''
            SELECT u.* FROM users u
            WHERE u.id IN (
                SELECT friend_id FROM friendships WHERE user_id = %s AND status = 'accepted'
                UNION
                SELECT user_id FROM friendships WHERE friend_id = %s AND status = 'accepted'
            )
            AND u.user_type = 'human'
            ORDER BY u.username
        '''
    else:
        raise ValueError(f"Invalid relationship_type: {relationship_type}")

    results = db.execute_query(query, (user_id, user_id))
    return [dict(row) for row in results]


def get_friendship_status(user_id: str, friend_id: str) -> Optional[str]:
    """
    获取好友关系状态

    Args:
        user_id: 用户ID
        friend_id: 好友ID

    Returns:
        好友状态 (pending, accepted, blocked, None)
    """
    query = '''
        SELECT status FROM friendships
        WHERE (user_id = %s AND friend_id = %s) OR (user_id = %s AND friend_id = %s)
        LIMIT 1
    '''
    result = db.execute_query(query, (user_id, friend_id, friend_id, user_id), "one")
    return result['status'] if result else None

# ==================== 好友相关模型 ====================

class FriendRequest(BaseModel):
    """好友请求模型"""
    friend_username: str

class FriendActionRequest(BaseModel):
    """好友操作请求模型"""
    friend_username: str
    action: str  # accept, reject

# ==================== 好友管理接口 ====================

@router.post("/friends/request")
async def send_friend_request(
    request: FriendRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """发送好友请求"""
    try:
        # 查找目标用户
        friend_user = db.get_user_by_username(request.friend_username)
        if not friend_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="目标用户不存在"
            )

        # 检查是否是AI智能体
        if friend_user['user_type'] == 'ai':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能添加AI智能体为好友"
            )

        # 检查是否是自己
        if friend_user['id'] == current_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能添加自己为好友"
            )

        # 检查好友关系状态
        existing_status = get_friendship_status(current_user_id, friend_user['id'])
        if existing_status:
            if existing_status == 'accepted':
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="已经是好友关系"
                )
            elif existing_status == 'pending':
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="好友请求已发送，请等待对方同意"
                )

        # 创建好友请求
        friendship_id = create_friend_request(current_user_id, friend_user['id'])

        return {
            "status": "success",
            "message": "好友请求已发送",
            "friendship_id": friendship_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"发送好友请求失败: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="发送好友请求失败"
        )

@router.post("/friends/action")
async def handle_friend_request(
    request: FriendActionRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """处理好友请求（接受/拒绝）"""
    try:
        # 查找发送请求的用户
        requester_user = db.get_user_by_username(request.friend_username)
        if not requester_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        if request.action == "accept":
            # 接受好友请求
            success = accept_friend_request(current_user_id, requester_user['id'])
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="没有待处理的好友请求"
                )
            return {
                "status": "success",
                "message": "已接受好友请求"
            }
        elif request.action == "reject":
            # 拒绝好友请求（删除pending状态的记录）
            query = '''
                DELETE FROM friendships
                WHERE user_id = %s AND friend_id = %s AND status = 'pending'
            '''
            cursor = db._get_connection().cursor()
            try:
                cursor.execute(query, (requester_user['id'], current_user_id))
                success = cursor.rowcount > 0
                cursor.connection.commit()
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="没有待处理的好友请求"
                    )
                return {
                    "status": "success",
                    "message": "已拒绝好友请求"
                }
            finally:
                cursor.connection.close()
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的操作类型"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"处理好友请求失败: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="处理好友请求失败"
        )

@router.get("/friends/requests")
async def get_friend_requests(
    current_user_id: str = Depends(get_current_user_id)
):
    """获取好友请求列表"""
    try:
        requests = get_friend_requests(current_user_id)
        return {
            "status": "success",
            "requests": requests,
            "total": len(requests)
        }
    except Exception as e:
        print(f"获取好友请求失败: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取好友请求失败"
        )

@router.get("/friends")
async def get_friends_list(
    current_user_id: str = Depends(get_current_user_id)
):
    """获取好友列表"""
    try:
        # 获取好友
        friends = get_friends(current_user_id)

        # 获取用户的AI智能体也加入好友列表
        ai_agents = db.get_ai_agents_by_owner(current_user_id)

        # 合并好友和AI智能体列表
        all_contacts = []

        # 添加普通好友
        for friend in friends:
            all_contacts.append({
                "id": friend['id'],
                "username": friend['username'],
                "full_name": friend['full_name'],
                "avatar_url": friend['avatar_url'],
                "user_type": friend['user_type'],
                "contact_type": "friend"
            })

        # 添加AI智能体
        for agent in ai_agents:
            all_contacts.append({
                "id": agent['id'],
                "username": agent['username'],
                "full_name": agent['full_name'],
                "avatar_url": None,
                "user_type": "ai",
                "contact_type": "ai_agent"
            })

        return {
            "status": "success",
            "contacts": all_contacts,
            "total_friends": len(friends),
            "total_agents": len(ai_agents),
            "total": len(all_contacts)
        }

    except Exception as e:
        print(f"获取好友列表失败: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取好友列表失败"
        )
