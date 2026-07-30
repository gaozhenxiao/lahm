# 提示词模版系统 - 实现检查清单

## ✅ Phase 1: 基础设施 (1-2周)

### 目录和文件结构
- [ ] 创建 `prompts/` 目录
- [ ] 创建 `prompts/templates/` 子目录
- [ ] 创建 `prompts/templates/fundamentals/` 目录
- [ ] 创建 `prompts/templates/market/` 目录
- [ ] 创建 `prompts/templates/news/` 目录
- [ ] 创建 `prompts/templates/social/` 目录
- [ ] 创建 `prompts/schema/` 目录
- [ ] 创建 `prompts/README.md`

### PromptTemplateManager 实现
- [ ] 创建 `lahm/config/prompt_manager.py`
- [ ] 实现 `__init__()` 方法
- [ ] 实现 `load_template()` 方法
- [ ] 实现 `list_templates()` 方法
- [ ] 实现 `validate_template()` 方法
- [ ] 实现 `render_template()` 方法
- [ ] 实现 `save_custom_template()` 方法
- [ ] 实现 `get_template_versions()` 方法
- [ ] 添加缓存机制
- [ ] 添加错误处理

### Schema 和验证
- [ ] 创建 `prompts/schema/prompt_template_schema.json`
- [ ] 实现 JSON Schema 验证
- [ ] 创建 YAML 验证函数
- [ ] 添加必填字段检查

### 单元测试
- [ ] 测试 `load_template()`
- [ ] 测试 `list_templates()`
- [ ] 测试 `validate_template()`
- [ ] 测试 `render_template()`
- [ ] 测试缓存机制
- [ ] 测试错误处理

## ✅ Phase 2: 模版文件创建 (1周)

### 基本面分析师模版
- [ ] 创建 `prompts/templates/fundamentals/default.yaml`
- [ ] 创建 `prompts/templates/fundamentals/conservative.yaml`
- [ ] 创建 `prompts/templates/fundamentals/aggressive.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

### 市场分析师模版
- [ ] 创建 `prompts/templates/market/default.yaml`
- [ ] 创建 `prompts/templates/market/short_term.yaml`
- [ ] 创建 `prompts/templates/market/long_term.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

