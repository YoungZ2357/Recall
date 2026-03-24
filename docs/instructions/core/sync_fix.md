## chunk_manager.py 改造指令

以下是 `app/core/chunk_manager.py` 的必要修复项和优化项。按优先级排列，P0 为运行时必崩项，P1 为逻辑错误，P2 为代码质量。

---

### P0-1: Qdrant Filter 构造方式错误

**位置：** `_layer1_fast_check` 和 `_layer2_full_check` 中的 `qdrant_filter` 构造

**现状：** 使用 dict 字面量，运行时会触发 Pydantic validation error

```python
# 错误
qdrant_filter = Filter(must=[{"key": "document_id", "match": {"value": doc_id}}])
```

**改为：**

```python
from qdrant_client.models import FieldCondition, MatchValue

qdrant_filter = Filter(
    must=[
        FieldCondition(key="document_id", match=MatchValue(value=doc_id))
    ]
)
```

在文件顶部 import 块中添加 `FieldCondition` 和 `MatchValue`。两处都要改。

---

### P0-2: SyncError 构造签名不匹配

**位置：** `transition_status` 和 `health_check_with_auto_dirty` 中的 `SyncError` 调用

**现状：** 传入了 `doc_id=doc_id`，但 `SyncError` 继承链上没有 `doc_id` 参数（`SyncError → ChunkManagerError → RecallError`，构造函数只有 `message` 和 `detail`）

**两种修法选其一：**

方案 A（推荐）：在 `exceptions.py` 中为 `SyncError` 添加 `doc_id` 参数：

```python
class SyncError(ChunkManagerError):
    """Failed to sync SQLite and Qdrant"""
    message = "Failed to sync data"

    def __init__(
        self,
        doc_id: str | None = None,
        **kwargs,
    ) -> None:
        msg = f"Failed to sync data (doc_id={doc_id})" if doc_id else None
        super().__init__(message=msg, **kwargs)
        self.doc_id = doc_id
```

方案 B：调用时去掉 `doc_id`，将信息合并到 `detail` 中：

```python
raise SyncError(detail=f"doc_id={doc_id}: Failed to update sync_status to {target_status}: {e}")
```

---

### P1-1: health_check_with_auto_dirty 对非 SYNCED 状态触发非法转换

**位置：** `health_check_with_auto_dirty` 的 `except HealthCheckError` 分支

**现状：** 无条件尝试 `transition_status → DIRTY`。如果文档当前状态为 PENDING，`PENDING → DIRTY` 不在合法转换表中，会抛出 `InvalidSyncStatusTransitionError`，掩盖原始的健康检查失败信息。

**改为：** 根据当前状态选择目标状态

```python
except HealthCheckError as e:
    logger.warning(f"Health check failed for document {doc_id}: {e}")
    try:
        doc = await cls._get_document(session, doc_id)
        if doc.sync_status == SyncStatus.SYNCED:
            await cls.transition_status(session, doc_id, SyncStatus.DIRTY)
        elif doc.sync_status == SyncStatus.PENDING:
            await cls.transition_status(session, doc_id, SyncStatus.FAILED)
        # DIRTY 和 FAILED 状态下不做额外转换
    except Exception as transition_error:
        logger.error(
            f"Failed to update status for document {doc_id} "
            f"after health check failure: {transition_error}"
        )
        raise SyncError(
            doc_id=doc_id,
            detail=f"Health check failed and status update failed: {e}"
        ) from e
    raise  # 始终 re-raise 原始 HealthCheckError
```

---

### P1-2: SyncStatus 枚举大小写不统一

**位置：** `_validate_transition` 中使用 `SyncStatus.pending`，其他地方使用 `SyncStatus.dirty` 等

**要求：** 在 `models.py` 中定义枚举时统一为大写成员名 + 小写 value：

```python
from enum import Enum

class SyncStatus(str, Enum):
    PENDING = "pending"
    SYNCED  = "synced"
    DIRTY   = "dirty"
    FAILED  = "failed"
```

然后 `chunk_manager.py` 全文替换：
- `SyncStatus.pending` → `SyncStatus.PENDING`
- `SyncStatus.synced` → `SyncStatus.SYNCED`
- `SyncStatus.dirty` → `SyncStatus.DIRTY`
- `SyncStatus.failed` → `SyncStatus.FAILED`

---

### P2-1: _get_document 中的延迟导入改为顶部导入

**位置：** `_get_document` 方法内部

**现状：**

```python
@staticmethod
async def _get_document(session: AsyncSession, doc_id: str) -> Document:
    from app.core.exceptions import DocumentNotFoundError  # 延迟导入
    ...
```

**改为：** 删除方法内的 import，在文件顶部 import 块中添加 `DocumentNotFoundError`：

```python
from app.core.exceptions import (
    ChunkCountMismatchError,
    ChunkIDMismatchError,
    DocumentNotFoundError,        # 新增
    InvalidSyncStatusTransitionError,
    HealthCheckError,
    SyncError,
)
```

---

### P2-2: health_check 的 level 参数语义化

**位置：** `health_check` 和 `health_check_with_auto_dirty` 的 `level` 参数

**现状：** `level: int = 2`，1 和 2 的含义需要查注释才能理解

**改为：** 使用 Literal 类型

```python
from typing import Literal

HealthCheckLevel = Literal["fast", "full"]
```

方法签名改为：

```python
async def health_check(
    cls,
    session: AsyncSession,
    qdrant_service: QdrantService,
    doc_id: str,
    level: HealthCheckLevel = "full",
) -> None:
    ...
    if level == "fast":
        return
    ...
```

同步修改 `health_check_with_auto_dirty` 的签名。

---

### P2-3: health_check 返回值改为 None

**位置：** `health_check` 和 `health_check_with_auto_dirty` 的返回类型

**现状：** 返回 `bool`，但永远只返回 `True`（失败走异常），返回值无信息量

**改为：** 返回类型标注为 `None`，删除所有 `return True` 语句。调用方通过"未抛异常"判定健康检查通过。同步更新 docstring 中的 Returns 段落。

---

### 修改检查清单

完成上述改造后，确认以下事项：

- [ ] `FieldCondition` 和 `MatchValue` 已添加到顶部 import
- [ ] `DocumentNotFoundError` 已添加到顶部 import，`_get_document` 内部延迟导入已删除
- [ ] 文件内所有 `SyncStatus.xxx` 均使用大写成员名
- [ ] `SyncError` 在 `exceptions.py` 中支持 `doc_id` 参数（或调用处已调整）
- [ ] `health_check_with_auto_dirty` 在 catch 中根据当前状态选择转换目标
- [ ] `health_check` 和 `health_check_with_auto_dirty` 返回类型为 `None`
- [ ] `level` 参数使用 `Literal["fast", "full"]`
- [ ] 上述改动不影响其他模块对 `ChunkManager` 的调用（如有，同步更新调用方）