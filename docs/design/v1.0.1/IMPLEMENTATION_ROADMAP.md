# 提示词模版系统 - 实现路线图

## 🎯 总体目标

为Lahm项目的所有13个Agent提供可配置的提示词模板系统，支持用户选择、编辑和自定义。

---

## 📊 实现阶段

### Phase 1: 基础设施 (Week 1-2)

#### 1.1 创建目录结构
- [ ] 创建 `prompts/templates/` 主目录
- [ ] 创建 `prompts/templates/analysts/` 子目录
- [ ] 创建 `prompts/templates/researchers/` 子目录
- [ ] 创建 `prompts/templates/debators/` 子目录
- [ ] 创建 `prompts/templates/managers/` 子目录
- [ ] 创建 `prompts/templates/trader/` 子目录
- [ ] 创建 `prompts/schema/` 目录

#### 1.2 实现PromptTemplateManager
- [ ] 创建 `lahm/config/prompt_manager.py`
- [ ] 实现 `__init__()` 方法
- [ ] 实现 `load_template()` 方法
- [ ] 实现 `list_templates()` 方法
- [ ] 实现 `validate_template()` 方法
- [ ] 实现 `render_template()` 方法
- [ ] 实现 `save_custom_template()` 方法
- [ ] 实现缓存机制
- [ ] 添加错误处理

#### 1.3 创建Schema和验证
- [ ] 创建 `prompts/schema/prompt_template_schema.json`
- [ ] 实现JSON Schema验证
- [ ] 实现YAML验证函数
- [ ] 添加必填字段检查

#### 1.4 单元测试
- [ ] 测试PromptTemplateManager所有方法
- [ ] 测试缓存机制
- [ ] 测试错误处理
- [ ] 测试模版验证

---

### Phase 2: 分析师模版 (Week 2-3)

#### 2.1 基本面分析师模版
- [ ] 创建 `prompts/templates/analysts/fundamentals/default.yaml`
- [ ] 创建 `prompts/templates/analysts/fundamentals/conservative.yaml`
- [ ] 创建 `prompts/templates/analysts/fundamentals/aggressive.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 2.2 市场分析师模版
- [ ] 创建 `prompts/templates/analysts/market/default.yaml`
- [ ] 创建 `prompts/templates/analysts/market/short_term.yaml`
- [ ] 创建 `prompts/templates/analysts/market/long_term.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 2.3 新闻分析师模版
- [ ] 创建 `prompts/templates/analysts/news/default.yaml`
- [ ] 创建 `prompts/templates/analysts/news/real_time.yaml`
- [ ] 创建 `prompts/templates/analysts/news/deep.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 2.4 社媒分析师模版
- [ ] 创建 `prompts/templates/analysts/social/default.yaml`
- [ ] 创建 `prompts/templates/analysts/social/sentiment_focus.yaml`
- [ ] 创建 `prompts/templates/analysts/social/trend_focus.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 2.5 分析师集成
- [ ] 修改 `create_fundamentals_analyst()` 函数
- [ ] 修改 `create_market_analyst()` 函数
- [ ] 修改 `create_news_analyst()` 函数
- [ ] 修改 `create_social_media_analyst()` 函数
- [ ] 集成测试

---

### Phase 3: 研究员模版 (Week 3-4)

#### 3.1 看涨研究员模版
- [ ] 创建 `prompts/templates/researchers/bull/default.yaml`
- [ ] 创建 `prompts/templates/researchers/bull/optimistic.yaml`
- [ ] 创建 `prompts/templates/researchers/bull/moderate.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 3.2 看跌研究员模版
- [ ] 创建 `prompts/templates/researchers/bear/default.yaml`
- [ ] 创建 `prompts/templates/researchers/bear/pessimistic.yaml`
- [ ] 创建 `prompts/templates/researchers/bear/moderate.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 3.3 研究员集成
- [ ] 修改 `create_bull_researcher()` 函数
- [ ] 修改 `create_bear_researcher()` 函数
- [ ] 集成测试

---

### Phase 4: 辩手模版 (Week 4-5)

#### 4.1 激进辩手模版
- [ ] 创建 `prompts/templates/debators/aggressive/default.yaml`
- [ ] 创建 `prompts/templates/debators/aggressive/extreme.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 4.2 保守辩手模版
- [ ] 创建 `prompts/templates/debators/conservative/default.yaml`
- [ ] 创建 `prompts/templates/debators/conservative/cautious.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 4.3 中立辩手模版
- [ ] 创建 `prompts/templates/debators/neutral/default.yaml`
- [ ] 创建 `prompts/templates/debators/neutral/balanced.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 4.4 辩手集成
- [ ] 修改 `create_risky_debator()` 函数
- [ ] 修改 `create_safe_debator()` 函数
- [ ] 修改 `create_neutral_debator()` 函数
- [ ] 集成测试

---

### Phase 5: 管理者和交易员模版 (Week 5-6)

#### 5.1 研究经理模版
- [ ] 创建 `prompts/templates/managers/research/default.yaml`
- [ ] 创建 `prompts/templates/managers/research/strict.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 5.2 风险经理模版
- [ ] 创建 `prompts/templates/managers/risk/default.yaml`
- [ ] 创建 `prompts/templates/managers/risk/strict.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 5.3 交易员模版
- [ ] 创建 `prompts/templates/trader/default.yaml`
- [ ] 创建 `prompts/templates/trader/conservative.yaml`
- [ ] 创建 `prompts/templates/trader/aggressive.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

