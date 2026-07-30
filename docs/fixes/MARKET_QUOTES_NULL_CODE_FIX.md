# Market Quotes Code 字段 Null 值修复指南

## 问题描述

### 错误信息
```
E11000 duplicate key error collection: lahm.market_quotes 
index: code_1 dup key: { code: null }
```

### 根本原因

1. **`market_quotes` 集合有 `code_1` 唯一索引**
2. **更新行情时只设置了 `symbol` 字段，没有设置 `code` 字段**
3. **导致 `code` 字段为 `null`**
4. **MongoDB 唯一索引不允许多个 `null` 值**，第二次插入时冲突

### 历史原因

- **旧版本**：使用 `code` 字段作为主键
- **新版本**：改用 `symbol` 字段作为主键
- **遗留问题**：数据库中的唯一索引还是 `code_1`

---

## 修复方案

### 1. 代码修复（已完成）

**文件**：`app/services/stock_data_service.py`

**修改**：`update_market_quotes()` 方法

```python
# 修改前
if "symbol" not in quote_data:
    quote_data["symbol"] = symbol6

# 修改后
if "symbol" not in quote_data:
    quote_data["symbol"] = symbol6
if "code" not in quote_data:
    quote_data["code"] = symbol6  # 兼容旧索引
```

**效果**：
- ✅ 确保每次更新时 `code` 和 `symbol` 字段都存在
- ✅ 避免插入 `code=null` 的记录
- ✅ 保持向后兼容

---

### 2. 数据修复（需要手动执行）

**脚本**：`scripts/fix_market_quotes_null_code.py`

#### 功能

1. 统计 `code=null` 的记录数
2. 查询所有 `code=null` 的记录
3. 如果有 `symbol`，将 `code` 设置为 `symbol`
4. 如果没有 `symbol`，删除记录
5. 验证修复结果

#### 使用方法

```bash
# 方法 1：直接运行脚本
python scripts/fix_market_quotes_null_code.py

# 方法 2：使用虚拟环境
.\.venv\Scripts\python scripts/fix_market_quotes_null_code.py
```

#### 预期输出

```
🔧 开始修复 market_quotes 集合中的 code=null 记录...
📊 market_quotes 集合的索引:
  - _id_: {'v': 2, 'key': [('_id', 1)]}
  - code_1: {'v': 2, 'key': [('code', 1)], 'unique': True}
  - symbol_1: {'v': 2, 'key': [('symbol', 1)]}
✅ 发现 code_1 唯一索引
📊 发现 2 条 code=null 的记录
📋 准备修复 2 条记录...
✅ 修复记录: _id=..., symbol=603175, code=603175
✅ 修复记录: _id=..., symbol=600000, code=600000
✅ 修复完成: 修复 2 条, 删除 0 条
✅ 所有 code=null 的记录已修复
✅ 修复完成
```

---

## 验证修复

### 1. 检查数据库

```javascript
// 连接 MongoDB
use lahm

// 检查 code=null 的记录数
db.market_quotes.countDocuments({ code: null })
// 应该返回 0

// 查看索引
db.market_quotes.getIndexes()
// 应该看到 code_1 唯一索引

// 查看示例记录
db.market_quotes.findOne()
// 应该同时有 code 和 symbol 字段
```

### 2. 测试更新行情

```python
# 在 Python 中测试
from app.services.stock_data_service import get_stock_data_service

service = await get_stock_data_service()

# 测试更新行情
quote_data = {
    "price": 10.5,
    "volume": 1000000,
    # 注意：不包含 code 字段
}

# 应该成功，不会报错
success = await service.update_market_quotes("603175", quote_data)
print(f"更新结果: {success}")

# 验证数据
db = get_mongo_db()
record = await db.market_quotes.find_one({"symbol": "603175"})
print(f"code: {record.get('code')}")  # 应该是 "603175"
print(f"symbol: {record.get('symbol')}")  # 应该是 "603175"
```

---

## 后续建议

### 选项 1：保持双字段（推荐）

**优点**：
- ✅ 向后兼容
- ✅ 支持旧代码
- ✅ 不需要迁移数据

**缺点**：
- ❌ 数据冗余
- ❌ 需要同步维护两个字段

**实现**：
- 已完成，无需额外操作

---

### 选项 2：迁移到 `symbol` 字段

**优点**：
- ✅ 数据结构更清晰
- ✅ 减少冗余

**缺点**：
- ❌ 需要迁移数据
- ❌ 需要更新所有相关代码
- ❌ 可能影响旧代码

**实现步骤**：

1. **删除 `code_1` 唯一索引**
   ```javascript
   db.market_quotes.dropIndex("code_1")
   ```

2. **创建 `symbol_1` 唯一索引**
   ```javascript
   db.market_quotes.createIndex({ symbol: 1 }, { unique: true })
   ```

3. **删除所有记录的 `code` 字段**
   ```javascript
   db.market_quotes.updateMany({}, { $unset: { code: "" } })
   ```

4. **更新代码**
   - 移除所有对 `code` 字段的引用
   - 统一使用 `symbol` 字段

---

## 常见问题

### Q1: 为什么会有 `code=null` 的记录？

**A**: 因为旧代码在更新行情时只设置了 `symbol` 字段，没有设置 `code` 字段。

---

### Q2: 修复脚本会删除数据吗？

**A**: 只会删除**既没有 `symbol` 也没有 `code` 的无效记录**。正常记录只会更新 `code` 字段。

---

### Q3: 修复后还会出现这个错误吗？

**A**: 不会。代码已修复，每次更新时都会确保 `code` 和 `symbol` 字段存在。

---

### Q4: 我应该选择哪个后续方案？

**A**: 
- **如果系统稳定运行**：选择**选项 1**（保持双字段），风险最小
- **如果准备重构**：选择**选项 2**（迁移到 symbol），数据结构更清晰

---

## 相关文件

- **代码修复**：`app/services/stock_data_service.py`
- **修复脚本**：`scripts/fix_market_quotes_null_code.py`
- **本文档**：`docs/fixes/MARKET_QUOTES_NULL_CODE_FIX.md`

---

## 提交记录

- **6bab35b**: fix: 修复 market_quotes 集合 code 字段为 null 导致的唯一索引冲突

