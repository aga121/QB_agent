"""
Knowledge Base (Memory) MCP
提供记忆的增删改查
"""
from claude_agent_sdk import create_sdk_mcp_server, tool

from ..kbs import service
from ..system import config


@tool(
    name="kbs_add_memory",
    description=(
        "新增记忆。参数：user_id, memory_type(如 经验/教训/偏好/规则/踩坑/记忆), "
        "content, title(可选), is_public(0/1,可选).默认0仅自己可见。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "memory_type": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "is_public": {"type": "integer"},
            "public_password": {"type": "string"},
        },
        "required": ["user_id", "memory_type", "content"],
    },
)
async def kbs_add_memory(args: dict) -> dict:
    try:
        is_public = int(args.get("is_public") or 0)
        if is_public == 1:
            public_password = (args.get("public_password") or "").strip()
            if not public_password:
                return {"content": [{"type": "text", "text": "公开记忆需要密码"}]}
            if not config.KB_PUBLIC_PASSWORD or public_password != config.KB_PUBLIC_PASSWORD:
                return {"content": [{"type": "text", "text": "公开记忆密码错误"}]}
        row = await service.add_memory(
            user_id=(args.get("user_id") or "").strip(),
            memory_type=(args.get("memory_type") or "").strip(),
            title=args.get("title"),
            content=(args.get("content") or "").strip(),
            is_public=is_public,
        )
        return {"content": [{"type": "text", "text": f"新增记忆成功: {row.get('id')}"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"新增记忆失败: {exc}"}]}


@tool(
    name="kbs_update_memory",
    description=(
        "更新记忆。参数：user_id, memory_id, 可选 memory_type/title/content/is_public/status。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "memory_type": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "is_public": {"type": "integer"},
            "status": {"type": "integer"},
        },
        "required": ["user_id", "memory_id"],
    },
)
async def kbs_update_memory(args: dict) -> dict:
    try:
        await service.update_memory(
            user_id=(args.get("user_id") or "").strip(),
            memory_id=(args.get("memory_id") or "").strip(),
            memory_type=args.get("memory_type"),
            title=args.get("title"),
            content=args.get("content"),
            is_public=int(args.get("is_public")) if args.get("is_public") is not None else None,
            status=int(args.get("status")) if args.get("status") is not None else None,
        )
        return {"content": [{"type": "text", "text": "更新成功"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"更新失败: {exc}"}]}


@tool(
    name="kbs_delete_memory",
    description=(
        "删除记忆。参数：user_id, memory_id。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
        },
        "required": ["user_id", "memory_id"],
    },
)
async def kbs_delete_memory(args: dict) -> dict:
    try:
        await service.delete_memory(
            user_id=(args.get("user_id") or "").strip(),
            memory_id=(args.get("memory_id") or "").strip(),
        )
        return {"content": [{"type": "text", "text": "删除成功"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"删除失败: {exc}"}]}


@tool(
    name="kbs_query_memory",
    description=(
        "查询记忆。参数：user_id, content, topk(默认10)。若启用向量则按语义+关键词55/45排序，"
        "否则仅关键词排序。提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "content": {"type": "string"},
            "topk": {"type": "integer"},
        },
        "required": ["user_id", "content"],
    },
)
async def kbs_query_memory(args: dict) -> dict:
    try:
        results = await service.query_memory(
            user_id=(args.get("user_id") or "").strip(),
            content=(args.get("content") or "").strip(),
            topk=int(args.get("topk") or 10),
        )
        lines = [f"共 {len(results)} 条结果："] 
        for row in results:
            lines.append(
                f"- {row.get('id')} | {row.get('memory_type')} | {row.get('title') or ''}\n"
                f"  相似度:{(row.get('semantic_score') or 0):.4f} 关键词:{(row.get('keyword_score') or 0):.4f} 综合:{(row.get('final_score') or 0):.4f}\n"
                f"  {row.get('content') or ''}"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"查询失败: {exc}"}]}


@tool(
    name="kbs_add_memory_batch",
    description=(
        "批量新增记忆。参数：items[{user_id, memory_type, content, title?, is_public?}]。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "memory_type": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "is_public": {"type": "integer"},
                    },
                    "required": ["user_id", "memory_type", "content"],
                },
            }
        },
        "required": ["items"],
    },
)
async def kbs_add_memory_batch(args: dict) -> dict:
    try:
        items = args.get("items") or []
        if len(items) > 50:
            return {"content": [{"type": "text", "text": "批量新增最多支持 50 条"}]}
        results = await service.add_memory_batch(items=items)
        ok = sum(1 for r in results if r.get("ok"))
        fail = len(results) - ok
        return {"content": [{"type": "text", "text": f"批量新增完成：成功 {ok} 条，失败 {fail} 条"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"批量新增失败: {exc}"}]}


@tool(
    name="kbs_update_memory_batch",
    description=(
        "批量更新记忆。参数：items[{user_id, memory_id, memory_type?, title?, content?, is_public?, status?}]。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "memory_id": {"type": "string"},
                        "memory_type": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "is_public": {"type": "integer"},
                        "status": {"type": "integer"},
                    },
                    "required": ["user_id", "memory_id"],
                },
            }
        },
        "required": ["items"],
    },
)
async def kbs_update_memory_batch(args: dict) -> dict:
    try:
        items = args.get("items") or []
        if len(items) > 50:
            return {"content": [{"type": "text", "text": "批量更新最多支持 50 条"}]}
        results = await service.update_memory_batch(items=items)
        ok = sum(1 for r in results if r.get("ok"))
        fail = len(results) - ok
        return {"content": [{"type": "text", "text": f"批量更新完成：成功 {ok} 条，失败 {fail} 条"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"批量更新失败: {exc}"}]}


