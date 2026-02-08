"""
JWT认证过滤器
用于保护需要认证的API接口
"""

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import sys
from .auth_utils import verify_token

# HTTP Bearer 认证方案
security = HTTPBearer()

async def get_current_user_id(request: Request) -> str:
    """
    从请求中获取当前用户ID

    Args:
        request: FastAPI请求对象

    Returns:
        用户ID字符串

    Raises:
        HTTPException: 认证失败时抛出异常
    """
    try:
        # 从请求头获取Authorization
        authorization = request.headers.get("authorization")

        # 如果没有Authorization，尝试从security获取
        if not authorization:
            # 这里可以添加其他获取token的方式
            pass

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少认证token",
                headers={"WWW-Authenticate": "Bearer"}
            )

        token = authorization.split(" ")[1]
        token_data = verify_token(token)

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的token或token已过期",
                headers={"WWW-Authenticate": "Bearer"}
            )

        return token_data.get('user_id')

    except HTTPException:
        raise
    except Exception as e:
        print(f"JWT认证异常: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败",
            headers={"WWW-Authenticate": "Bearer"}
        )

async def get_current_user_id_by_credentials(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    通过HTTPBearer依赖获取当前用户ID

    Args:
        credentials: HTTPAuthorizationCredentials对象

    Returns:
        用户ID字符串

    Raises:
        HTTPException: 认证失败时抛出异常
    """
    try:
        token = credentials.credentials
        token_data = verify_token(token)

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的token或token已过期",
                headers={"WWW-Authenticate": "Bearer"}
            )

        return token_data.get('user_id')

    except HTTPException:
        raise
    except Exception as e:
        print(f"JWT认证异常: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败",
            headers={"WWW-Authenticate": "Bearer"}
        )

async def get_current_user_data(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    通过HTTPBearer依赖获取当前用户的完整数据

    Args:
        credentials: HTTPAuthorizationCredentials对象

    Returns:
        用户数据字典

    Raises:
        HTTPException: 认证失败时抛出异常
    """
    try:
        token = credentials.credentials
        token_data = verify_token(token)

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的token或token已过期",
                headers={"WWW-Authenticate": "Bearer"}
            )

        return token_data

    except HTTPException:
        raise
    except Exception as e:
        print(f"JWT认证异常: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败",
            headers={"WWW-Authenticate": "Bearer"}
        )

def verify_user_id_match(request: Request, expected_user_id: str) -> bool:
    """
    验证请求中的用户ID与认证的用户ID是否匹配

    Args:
        request: FastAPI请求对象
        expected_user_id: 期望的用户ID

    Returns:
        是否匹配

    Raises:
        HTTPException: 不匹配时抛出异常
    """
    try:
        # 从Authorization获取用户ID
        authorization = request.headers.get("authorization")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少认证token"
            )

        token = authorization.split(" ")[1]
        token_data = verify_token(token)

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的token或token已过期"
            )

        actual_user_id = token_data.get('user_id')

        if actual_user_id != expected_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户身份验证失败"
            )

        return True

    except HTTPException:
        raise
    except Exception as e:
        print(f"用户ID匹配验证异常: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败"
        )