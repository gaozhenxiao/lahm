# 与现有系统集成设计

## 📋 概述

本文档说明如何将提示词模板系统与现有的用户系统集成。

---

## ✅ 现有系统分析

### 现有用户系统
- **位置**: `app/models/user.py`, `app/services/user_service.py`
- **数据库**: MongoDB (lahm)
- **集合**: users
- **认证**: 密码哈希 (SHA-256/bcrypt)
- **功能**: 用户创建、认证、信息管理

### 现有用户模型字段
```python
- _id: ObjectId (主键)
- username: str (唯一)
- email: str (唯一)
- hashed_password: str
- is_active: bool
- is_verified: bool
- is_admin: bool
- created_at: datetime
- updated_at: datetime
- last_login: datetime
- preferences: UserPreferences (嵌入式文档)
- daily_quota: int
- concurrent_limit: int
- total_analyses: int
- successful_analyses: int
- failed_analyses: int
- favorite_stocks: List[FavoriteStock]
```

### 现有偏好设置
```python
class UserPreferences:
    - default_market: str
    - default_depth: str
    - default_analysts: List[str]
    - auto_refresh: bool
    - refresh_interval: int
    - ui_theme: str
    - sidebar_width: int
    - language: str
    - notifications_enabled: bool
    - email_notifications: bool
    - desktop_notifications: bool
```

---

## 🔄 集成策略

### 方案1: 扩展现有preferences字段 (推荐)
**优点**: 无需修改现有表结构，最小化改动
**缺点**: preferences字段会变大

```python
# 在UserPreferences中添加
class UserPreferences(BaseModel):
    # 现有字段...
    
    # 新增字段 - 分析偏好
    analysis_preference_type: str = "neutral"  # 默认中性
    analysis_preference_id: Optional[str] = None  # 关联到analysis_preferences._id
```

### 方案2: 创建独立集合 (灵活性更高)
**优点**: 完全独立，易于扩展
**缺点**: 需要维护关联关系

```javascript
// 新增集合
db.createCollection('user_analysis_preferences');
db.createCollection('prompt_templates');
db.createCollection('user_template_configs');
db.createCollection('template_history');
db.createCollection('template_comparison');
```

---

## 📊 新增集合设计

### 1. analysis_preferences 集合
```javascript
{
    _id: ObjectId,
    user_id: ObjectId,  // 关联到users._id
    preference_type: String,  // 'aggressive', 'neutral', 'conservative'
    description: String,
    risk_level: Number,  // 0.0-1.0
    confidence_threshold: Number,  // 0.0-1.0
    position_size_multiplier: Number,  // 0.5-2.0
    decision_speed: String,  // 'fast', 'normal', 'slow'
    is_default: Boolean,
    created_at: DateTime,
    updated_at: DateTime
}
```

**索引**:
```javascript
db.analysis_preferences.createIndex({ user_id: 1 });
db.analysis_preferences.createIndex({ user_id: 1, preference_type: 1 }, { unique: true });
db.analysis_preferences.createIndex({ user_id: 1, is_default: 1 });
```

### 2. prompt_templates 集合
```javascript
{
    _id: ObjectId,
    agent_type: String,  // 'analysts', 'researchers', 'debators', 'managers', 'trader'
    agent_name: String,
    template_name: String,
    preference_type: String,  // null表示通用
    content: {
        system_prompt: String,
        tool_guidance: String,
        analysis_requirements: String,
        output_format: String,
        constraints: String
    },
    is_system: Boolean,
    created_by: ObjectId,  // null表示系统模板
    created_at: DateTime,
    updated_at: DateTime,
    version: Number
}
```

**索引**:
```javascript
db.prompt_templates.createIndex({ agent_type: 1, agent_name: 1 });
db.prompt_templates.createIndex({ is_system: 1 });
db.prompt_templates.createIndex({ created_by: 1 });
db.prompt_templates.createIndex({ preference_type: 1 });
```

