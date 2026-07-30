# 异步/同步冲突问题修复文档

**日期**: 2025-10-26  
**问题类型**: 数据库调用异步/同步冲突  
**严重程度**: 高（导致数据源降级功能失败）

---

## 📋 问题描述

### 错误信息

```
⚠️ [数据源优先级] 从数据库读取失败: '_asyncio.Future' object has no attribute 'get'，使用默认顺序
```

### 触发场景

当数据源（如 MongoDB）获取数据失败时，系统尝试降级到其他数据源（AKShare、Tushare、BaoStock），在读取数据源优先级配置时出现错误。

### 影响范围

- ✅ 数据源降级功能
- ✅ 数据源优先级配置
- ✅ 所有需要从数据库读取数据源配置的场景
- ✅ 历史数据获取
- ✅ 基本面数据获取
- ✅ 新闻数据获取

---

## 🔍 根本原因分析

### 问题 1: 异步/同步类型不匹配

**位置**: `lahm/dataflows/data_source_manager.py:90-100`

**错误代码**:
```python
# ❌ 错误：在同步方法中使用异步数据库客户端
from app.core.database import get_mongo_db
db = get_mongo_db()  # 返回 AsyncIOMotorDatabase
config_collection = db.system_configs

# 同步调用异步方法，返回 Future 对象而不是实际数据
config_data = config_collection.find_one(...)  # 返回 _asyncio.Future
```

**问题**:
- `get_mongo_db()` 返回 `AsyncIOMotorDatabase`（异步数据库）
- `find_one()` 是异步方法，需要 `await`
- 在同步上下文中调用，返回 `_asyncio.Future` 对象
- 后续代码尝试访问 `.get()` 方法，导致 `AttributeError`

### 问题 2: 调用链全部是同步的

**调用链分析**:

```
同步方法调用链：
├── get_stock_data() [同步]
│   └── _try_fallback_sources() [同步]
│       └── _get_data_source_priority_order() [同步]
│           └── get_mongo_db() [❌ 异步]
│
├── get_fundamentals_data() [同步]
│   └── _try_fallback_fundamentals() [同步]
│       └── _get_data_source_priority_order() [同步]
│           └── get_mongo_db() [❌ 异步]
│
└── get_news_data() [同步]
    └── _try_fallback_news() [同步]
        └── _get_data_source_priority_order() [同步]
            └── get_mongo_db() [❌ 异步]
```

**结论**: 整个调用链都是同步的，但在最底层使用了异步数据库客户端。

---

## ✅ 解决方案

### 修复策略

使用 **同步 MongoDB 客户端** `get_mongo_db_sync()` 替代异步客户端 `get_mongo_db()`。

### 修复代码

**文件**: `lahm/dataflows/data_source_manager.py`

**修改位置**: 第 90-93 行

```python
# 修复前
from app.core.database import get_mongo_db
db = get_mongo_db()  # 返回 AsyncIOMotorDatabase

# 修复后
from app.core.database import get_mongo_db_sync
db = get_mongo_db_sync()  # 返回 pymongo.Database（同步）
```

### 为什么这样修复？

1. **`get_mongo_db_sync()` 返回同步客户端**
   - 类型: `pymongo.Database`
   - 方法: 同步方法（`find_one()` 直接返回结果）
   - 适用场景: 同步上下文（普通函数、线程池）

2. **`get_mongo_db()` 返回异步客户端**
   - 类型: `motor.motor_asyncio.AsyncIOMotorDatabase`
   - 方法: 异步方法（`find_one()` 返回 coroutine，需要 `await`）
   - 适用场景: 异步上下文（`async def` 函数）

3. **调用链全部是同步的**
   - 所有调用方法都是普通函数（`def`），不是异步函数（`async def`）
   - 无法使用 `await` 关键字
   - 必须使用同步数据库客户端

---

## 📊 修复效果

### 修复前

```
⚠️ [数据来源: MongoDB] 未找到daily数据: 002241，降级到其他数据源
❌ mongodb失败，尝试备用数据源获取daily数据...
⚠️ [数据源优先级] 从数据库读取失败: '_asyncio.Future' object has no attribute 'get'，使用默认顺序
✅ [数据来源: 备用数据源] 降级成功获取daily数据: akshare
```

**问题**:
- ❌ 无法从数据库读取数据源优先级配置
- ❌ 降级到硬编码的默认顺序（AKShare > Tushare > BaoStock）
- ❌ 用户在 Web 后台配置的数据源优先级不生效

### 修复后

```
⚠️ [数据来源: MongoDB] 未找到daily数据: 002241，降级到其他数据源
❌ mongodb失败，尝试备用数据源获取daily数据...
✅ [数据源优先级] 市场=A股, 从数据库读取: ['akshare', 'tushare', 'baostock']
✅ [数据来源: 备用数据源] 降级成功获取daily数据: akshare
```

