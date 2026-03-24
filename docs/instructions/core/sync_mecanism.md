## Document Sync Status 状态机

### 状态定义

| 状态 | 含义 |
|------|------|
| `pending` | 文档元数据已写入 SQLite，尚未执行 ingestion（未分块、未嵌入、未写入 Qdrant） |
| `synced` | ingestion 完成，健康检查通过，SQLite 与 Qdrant 数据一致 |
| `dirty` | 已知与 Qdrant 不一致，需要重新同步。触发来源：健康检查失败 **或** 主动 reindex |
| `failed` | ingestion 或健康检查过程中发生不可自动恢复的异常 |

状态字段为 `Document.sync_status`，使用字符串枚举（建议定义 `SyncStatus(str, Enum)`）。

### 合法状态转换

```
Pending ──(ingestion 成功)──→ Synced
Pending ──(ingestion 异常)──→ Failed
Synced  ──(健康检查失败)───→ Dirty
Synced  ──(reindex 触发)───→ Dirty
Dirty   ──(re-sync 成功)───→ Synced
Dirty   ──(re-sync 异常)───→ Failed
Failed  ──(retry / 手动修复)→ Pending
```

**任何不在上述列表中的转换都是非法的**，必须抛出 `InvalidSyncStatusTransitionError`。
在 `chunk_manager` 中实现状态转换时，先校验合法性再执行写入。

### 健康检查规则（分层执行）

健康检查针对单个 Document 执行，目的是验证 SQLite（source of truth）与 Qdrant（derived store）的一致性。

**Layer 1 — 快检（chunk 数量比较）：**
- 从 SQLite 查询 `SELECT COUNT(*) FROM chunks WHERE doc_id = :doc_id`
- 从 Qdrant 按 `doc_id` filter 做 scroll count
- 数量不匹配 → 抛出 `ChunkCountMismatchError` → 标记 `dirty`
- 数量匹配 → 继续 Layer 2
- **注意**：数量匹配是必要不充分条件（可能存在孤儿向量恰好补齐了数量差）

**Layer 2 — 全检（逐 chunk UUID 双向差集）：**
- 从 SQLite 取该 Document 下所有 `chunk_id` 集合 S
- 从 Qdrant scroll 出同一 `doc_id` 下所有 `point_id` 集合 Q
- 计算 `missing_in_qdrant = S - Q`（SQLite 有但 Qdrant 缺失）
- 计算 `orphaned_in_qdrant = Q - S`（Qdrant 有但 SQLite 无）
- 任一非空 → 抛出 `ChunkIDMismatchError`（携带差集信息）→ 标记 `dirty`
- 两者均为空 → 检查通过

### 异常层级

```
RecallError
└── ChunkManagerError                   # chunk_manager 协调异常基类
    ├── SyncError                       # SQLite ↔ Qdrant 同步写入失败
    ├── InvalidSyncStatusTransitionError # 非法状态转换（409）
    └── HealthCheckError                # 健康检查未通过基类（409）
        ├── ChunkCountMismatchError     # Layer 1 快检失败
        └── ChunkIDMismatchError        # Layer 2 全检失败
```

### 实现约定

- 状态转换逻辑集中在 `chunk_manager.py`，不要分散到 API 层或 ingestion 层
- 健康检查方法签名建议：`async def health_check(self, doc_id: str) -> bool`，内部按 Layer 1 → Layer 2 顺序执行，失败时抛出对应异常
- 调用方（API / CLI）负责 catch 异常并决定是否执行自动 re-sync 或只是标记状态
- `HealthCheckError` 子类都携带 `doc_id`，方便上层日志和错误响应定位
- `ChunkIDMismatchError` 携带 `missing_in_qdrant` 和 `orphaned_in_qdrant` 差集，可用于增量修复而非全量重建
- Qdrant scroll 时注意分页：单次 scroll limit 有上限，大文档需要循环取完