# LLM 超时监控和优化

## 问题描述

在4级深度分析中，Risk Manager 调用 LLM 时出现超时（Request timed out），从日志看耗时超过6分钟。

## 原因分析

### 1. Prompt 过大

Risk Manager 的 prompt 包含：
- 完整的风险辩论历史（3个分析师 × 2轮 = 6次发言）
- 市场研究报告
- 情绪分析报告
- 新闻报告
- 基本面报告
- 交易员计划
- 历史记忆

**估算**：
- 2轮风险讨论：每个分析师每次发言 500-1000 字符，6次发言 = 3000-6000 字符
- 各种报告：2000-4000 字符
- **总计：5000-10000 字符 ≈ 3000-6000 tokens**

### 2. 超时配置不足

原始配置：
- 固定超时：120秒
- 实际需要：300秒以上（根据日志）

## 解决方案

### 1. 动态超时配置

**文件**: `lahm/graph/trading_graph.py`

根据研究深度动态调整超时时间：

```python
# 计算合理的超时时间：基础300秒 + 每轮辩论额外60秒
base_timeout = 300
debate_timeout = max_debate_rounds * 30  # 投资辩论每轮30秒
risk_timeout = max_risk_discuss_rounds * 60  # 风险讨论每轮60秒
total_timeout = base_timeout + debate_timeout + risk_timeout
```

**超时时间对照表**：

| 研究深度 | 辩论轮次 | 风险轮次 | 计算公式 | 总超时 |
|---------|---------|---------|---------|--------|
| 1级-快速 | 1 | 1 | 300 + 1×30 + 1×60 | 390秒 |
| 2级-基础 | 1 | 1 | 300 + 1×30 + 1×60 | 390秒 |
| 3级-标准 | 1 | 2 | 300 + 1×30 + 2×60 | 450秒 |
| **4级-深度** | **2** | **2** | **300 + 2×30 + 2×60** | **480秒** |
| **5级-全面** | **3** | **3** | **300 + 3×30 + 3×60** | **570秒** |

### 2. 添加详细监控

#### 2.1 Risk Manager 监控

**文件**: `lahm/agents/managers/risk_manager.py`

**输入统计**：
```python
logger.info(f"📊 [Risk Manager] Prompt 统计:")
logger.info(f"   - 辩论历史长度: {len(history)} 字符")
logger.info(f"   - 交易员计划长度: {len(trader_plan)} 字符")
logger.info(f"   - 历史记忆长度: {len(past_memory_str)} 字符")
logger.info(f"   - 总 Prompt 长度: {prompt_length} 字符")
logger.info(f"   - 估算输入 Token: ~{estimated_tokens} tokens")
```

**输出统计**：
```python
logger.info(f"⏱️ [Risk Manager] LLM调用耗时: {elapsed_time:.2f}秒")
logger.info(f"📊 [Risk Manager] 响应统计: {response_length} 字符, 估算~{estimated_output_tokens} tokens")
```

**Token 使用情况**（如果 LLM 返回）：
```python
if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
    token_usage = response.response_metadata['token_usage']
    logger.info(f"实际Token: 输入={token_usage['prompt_tokens']} 输出={token_usage['completion_tokens']} 总计={token_usage['total_tokens']}")
```

#### 2.2 Research Manager 监控

**文件**: `lahm/agents/managers/research_manager.py`

类似的统计信息：
- Prompt 长度统计
- 估算 Token 数量
- LLM 调用耗时
- 响应长度统计

## 如何使用监控日志

### 1. 查看超时配置

```powershell
Get-Content logs/lahm.log | Select-String "阿里百炼.*超时|研究深度.*辩论轮次"
```

期望看到：
```
⏱️ [阿里百炼] 研究深度: 深度, 辩论轮次: 2, 风险讨论轮次: 2
⏱️ [阿里百炼] 计算超时时间: 300s (基础) + 60s (辩论) + 120s (风险) = 480s
✅ [阿里百炼] 已设置动态请求超时: 480秒
```

### 2. 查看 Risk Manager 性能

```powershell
Get-Content logs/lahm.log | Select-String "Risk Manager.*Prompt 统计|Risk Manager.*调用耗时|Risk Manager.*响应统计"
```

期望看到：
```
📊 [Risk Manager] Prompt 统计:
   - 辩论历史长度: 8523 字符
   - 交易员计划长度: 1245 字符
   - 历史记忆长度: 234 字符
   - 总 Prompt 长度: 12456 字符
   - 估算输入 Token: ~6920 tokens

⏱️ [Risk Manager] LLM调用耗时: 245.32秒
📊 [Risk Manager] 响应统计: 1523 字符, 估算~846 tokens
```

### 3. 查看 Research Manager 性能

```powershell
Get-Content logs/lahm.log | Select-String "Research Manager.*Prompt 统计|Research Manager.*调用耗时"
```

## 性能分析

### 正常情况

**4级深度分析**：
- Research Manager: 60-120秒
- Risk Manager: 120-300秒
- 总耗时: 180-420秒（3-7分钟）

**5级全面分析**：
- Research Manager: 90-180秒
- Risk Manager: 180-450秒
- 总耗时: 270-630秒（4.5-10.5分钟）

### 异常情况

如果看到以下情况，说明有问题：

1. **超时错误**：
   ```
   ❌ [Risk Manager] LLM调用失败: Request timed out.
   ```
   - **原因**: 超时时间不足或 LLM 服务响应慢
   - **解决**: 增加 `base_timeout` 或检查网络

2. **Prompt 过大**：
   ```
   📊 [Risk Manager] 总 Prompt 长度: 25000 字符
   📊 [Risk Manager] 估算输入 Token: ~13889 tokens
   ```
   - **原因**: 辩论轮次过多或报告过长
   - **解决**: 考虑截断历史或摘要报告

3. **响应时间过长**：
   ```
   ⏱️ [Risk Manager] LLM调用耗时: 450.00秒
   ```
   - **原因**: Token 数量大或 LLM 服务负载高
   - **解决**: 优化 prompt 或升级 LLM 服务

## 优化建议

### 短期优化（已实施）

1. ✅ **动态超时配置**: 根据研究深度自动调整
2. ✅ **详细监控日志**: 追踪 Token 使用和耗时

### 中期优化（待实施）

1. **Prompt 优化**:
   - 截断过长的辩论历史（保留最近3000字符）
   - 使用摘要而非完整报告
   - 减少历史记忆数量（从2条减到1条）

2. **并行处理**:
   - 某些独立的分析可以并行执行
   - 减少总体等待时间

### 长期优化（待评估）

1. **流式输出**:
   - 使用 LLM 的流式 API
   - 边生成边处理，减少等待时间

2. **缓存机制**:
   - 缓存相似的分析结果
   - 避免重复计算

3. **模型选择**:
   - 对于简单任务使用更快的模型
   - 只在关键决策时使用深度模型

## 测试验证

### 1. 运行4级深度分析

观察日志中的：
- ✅ 超时配置是否正确（应该是480秒）
- ✅ Prompt 大小是否合理（<15000字符）
- ✅ 实际耗时是否在预期范围内（<480秒）

### 2. 运行5级全面分析

观察日志中的：
- ✅ 超时配置是否正确（应该是570秒）
- ✅ Prompt 大小（可能更大）
- ✅ 实际耗时是否在预期范围内（<570秒）

## 总结

通过动态超时配置和详细监控，我们可以：
1. ✅ 避免不必要的超时错误
2. ✅ 准确追踪 LLM 性能
3. ✅ 识别性能瓶颈
4. ✅ 为进一步优化提供数据支持

现在重新运行4级深度分析，观察新的监控日志！