**效果**:
- ✅ 成功从数据库读取数据源优先级配置
- ✅ 按照用户配置的优先级顺序降级
- ✅ 支持按市场分类（A股/美股/港股）配置不同的数据源优先级
- ✅ 用户在 Web 后台的配置立即生效

---

## 🔧 相关代码

### `app/core/database.py`

提供两种 MongoDB 客户端：

```python
# 异步客户端（用于 FastAPI 异步路由）
def get_mongo_db() -> AsyncIOMotorDatabase:
    """获取MongoDB数据库实例（异步）"""
    if mongo_db is None:
        raise RuntimeError("MongoDB数据库未初始化")
    return mongo_db

# 同步客户端（用于普通函数、线程池）
def get_mongo_db_sync() -> Database:
    """
    获取同步版本的MongoDB数据库实例
    用于非异步上下文（如普通函数调用）
    """
    global _sync_mongo_client, _sync_mongo_db

    if _sync_mongo_db is not None:
        return _sync_mongo_db

    # 创建同步 MongoDB 客户端
    if _sync_mongo_client is None:
        _sync_mongo_client = MongoClient(
            settings.MONGO_URI,
            maxPoolSize=settings.MONGO_MAX_CONNECTIONS,
            minPoolSize=settings.MONGO_MIN_CONNECTIONS,
            maxIdleTimeMS=30000,
            serverSelectionTimeoutMS=5000
        )

    _sync_mongo_db = _sync_mongo_client[settings.MONGO_DB]
    return _sync_mongo_db
```

### 使用场景对比

| 场景 | 使用客户端 | 示例 |
|------|-----------|------|
| FastAPI 异步路由 | `get_mongo_db()` | `async def get_stocks(db: AsyncIOMotorDatabase = Depends(get_mongo_db))` |
| 普通函数 | `get_mongo_db_sync()` | `def _get_data_source_priority_order(self)` |
| 线程池任务 | `get_mongo_db_sync()` | `executor.submit(sync_function)` |
| 后台任务 | `get_mongo_db_sync()` | `scheduler.add_job(sync_function)` |

---

## 🎯 关键教训

### 1. 异步/同步类型必须匹配

```python
# ❌ 错误：在同步函数中使用异步客户端
def sync_function():
    db = get_mongo_db()  # AsyncIOMotorDatabase
    result = db.collection.find_one({})  # 返回 Future，不是实际数据

# ✅ 正确：在同步函数中使用同步客户端
def sync_function():
    db = get_mongo_db_sync()  # pymongo.Database
    result = db.collection.find_one({})  # 直接返回数据

# ✅ 正确：在异步函数中使用异步客户端
async def async_function():
    db = get_mongo_db()  # AsyncIOMotorDatabase
    result = await db.collection.find_one({})  # 使用 await 获取数据
```

### 2. 检查整个调用链

修复异步/同步问题时，需要检查整个调用链：
- 如果调用链中有任何一个是同步函数，就必须使用同步客户端
- 如果调用链全部是异步函数，才能使用异步客户端

### 3. 错误信息的识别

看到以下错误信息时，通常是异步/同步冲突：
- `'_asyncio.Future' object has no attribute 'xxx'`
- `'coroutine' object has no attribute 'xxx'`
- `RuntimeError: There is no current event loop in thread`

---

## 📝 测试建议

### 1. 功能测试

```bash
# 测试数据源降级功能
python -m pytest tests/test_data_source_fallback.py -v

# 测试数据源优先级配置
python -m pytest tests/test_data_source_priority.py -v
```

### 2. 集成测试

1. 在 Web 后台配置数据源优先级
2. 停止 MongoDB 服务，触发降级
3. 查看日志，确认按照配置的优先级降级
4. 验证数据获取成功

### 3. 日志验证

修复后应该看到：
```
✅ [数据源优先级] 市场=A股, 从数据库读取: ['akshare', 'tushare', 'baostock']
```

而不是：
```
⚠️ [数据源优先级] 从数据库读取失败: '_asyncio.Future' object has no attribute 'get'，使用默认顺序
```

---

## 🔗 相关问题

### 已修复的类似问题

1. **线程池中的事件循环错误** (`docs/fixes/asyncio_thread_pool_fix.md`)
   - 问题: 在线程池中调用异步方法
   - 修复: 在线程池中创建新的事件循环

2. **Tushare Token 配置优先级问题** (`docs/bugfix/2025-10-26-tushare-token-priority-issue.md`)
   - 问题: 配置优先级错误
   - 修复: 修改配置读取顺序

### 预防措施

1. **代码审查**: 检查异步/同步类型匹配
2. **类型注解**: 使用类型注解明确标注异步/同步
3. **单元测试**: 覆盖同步和异步两种场景
4. **日志监控**: 监控异步/同步相关错误

---

**修复完成日期**: 2025-10-26  
**Git 提交**: `da3406b`  
**审核状态**: 待用户验证

