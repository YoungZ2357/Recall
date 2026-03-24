## 文档级重置索引
该类操作的目的是：同模型，修复、刷新chunk

重置索引（文档级）包含如下的步骤：
1. 输入校验：确认目标Document存在，获取其所有的Chunk记录
2. 批量标记DIRTY：将所有相关的chunk的sync_status标记为DIRTY(SQLite事务)
3. 分批处理(batch_size, 默认为100)：
    1. 取一批DIRTY chunk的文本
    2. 调用embedder生成新向量
    3. upsert到Qdrant（相同chunk_id覆盖写入）
    4. 重新标记对应的chunk为; DIRTY -> SYNCED
    5. 若失败，重新标记为 DIRTY -> FAILED，记录错误信息，继续下一批
4. 对对应的document_id进行health_check(level="full")
5. 返回报告：成功数、失败数、失败chunk_id列表

## 模型级重置索引
该类操作的目的是：更换嵌入模型，重建向量空间

1. 输入校验：确认新Embedder可用(API联通，或者模型文件存在)，获取新模型维度
2. 维度决策：比较新维度与当前collection的维度
    - 若匹配，对所有的document执行文档级重置索引
    - 若不匹配，需要重建collection，进行接下来的步骤
3. 批量标记DIRTY：将所有相关的chunk的sync_status标记为DIRTY(SQLite事务)
4. 重建collection: 删除旧collection，以新维度创建新collection
5. 分批处理：和文档级相同，遍历 DIRTY chunk，逐批次嵌入 -> upsert ->标记SYNCED/FAILED
6. 对所有的嵌入进行health_check(level="full")
7. 更新config中当前模型的标识，方式下次启动时模型信息与实际向量不匹配