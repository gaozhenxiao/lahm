# 增强版实现路线图 - 包含数据库、用户、偏好、历史记录

## 🎯 总体目标

为Lahm项目的所有13个Agent提供完整的提示词模板系统，包括：
- ✅ 数据库存储
- ✅ 用户管理
- ✅ 分析偏好
- ✅ 历史记录和版本管理
- ✅ Web API
- ✅ 前端UI

---

## 📊 实现阶段概览

| 阶段 | 名称 | 周数 | 任务数 | 优先级 |
|------|------|------|--------|--------|
| Phase 1 | 基础设施 + 数据库 | 2 | 25 | 🔴 高 |
| Phase 2 | 用户和偏好管理 | 1 | 20 | 🔴 高 |
| Phase 3 | 分析师模版 | 1 | 25 | 🔴 高 |
| Phase 4 | 研究员和辩手模版 | 1 | 20 | 🟡 中 |
| Phase 5 | 管理者和交易员模版 | 1 | 15 | 🟡 中 |
| Phase 6 | 历史记录和版本管理 | 1 | 20 | 🟡 中 |
| Phase 7 | Web API (完整) | 1 | 35 | 🔴 高 |
| Phase 8 | 前端UI和集成 | 2 | 40 | 🟡 中 |
| Phase 9 | 文档和优化 | 1 | 15 | 🟢 低 |
| **总计** | **9个阶段** | **11周** | **215** | - |

---

## 🔄 详细实现计划

### Phase 1: 基础设施 + 数据库 (Week 1-2)

#### 1.1 数据库设计和创建
- [ ] 设计数据库架构
- [ ] 创建users表
- [ ] 创建analysis_preferences表
- [ ] 创建prompt_templates表
- [ ] 创建user_template_configs表
- [ ] 创建template_history表
- [ ] 创建template_comparison表
- [ ] 创建索引和约束
- [ ] 创建初始数据

#### 1.2 目录结构
- [ ] 创建prompts/templates/目录
- [ ] 创建prompts/schema/目录
- [ ] 创建lahm/database/目录
- [ ] 创建lahm/models/目录

#### 1.3 核心类实现
- [ ] 实现User模型
- [ ] 实现AnalysisPreference模型
- [ ] 实现PromptTemplate模型
- [ ] 实现UserTemplateConfig模型
- [ ] 实现TemplateHistory模型

#### 1.4 数据库访问层
- [ ] 实现UserDAO
- [ ] 实现PreferenceDAO
- [ ] 实现TemplateDAO
- [ ] 实现HistoryDAO

---

### Phase 2: 用户和偏好管理 (Week 3)

#### 2.1 用户管理
- [ ] 实现用户创建
- [ ] 实现用户查询
- [ ] 实现用户更新
- [ ] 实现用户删除
- [ ] 实现用户认证

#### 2.2 偏好管理
- [ ] 实现偏好创建
- [ ] 实现偏好查询
- [ ] 实现偏好更新
- [ ] 实现偏好删除
- [ ] 实现默认偏好设置

#### 2.3 用户配置管理
- [ ] 实现配置创建
- [ ] 实现配置查询
- [ ] 实现配置更新
- [ ] 实现配置删除

#### 2.4 单元测试
- [ ] 测试用户管理
- [ ] 测试偏好管理
- [ ] 测试配置管理

---

### Phase 3: 分析师模版 (Week 4)

#### 3.1 基本面分析师
- [ ] 创建default.yaml
- [ ] 创建conservative.yaml
- [ ] 创建aggressive.yaml
- [ ] 集成到Agent

#### 3.2 市场分析师
- [ ] 创建default.yaml
- [ ] 创建conservative.yaml
- [ ] 创建aggressive.yaml
- [ ] 集成到Agent

#### 3.3 新闻分析师
- [ ] 创建default.yaml
- [ ] 创建conservative.yaml
- [ ] 创建aggressive.yaml
- [ ] 集成到Agent

#### 3.4 社媒分析师
- [ ] 创建default.yaml
- [ ] 创建conservative.yaml
- [ ] 创建aggressive.yaml
- [ ] 集成到Agent

---

### Phase 4: 研究员和辩手模版 (Week 5)

#### 4.1 研究员模版
- [ ] 看涨研究员 (3个模版)
- [ ] 看跌研究员 (3个模版)

#### 4.2 辩手模版
- [ ] 激进辩手 (2个模版)
- [ ] 保守辩手 (2个模版)
- [ ] 中立辩手 (2个模版)

---

### Phase 5: 管理者和交易员模版 (Week 6)

#### 5.1 管理者模版
- [ ] 研究经理 (2个模版)
- [ ] 风险经理 (2个模版)

#### 5.2 交易员模版
- [ ] 交易员 (3个模版)

---

### Phase 6: 历史记录和版本管理 (Week 7)

