## Retrieve

### Frequency-based tag embedding cache

2026-03-18

- 提案：为 tag embedding 引入频率驱动的缓存晋升机制，仅当 tag 被命中达到阈值后才写入缓存表，维护一个较小的 tag-vector 存储
- 采用类似 SQLite ↔ Qdrant 的双轨管理，包含 sync_status 状态机和一致性保障

> 否决理由：个人知识库 unique tag 规模有限（千级，~12MB），全量缓存的存储开销可忽略，不需要频率淘汰。频率追踪会在每次搜索时引入额外写操作，与读多写少的检索系统方向相反。双轨管理适用于 Qdrant 这类外部存储的一致性场景，而 tag embedding 是纯派生数据（tag 文本 + 模型 → 向量），仅需 SQLite 单表即可，丢失可随时重算。

替代方案：ingestion 阶段全量预计算 tag embedding 并持久化到 SQLite，搜索时查表，cache miss 时 fallback API 并回填。见 backlog「Tag embedding 预计算缓存」。
