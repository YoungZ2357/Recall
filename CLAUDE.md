# Knowledge Base Retriever
## Project Overview
- Description: 一个精简的知识检索系统，重视RAG的检索部分并倾向增加对部分特殊格式的兼容，具备最基本的生成功能
- 技术栈：Python 3.11/ SQLAlchemy 2.0 (async)/ FastAPI / React-ts
- package manager: pip(backend, pyproject.toml)/ npm(frontend, package.json)
- 仓库结构：见 @README.md

## Current Stage:
- Sprint-1

完整任务表见 @docs/recall-sprint-plan.md

## Common Commands
```bash
# Qdrant docker compose up qdrant -d

# backend
cd backend
uvicorn app.main:app --reload

# frontend
cd frontend
npm install && num run dev

# activate python environment
conda activate rag_env
```
## Code Style
### Python
- **SQLAlchemy 2.0 风格**: 使用`Mapped[]` 类型注解、`mapped_column()`、`relationship()` 从类型注解推断目标类
- **全栈 async/await**: 数据库使用aiosqlite, HTTP 用httpx.AsyncClient, FastAPI路由全部 async def
-  **类型注解优先**：所有函数签名标注参数类型和返回类型
- **Pydantic 做数据校验**：请求/响应模型与 ORM 模型分离（schemas.py vs models.py）
- **datetime 使用 timezone-aware**：`datetime.now(timezone.utc)`，不用已废弃的 `datetime.utcnow()`
- 不使用`__init__.py`进行re-export，使用完整路径
### 命名规范

| 类别 | 风格 | 示例 |
|------|------|------|
| Python 文件 / 变量 / 函数 | snake_case | `chunk_manager.py`, `get_document_by_id()` |
| Python 类 | PascalCase | `ChunkManager`, `APIEmbedder` |
| 常量 | UPPER_SNAKE_CASE | `MAX_CHUNK_SIZE`, `DEFAULT_TOP_K` |
| TS 文件 | kebab-case | `document-list.tsx` |
| TS 变量 / 函数 | camelCase | `fetchDocuments()` |
| TS 组件 / 类型 | PascalCase | `DocumentList`, `SearchResult` |


### 错误处理

- 自定义异常类（`exceptions.py`），通过 FastAPI exception handler 统一转 HTTP 响应
- 异步操作用 try/except，使用 `logging` 记录日志，不用 `print`
- Qdrant / SQLite 操作失败时，`chunk_manager` 负责状态回滚或标记 dirty

## Hard Rules

> **以下规则最高优先级，不可违反。**

1. **数据一致性**：文档的增删改必须通过 `chunk_manager.py` 协调 SQLite 和 Qdrant，不得绕过
2. **SQLite 是 Source of Truth**，Qdrant 是可重建的派生存储。最坏情况下可以从 SQLite 完全重建 Qdrant
3. **共享主键**：chunk_id 使用 UUID，作为 SQLite 和 Qdrant 的共享主键
4. **嵌入模型追踪**：切换模型时必须记录 `embedding_model` 字段并触发重新嵌入，不同维度的向量不得混入同一 collection
5. **敏感信息**：API key 等只能通过环境变量获取，禁止硬编码
6. **数据库访问**：通过 SQLAlchemy ORM，不写裸 SQL
7. **不修改已有测试**，除非明确要求

## AI Interaction Preferences
沟通风格
- 回复语言：中文
- 代码注释语言：English
- 解释详细度：简洁，必要时展开
- 不确定时向我提问，不要猜测
- 对我提供的代码进行批判性分析，发现错误直接指出
工作流约束
- 先计划后编码，在我明确确认方案之前，不要编码
- 只编写我明确提及的部分，不主动添加未要求的功能