#### 5.4 管理者和交易员集成
- [ ] 修改 `create_research_manager()` 函数
- [ ] 修改 `create_risk_manager()` 函数
- [ ] 修改 `create_trader()` 函数
- [ ] 集成测试

---

### Phase 6: Web API实现 (Week 6-7)

#### 6.1 API路由创建
- [ ] 创建 `app/routers/prompts.py`
- [ ] 创建数据模型
- [ ] 实现所有API端点

#### 6.2 API端点
- [ ] `GET /api/prompts/templates/{agent_type}`
- [ ] `GET /api/prompts/templates/{agent_type}/{name}`
- [ ] `POST /api/prompts/templates/{agent_type}`
- [ ] `PUT /api/prompts/templates/{agent_type}/{name}`
- [ ] `DELETE /api/prompts/templates/{agent_type}/{name}`
- [ ] `POST /api/prompts/templates/{agent_type}/{name}/preview`
- [ ] `GET /api/prompts/templates/{agent_type}/{name}/versions`

#### 6.3 API测试
- [ ] 测试所有端点
- [ ] 测试错误处理
- [ ] 性能测试

---

### Phase 7: 前端集成 (Week 7-8)

#### 7.1 UI组件开发
- [ ] 创建模版选择组件
- [ ] 创建模版编辑器组件
- [ ] 创建模版预览组件
- [ ] 创建模版列表组件

#### 7.2 分析流程集成
- [ ] 在分析参数中添加模版选择
- [ ] 集成模版选择到分析流程
- [ ] 显示选定的模版
- [ ] 支持模版预览

#### 7.3 前端测试
- [ ] 测试模版选择
- [ ] 测试模版编辑
- [ ] 测试模版预览

---

### Phase 8: 文档和优化 (Week 8-9)

#### 8.1 文档完善
- [ ] 编写用户指南
- [ ] 编写开发者指南
- [ ] 编写API文档
- [ ] 编写模版编写指南

#### 8.2 性能优化
- [ ] 优化缓存策略
- [ ] 优化文件读取
- [ ] 性能测试

#### 8.3 代码质量
- [ ] 代码审查
- [ ] 添加类型注解
- [ ] 代码格式化

#### 8.4 发布准备
- [ ] 更新版本号
- [ ] 更新CHANGELOG
- [ ] 创建发布说明

---

## 📈 进度跟踪

| Phase | 任务数 | 完成 | 进度 |
|-------|--------|------|------|
| Phase 1 | 20 | 0 | 0% |
| Phase 2 | 25 | 0 | 0% |
| Phase 3 | 15 | 0 | 0% |
| Phase 4 | 20 | 0 | 0% |
| Phase 5 | 25 | 0 | 0% |
| Phase 6 | 20 | 0 | 0% |
| Phase 7 | 15 | 0 | 0% |
| Phase 8 | 15 | 0 | 0% |
| **总计** | **155** | **0** | **0%** |

---

## 🎯 关键里程碑

- [ ] **Week 2**: Phase 1 完成 - 基础设施就绪
- [ ] **Week 3**: Phase 2 完成 - 分析师模版完成
- [ ] **Week 4**: Phase 3 完成 - 研究员模版完成
- [ ] **Week 5**: Phase 4 完成 - 辩手模版完成
- [ ] **Week 6**: Phase 5 完成 - 管理者和交易员模版完成
- [ ] **Week 7**: Phase 6 完成 - Web API实现
- [ ] **Week 8**: Phase 7 完成 - 前端集成
- [ ] **Week 9**: Phase 8 完成 - 文档和优化

---

## 📝 注意事项

1. **向后兼容**: 确保现有代码继续工作
2. **默认行为**: 默认模版应保持现有行为
3. **错误处理**: 完善的错误处理和日志
4. **性能**: 缓存机制确保性能
5. **安全**: 验证用户输入
6. **测试**: 充分的单元测试和集成测试
7. **文档**: 清晰的文档和示例

---

## 🚀 启动建议

1. 从Phase 1开始，建立基础设施
2. Phase 2-5可以并行进行
3. Phase 6和7可以并行进行
4. Phase 8贯穿整个开发过程
5. 每个Phase完成后进行充分的集成测试