@tool(
    name="kbs_delete_memory_batch",
    description=(
        "批量删除记忆。参数：user_id, memory_ids[]。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "memory_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["user_id", "memory_ids"],
    },
)
async def kbs_delete_memory_batch(args: dict) -> dict:
    try:
        user_id = (args.get("user_id") or "").strip()
        memory_ids = args.get("memory_ids") or []
        if len(memory_ids) > 50:
            return {"content": [{"type": "text", "text": "批量删除最多支持 50 条"}]}
        results = await service.delete_memory_batch(user_id=user_id, memory_ids=memory_ids)
        ok = sum(1 for r in results if r.get("ok"))
        fail = len(results) - ok
        return {"content": [{"type": "text", "text": f"批量删除完成：成功 {ok} 条，失败 {fail} 条"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"批量删除失败: {exc}"}]}


@tool(
    name="kbs_query_memory_batch",
    description=(
        "批量查询记忆。参数：user_id, queries[{content, topk?}]。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "topk": {"type": "integer"},
                    },
                    "required": ["content"],
                },
            },
        },
        "required": ["user_id", "queries"],
    },
)
async def kbs_query_memory_batch(args: dict) -> dict:
    try:
        user_id = (args.get("user_id") or "").strip()
        queries = args.get("queries") or []
        if len(queries) > 50:
            return {"content": [{"type": "text", "text": "批量查询最多支持 50 条"}]}
        results = await service.query_memory_batch(user_id=user_id, queries=queries)
        ok = sum(1 for r in results if r.get("ok"))
        fail = len(results) - ok
        return {"content": [{"type": "text", "text": f"批量查询完成：成功 {ok} 条，失败 {fail} 条"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"批量查询失败: {exc}"}]}


@tool(
    name="kbs_list_chat_fragments",
    description=(
        "查询用户主动输入的聊天信息（聊天碎片）。参数：user_id。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
)
async def kbs_list_chat_fragments(args: dict) -> dict:
    try:
        rows = await service.list_chat_fragments(
            user_id=(args.get("user_id") or "").strip(),
        )
        lines = [f"共 {len(rows)} 条聊天碎片："]
        for row in rows:
            lines.append(f"- {row.get('id')} | {row.get('created_at') or ''}\n  {row.get('content') or ''}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"查询失败: {exc}"}]}


@tool(
    name="kbs_clear_chat_fragments",
    description=(
        "清除用户主动输入的聊天信息（聊天碎片）。参数：user_id。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
)
async def kbs_clear_chat_fragments(args: dict) -> dict:
    try:
        deleted = await service.clear_chat_fragments(
            user_id=(args.get("user_id") or "").strip(),
        )
        return {"content": [{"type": "text", "text": f"已清除 {deleted} 条聊天碎片"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"清除失败: {exc}"}]}


@tool(
    name="kbs_dump_unprocessed_chat_records",
    description=(
        "将未处理聊天记录导出为 txt 文件（用于整理完整对话）。参数：user_id, output_dir(工作空间路径)。"
        "内部会读取 title='已整理记忆参数' 且 memory_type='参数' 的记忆内容作为处理进度。"
        "进度格式必须为 JSON: {\"last_created_at\": \"...\"}。"
        "整理完成后请调用 kbs_set_memory_progress 更新进度（写入当前北京时间）。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "output_dir": {"type": "string"},
        },
        "required": ["user_id", "output_dir"],
    },
)
async def kbs_dump_unprocessed_chat_records(args: dict) -> dict:
    try:
        file_path, count = await service.dump_unprocessed_chat_records(
            user_id=(args.get("user_id") or "").strip(),
            output_dir=(args.get("output_dir") or "").strip(),
        )
        return {"content": [{"type": "text", "text": f"已导出 {count} 条到: {file_path}"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"导出失败: {exc}"}]}


@tool(
    name="kbs_set_memory_progress",
    description=(
        "更新已整理记忆参数（自动使用当前北京时间）。参数：user_id。"
        "会写入 title='已整理记忆参数' 且 memory_type='参数' 的 JSON 内容。"
        "提示：user_id 可从工作目录名推导，形如 userid_xxx，去掉 userid_ 即为用户ID。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
        },
        "required": ["user_id"],
    },
)
async def kbs_set_memory_progress(args: dict) -> dict:
    try:
        result = await service.set_memory_progress_now(
            user_id=(args.get("user_id") or "").strip(),
        )
        return {"content": [{"type": "text", "text": f"更新成功: {result.get('id')}"}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"更新失败: {exc}"}]}


kbs_mcp = create_sdk_mcp_server(
    name="kbs-memory",
    version="1.0.0",
    tools=[
        kbs_add_memory,
        kbs_update_memory,
        kbs_delete_memory,
        kbs_query_memory,
        kbs_add_memory_batch,
        kbs_update_memory_batch,
        kbs_delete_memory_batch,
        kbs_query_memory_batch,
        kbs_list_chat_fragments,
        kbs_clear_chat_fragments,
        kbs_dump_unprocessed_chat_records,
        kbs_set_memory_progress,
    ],
)