### 新闻分析师模版
- [ ] 创建 `prompts/templates/news/default.yaml`
- [ ] 创建 `prompts/templates/news/real_time.yaml`
- [ ] 创建 `prompts/templates/news/deep.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

### 社媒分析师模版
- [ ] 创建 `prompts/templates/social/default.yaml`
- [ ] 创建 `prompts/templates/social/sentiment_focus.yaml`
- [ ] 创建 `prompts/templates/social/trend_focus.yaml`
- [ ] 验证模版格式
- [ ] 测试模版加载

## ✅ Phase 3: 分析师集成 (1-2周)

### 基本面分析师集成
- [ ] 修改 `create_fundamentals_analyst()` 函数签名
- [ ] 添加 `template_name` 参数
- [ ] 集成 PromptTemplateManager
- [ ] 加载模版
- [ ] 渲染模版变量
- [ ] 注入到提示词
- [ ] 测试集成

### 市场分析师集成
- [ ] 修改 `create_market_analyst()` 函数签名
- [ ] 添加 `template_name` 参数
- [ ] 集成 PromptTemplateManager
- [ ] 加载模版
- [ ] 渲染模版变量
- [ ] 注入到提示词
- [ ] 测试集成

### 新闻分析师集成
- [ ] 修改 `create_news_analyst()` 函数签名
- [ ] 添加 `template_name` 参数
- [ ] 集成 PromptTemplateManager
- [ ] 加载模版
- [ ] 渲染模版变量
- [ ] 注入到提示词
- [ ] 测试集成

### 社媒分析师集成
- [ ] 修改 `create_social_media_analyst()` 函数签名
- [ ] 添加 `template_name` 参数
- [ ] 集成 PromptTemplateManager
- [ ] 加载模版
- [ ] 渲染模版变量
- [ ] 注入到提示词
- [ ] 测试集成

### 集成测试
- [ ] 测试所有分析师的模版加载
- [ ] 测试模版变量渲染
- [ ] 测试分析执行
- [ ] 测试不同模版的结果差异

## ✅ Phase 4: Web API 实现 (1周)

### API 路由创建
- [ ] 创建 `app/routers/prompts.py`
- [ ] 创建 PromptTemplateResponse 数据模型
- [ ] 创建 CreatePromptTemplateRequest 数据模型
- [ ] 创建 PromptTemplatePreviewRequest 数据模型

### API 端点实现
- [ ] 实现 `GET /api/prompts/templates/{analyst_type}`
- [ ] 实现 `GET /api/prompts/templates/{analyst_type}/{name}`
- [ ] 实现 `POST /api/prompts/templates/{analyst_type}`
- [ ] 实现 `PUT /api/prompts/templates/{analyst_type}/{name}`
- [ ] 实现 `DELETE /api/prompts/templates/{analyst_type}/{name}`
- [ ] 实现 `POST /api/prompts/templates/{analyst_type}/{name}/preview`
- [ ] 实现 `GET /api/prompts/templates/{analyst_type}/{name}/versions`

### 数据库模型 (可选)
- [ ] 创建 PromptTemplateDB 模型
- [ ] 创建数据库迁移脚本
- [ ] 实现自定义模版保存
- [ ] 实现模版版本管理

### API 测试
- [ ] 测试所有端点
- [ ] 测试错误处理
- [ ] 测试权限控制
- [ ] 测试性能

## ✅ Phase 5: 前端集成 (1-2周)

### 数据模型更新
- [ ] 更新 AnalysisParameters 模型
- [ ] 添加 analyst_templates 字段
- [ ] 更新类型定义

### UI 组件开发
- [ ] 创建模版选择组件
- [ ] 创建模版编辑器组件
- [ ] 创建模版预览组件
- [ ] 创建模版列表组件

### 分析流程集成
- [ ] 在分析参数中添加模版选择
- [ ] 集成模版选择到分析流程
- [ ] 显示选定的模版
- [ ] 支持模版预览

### 前端测试
- [ ] 测试模版选择
- [ ] 测试模版编辑
- [ ] 测试模版预览
- [ ] 测试分析执行

## ✅ Phase 6: 文档和优化 (1周)

### 文档完善
- [ ] 编写用户指南
- [ ] 编写开发者指南
- [ ] 编写 API 文档
- [ ] 编写模版编写指南
- [ ] 创建常见问题解答

### 性能优化
- [ ] 优化缓存策略
- [ ] 优化文件读取
- [ ] 优化模版渲染
- [ ] 性能测试

### 代码质量
- [ ] 代码审查
- [ ] 添加类型注解
- [ ] 添加文档字符串
- [ ] 代码格式化

### 发布准备
- [ ] 更新版本号
- [ ] 更新 CHANGELOG
- [ ] 创建发布说明
- [ ] 准备迁移指南

## 📊 进度跟踪

| Phase | 任务数 | 完成 | 进度 |
|-------|--------|------|------|
| Phase 1 | 20 | 0 | 0% |
| Phase 2 | 20 | 0 | 0% |
| Phase 3 | 28 | 0 | 0% |
| Phase 4 | 20 | 0 | 0% |
| Phase 5 | 16 | 0 | 0% |
| Phase 6 | 16 | 0 | 0% |
| **总计** | **120** | **0** | **0%** |

## 🎯 关键里程碑

- [ ] **Week 1**: Phase 1 完成 - 基础设施就绪
- [ ] **Week 2**: Phase 2 完成 - 模版文件创建
- [ ] **Week 3**: Phase 3 完成 - 分析师集成
- [ ] **Week 4**: Phase 4 完成 - Web API 实现
- [ ] **Week 5**: Phase 5 完成 - 前端集成
- [ ] **Week 6**: Phase 6 完成 - 文档和优化
- [ ] **Week 7**: 测试和修复
- [ ] **Week 8**: 发布准备

## 📝 注意事项

1. **向后兼容**: 确保现有代码继续工作
2. **默认行为**: 默认模版应保持现有行为
3. **错误处理**: 完善的错误处理和日志
4. **性能**: 缓存机制确保性能
5. **安全**: 验证用户输入
6. **测试**: 充分的单元测试和集成测试
7. **文档**: 清晰的文档和示例

## 🚀 启动建议

1. 从 Phase 1 开始，建立基础设施
2. 并行进行 Phase 2 的模版创建
3. 完成 Phase 3 后进行集成测试
4. Phase 4 和 5 可以并行进行
5. Phase 6 贯穿整个开发过程