### 3. user_template_configs 集合
```javascript
{
    _id: ObjectId,
    user_id: ObjectId,
    agent_type: String,
    agent_name: String,
    template_id: ObjectId,
    preference_id: ObjectId,
    is_active: Boolean,
    created_at: DateTime,
    updated_at: DateTime
}
```

**索引**:
```javascript
db.user_template_configs.createIndex({ user_id: 1 });
db.user_template_configs.createIndex({ user_id: 1, agent_type: 1, agent_name: 1 }, { unique: true });
db.user_template_configs.createIndex({ template_id: 1 });
```

### 4. template_history 集合
```javascript
{
    _id: ObjectId,
    template_id: ObjectId,
    user_id: ObjectId,  // null表示系统模板
    version: Number,
    content: { /* 完整内容 */ },
    change_description: String,
    change_type: String,  // 'create', 'update', 'delete', 'restore'
    created_at: DateTime
}
```

**索引**:
```javascript
db.template_history.createIndex({ template_id: 1, version: 1 });
db.template_history.createIndex({ template_id: 1, created_at: -1 });
```

### 5. template_comparison 集合
```javascript
{
    _id: ObjectId,
    user_id: ObjectId,
    template_id_1: ObjectId,
    template_id_2: ObjectId,
    version_1: Number,
    version_2: Number,
    differences: [
        {
            field: String,
            old_value: String,
            new_value: String,
            change_type: String
        }
    ],
    created_at: DateTime
}
```

---

## 🔗 集成点

### 1. 用户认证
- 使用现有的 `UserService.authenticate_user()`
- 无需修改

### 2. 用户信息
- 使用现有的 `User` 模型
- 扩展 `UserPreferences` 添加分析偏好字段

### 3. 用户偏好
- 新增 `AnalysisPreferenceService`
- 管理用户的分析偏好

### 4. 模板管理
- 新增 `PromptTemplateService`
- 管理系统和用户自定义模板

### 5. 用户配置
- 新增 `UserTemplateConfigService`
- 管理用户的模板配置

### 6. 历史记录
- 新增 `TemplateHistoryService`
- 记录模板修改历史

---

## 📝 迁移步骤

### Step 1: 创建新集合
```bash
# 在MongoDB中执行
db.createCollection('analysis_preferences');
db.createCollection('prompt_templates');
db.createCollection('user_template_configs');
db.createCollection('template_history');
db.createCollection('template_comparison');
```

### Step 2: 创建索引
```bash
# 执行索引创建脚本
python scripts/create_template_indexes.py
```

### Step 3: 创建系统模板
```bash
# 导入预设模板
python scripts/import_system_templates.py
```

### Step 4: 创建默认偏好
```bash
# 为现有用户创建默认偏好
python scripts/create_default_preferences.py
```

### Step 5: 创建默认配置
```bash
# 为现有用户创建默认模板配置
python scripts/create_default_configs.py
```

---

## 🚀 实现优先级

### Phase 1: 基础设施 (Week 1-2)
- [ ] 创建新集合
- [ ] 创建索引
- [ ] 实现DAO层

### Phase 2: 服务层 (Week 2-3)
- [ ] 实现AnalysisPreferenceService
- [ ] 实现PromptTemplateService
- [ ] 实现UserTemplateConfigService

### Phase 3: API层 (Week 3-4)
- [ ] 实现偏好API
- [ ] 实现模板API
- [ ] 实现配置API

### Phase 4: 前端集成 (Week 4-5)
- [ ] 前端UI开发
- [ ] 前端集成
- [ ] 测试

---

## 💡 关键考虑

### 1. 数据一致性
- 使用事务确保数据一致性
- 实现乐观锁防止并发冲突

### 2. 性能优化
- 使用缓存减少数据库访问
- 使用索引加快查询

### 3. 向后兼容
- 现有用户无需修改
- 新功能可选

### 4. 权限管理
- 用户只能访问自己的数据
- 管理员可以管理所有数据

---

**版本**: v1.0.1  
**状态**: 设计完成  
**下一步**: 实现集成

