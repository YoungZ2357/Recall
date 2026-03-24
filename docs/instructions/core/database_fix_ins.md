# database.py 重构指令

对 `app/database.py` 进行以下改进：

## 1. 移除模块级副作用，改为延迟初始化
- 删除模块级直接创建的 `engine` 和 `AsyncSessionLocal`
- 改用私有变量 `_engine` 和 `_session_factory`，初始值为 `None`
- 提供 `get_engine()` 和 `get_session_factory()` 函数实现延迟初始化
- 确保 `import database` 时不会触发任何连接创建或配置读取

## 2. 添加引擎清理函数
- 新增 `async def dispose_engine() -> None`，调用 `await engine.dispose()` 并将 `_engine` 和 `_session_factory` 重置为 `None`
- 该函数应在应用关闭时（如 FastAPI lifespan 的 shutdown 阶段）调用

## 3. 清理 get_async_session 中的冗余代码
- 移除 `finally` 块中的 `await session.close()`，因为 `async with AsyncSessionLocal()` 退出时已自动关闭 session

## 4. 新增 FastAPI 依赖注入兼容函数
- 新增 `async def get_session() -> AsyncGenerator[AsyncSession, None]`，使用 `yield` 而非 `@asynccontextmanager`，使其可直接用于 `Depends(get_session)`
- 保留原有的 `get_async_session()` 上下文管理器供非 FastAPI 场景使用

## 约束
- 不修改 `Base` 类定义
- 不修改 `create_async_engine_from_settings()` 的内部逻辑
- 保留所有类型注解和文档字符串风格
- `create_tables()` 和 `drop_tables()` 改为使用 `get_engine()` 获取引擎