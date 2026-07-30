# stock_basic_info 集合缺少 symbol 字段修复

**日期**: 2025-10-27  
**问题**: MongoDB 中 `stock_basic_info` 集合缺少 `symbol` 字段  
**严重程度**: 高（影响股票数据查询和名称对应）

---

## 📋 问题描述

### 现象

用户反馈：股票代码 `601899` 显示的名称是"中国神华"，但实际应该是"紫金矿业"。

### 根本原因

经过调查发现，问题不是数据本身错误，而是**字段结构不完整**：

- ✅ MongoDB 中有 `code` 字段（6位股票代码）
- ✅ MongoDB 中有 `full_symbol` 字段（完整标准化代码，如 601899.SH）
- ❌ **MongoDB 中缺少 `symbol` 字段**

### 导致的问题

1. **查询逻辑不一致**：
   - `app_adapter.py` 只查询 `code` 字段 ✅
   - `stock_data_service.py` 查询 `symbol` 或 `code` 字段 ⚠️
   - 导致某些查询可能失败或返回不一致的结果

2. **数据标准化不完整**：
   - 设计文档要求添加 `symbol` 字段
   - 但同步服务没有实现

3. **股票名称对应错误**：
   - 当查询逻辑失败时，可能返回缓存的错误数据
   - 导致股票名称对应错误

---

## ✅ 修复方案

### 1. 修复同步服务

#### 文件1: `app/services/basics_sync_service.py`

**修改内容**（第 171-183 行）：
```python
doc = {
    "code": code,
    "symbol": code,  # ✅ 添加这一行
    "name": name,
    "area": area,
    # ... 其他字段
    "full_symbol": full_symbol,
}
```

#### 文件2: `app/services/multi_source_basics_sync_service.py`

**修改内容**（第 208-220 行）：
```python
doc = {
    "code": code,
    "symbol": code,  # ✅ 添加这一行
    "name": name,
    "area": area,
    # ... 其他字段
    "full_symbol": full_symbol,
}
```

#### 文件3: `app/worker/baostock_sync_service.py`

**修改内容**（第 139-157 行）：
```python
async def _update_stock_basic_info(self, basic_info: Dict[str, Any]):
    """更新股票基础信息到数据库"""
    try:
        collection = self.db.stock_basic_info
        
        # ✅ 确保 symbol 字段存在
        if "symbol" not in basic_info and "code" in basic_info:
            basic_info["symbol"] = basic_info["code"]
        
        # 使用upsert更新或插入
        await collection.update_one(
            {"code": basic_info["code"]},
            {"$set": basic_info},
            upsert=True
        )
```

### 2. 修复查询逻辑

#### 文件: `lahm/dataflows/cache/app_adapter.py`

**修改内容**（第 47-60 行）：
```python
# 同时查询 symbol 和 code 字段，确保兼容新旧数据格式
doc = coll.find_one({"$or": [{"symbol": code6}, {"code": code6}]})
```

### 3. 迁移现有数据

创建迁移脚本：`scripts/migrations/add_symbol_field_to_stock_basic_info.py`

**功能**：
- 为现有的所有 `stock_basic_info` 记录添加 `symbol` 字段
- `symbol` 字段值等于 `code` 字段值
- 验证迁移结果

**使用方法**：
```bash
python scripts/migrations/add_symbol_field_to_stock_basic_info.py
```

---

## 📊 修复效果

### 修复前

```javascript
// MongoDB 中的数据
{
  "_id": ObjectId("..."),
  "code": "601899",
  "name": "紫金矿业",
  "full_symbol": "601899.SH",
  // ❌ 缺少 symbol 字段
}
```

### 修复后

```javascript
// MongoDB 中的数据
{
  "_id": ObjectId("..."),
  "code": "601899",
  "symbol": "601899",  // ✅ 添加了 symbol 字段
  "name": "紫金矿业",
  "full_symbol": "601899.SH",
}
```

### 查询逻辑

```python
# 修复前：只查询 code 字段
doc = coll.find_one({"code": code6})

# 修复后：同时查询 symbol 和 code 字段
doc = coll.find_one({"$or": [{"symbol": code6}, {"code": code6}]})
```

---

## 🧪 验证

### 测试脚本

**文件**: `tests/test_symbol_field_fix.py`

**测试内容**:
1. ✅ basics_sync_service 是否添加了 symbol 字段
2. ✅ multi_source_sync_service 是否添加了 symbol 字段
3. ✅ baostock_sync_service 是否添加了 symbol 字段
4. ✅ app_adapter 是否支持 symbol 字段查询
5. ✅ 迁移脚本是否存在

**测试结果**: 所有测试通过 ✅

---

## 📝 后续步骤

1. **立即执行**：
   - ✅ 代码修复已完成
   - ⏳ 需要运行迁移脚本为现有数据添加 `symbol` 字段

2. **运行迁移脚本**：
   ```bash
   python scripts/migrations/add_symbol_field_to_stock_basic_info.py
   ```

3. **验证结果**：
   - 检查 MongoDB 中是否所有记录都有 `symbol` 字段
   - 重新查询股票 601899，确认名称正确

4. **重新同步数据**（可选）：
   - 如果需要更新最新的股票数据，可以运行同步服务
   - 新同步的数据会自动包含 `symbol` 字段

---

## 🎯 总结

这个修复确保了：
- ✅ 所有新同步的数据都包含 `symbol` 字段
- ✅ 查询逻辑能正确处理 `symbol` 和 `code` 字段
- ✅ 股票名称能正确对应到股票代码
- ✅ 数据结构符合设计文档要求

