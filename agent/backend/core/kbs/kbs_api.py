"""
知识库记忆 API
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.auth_filter import get_current_user_id
from . import service


router = APIRouter(prefix="/api/v1/kbs", tags=["kbs"])


class MemoryAddRequest(BaseModel):
    memory_type: str
    title: Optional[str] = None
    content: str
    is_public: int = 0


class MemoryQueryRequest(BaseModel):
    content: str
    topk: int = 10


class MemoryUpdateRequest(BaseModel):
    memory_type: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    is_public: Optional[int] = None
    status: Optional[int] = None


@router.post("/add")
async def add_memory(
    payload: MemoryAddRequest,
    user_id: str = Depends(get_current_user_id),
):
    if not payload.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content 不能为空",
        )
    if not payload.memory_type.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="memory_type 不能为空",
        )

    try:
        row = await service.add_memory(
            user_id=user_id,
            memory_type=payload.memory_type.strip(),
            title=payload.title,
            content=payload.content,
            is_public=payload.is_public,
        )
        return {"success": True, "memory": row}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"保存记忆失败: {exc}")


@router.post("/query")
async def query_memory(
    payload: MemoryQueryRequest,
    user_id: str = Depends(get_current_user_id),
):
    query_text = payload.content.strip()
    if not query_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content 不能为空",
        )
    topk = max(1, min(payload.topk, 50))
    try:
        results = await service.query_memory(user_id=user_id, content=query_text, topk=topk)
        return {"success": True, "results": results}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"查询失败: {exc}")


@router.put("/{memory_id}")
async def update_memory(
    memory_id: str,
    payload: MemoryUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        updated = await service.update_memory(
            user_id=user_id,
            memory_id=memory_id,
            memory_type=payload.memory_type.strip() if payload.memory_type is not None else None,
            title=payload.title,
            content=payload.content,
            is_public=payload.is_public,
            status=payload.status,
        )
        return {"success": True, "memory": updated}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"更新记忆失败: {exc}")


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        await service.delete_memory(user_id=user_id, memory_id=memory_id)
        return {"success": True}
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"删除记忆失败: {exc}")