#### 6.1 历史记录功能
- [ ] 实现历史记录创建
- [ ] 实现历史记录查询
- [ ] 实现版本列表
- [ ] 实现版本详情

#### 6.2 版本管理
- [ ] 实现版本回滚
- [ ] 实现版本对比
- [ ] 实现差异计算
- [ ] 实现对比记录

#### 6.3 单元测试
- [ ] 测试历史记录
- [ ] 测试版本管理
- [ ] 测试版本对比

---

### Phase 7: Web API (Week 8)

#### 7.1 用户API
- [ ] POST /api/v1/users
- [ ] GET /api/v1/users/{user_id}
- [ ] PUT /api/v1/users/{user_id}
- [ ] DELETE /api/v1/users/{user_id}

#### 7.2 偏好API
- [ ] POST /api/v1/users/{user_id}/preferences
- [ ] GET /api/v1/users/{user_id}/preferences
- [ ] PUT /api/v1/users/{user_id}/preferences/{preference_id}
- [ ] DELETE /api/v1/users/{user_id}/preferences/{preference_id}
- [ ] POST /api/v1/users/{user_id}/preferences/{preference_id}/set-default

#### 7.3 模板API
- [ ] POST /api/v1/templates
- [ ] GET /api/v1/templates/{template_id}
- [ ] PUT /api/v1/templates/{template_id}
- [ ] DELETE /api/v1/templates/{template_id}
- [ ] GET /api/v1/users/{user_id}/custom-templates
- [ ] POST /api/v1/templates/{template_id}/clone

#### 7.4 历史API
- [ ] GET /api/v1/templates/{template_id}/history
- [ ] GET /api/v1/templates/{template_id}/history/{version}
- [ ] POST /api/v1/templates/{template_id}/restore/{version}
- [ ] POST /api/v1/templates/{template_id}/compare

#### 7.5 配置API
- [ ] GET /api/v1/users/{user_id}/template-configs
- [ ] POST /api/v1/users/{user_id}/template-configs
- [ ] PUT /api/v1/users/{user_id}/template-configs/{config_id}
- [ ] DELETE /api/v1/users/{user_id}/template-configs/{config_id}

#### 7.6 统计API
- [ ] GET /api/v1/users/{user_id}/statistics
- [ ] GET /api/v1/templates/{template_id}/statistics
- [ ] GET /api/v1/users/{user_id}/preferences/{preference_id}/statistics

---

### Phase 8: 前端UI和集成 (Week 9-10)

#### 8.1 用户管理UI
- [ ] 用户信息面板
- [ ] 用户编辑表单
- [ ] 用户删除确认

#### 8.2 偏好管理UI
- [ ] 偏好列表面板
- [ ] 偏好编辑表单
- [ ] 偏好选择器
- [ ] 偏好预览

#### 8.3 模板管理UI
- [ ] 模板配置面板
- [ ] 模板编辑器
- [ ] 模板预览
- [ ] 模板选择器

#### 8.4 历史管理UI
- [ ] 历史记录面板
- [ ] 版本对比面板
- [ ] 版本恢复确认
- [ ] 修改统计

#### 8.5 集成测试
- [ ] 测试用户流程
- [ ] 测试偏好流程
- [ ] 测试模板流程
- [ ] 测试历史流程

---

### Phase 9: 文档和优化 (Week 11)

#### 9.1 文档
- [ ] 完善API文档
- [ ] 完善UI文档
- [ ] 完善数据库文档
- [ ] 完善部署文档

#### 9.2 优化
- [ ] 性能优化
- [ ] 缓存优化
- [ ] 查询优化
- [ ] 前端优化

#### 9.3 发布
- [ ] 代码审查
- [ ] 最终测试
- [ ] 发布准备
- [ ] 版本发布

---

## 🎯 关键里程碑

| 时间 | 里程碑 | 状态 |
|------|--------|------|
| Week 2 | 数据库和基础设施完成 | ⏳ |
| Week 3 | 用户和偏好管理完成 | ⏳ |
| Week 6 | 所有模版创建完成 | ⏳ |
| Week 7 | 历史记录功能完成 | ⏳ |
| Week 8 | Web API完成 | ⏳ |
| Week 10 | 前端UI完成 | ⏳ |
| Week 11 | v1.0.1正式发布 | ⏳ |

---

## 📈 风险和缓解

### 风险1: 数据库性能
- **风险**: 大量用户和模版导致查询缓慢
- **缓解**: 使用缓存、索引优化、查询优化

### 风险2: 数据一致性
- **风险**: 并发修改导致数据不一致
- **缓解**: 使用事务、版本控制、乐观锁

### 风险3: 前端复杂性
- **风险**: 前端功能过多导致开发延期
- **缓解**: 分阶段实现、优先级划分、代码复用

---

**版本**: v1.0.1 增强版  
**状态**: 设计完成  
**下一步**: 启动Phase 1实现

