# 数据导出脱敏功能说明

## 📋 概述

从 v1.0.0 版本开始，数据库导出功能支持**自动脱敏**，用于安全地导出配置数据用于演示系统、分享或公开发布。

---

## 🎯 功能特性

### 自动脱敏

当选择"**配置数据（用于演示系统）**"导出时，系统会自动：

1. **清空敏感字段**
   - 递归扫描所有文档，清空包含以下关键词的字段值：
     - `api_key`
     - `api_secret`
     - `secret`
     - `token`
     - `password`
     - `client_secret`
     - `webhook_secret`
     - `private_key`

2. **特殊处理 users 集合**
   - 只导出空数组（保留集合结构）
   - 不导出任何实际用户数据（用户名、密码哈希、邮箱等）

3. **保持数据结构完整**
   - 字段名保持不变
   - 嵌套结构保持不变
   - 只清空敏感字段的值（设为空字符串 `""`）

---

## 🚀 使用方法

### 前端界面导出

1. 登录系统
2. 进入：`系统管理` → `数据库管理`
3. 在"数据导出"区域：
   - **导出格式**：选择 `JSON`
   - **数据集合**：选择 `配置数据（用于演示系统）`
4. 点击"导出数据"按钮
5. 下载文件：`database_export_config_YYYY-MM-DD.json`

> **提示**：导出成功后会显示"配置数据导出成功（已脱敏：API key 等敏感字段已清空，用户数据仅保留结构）"

### API 调用

```bash
# 脱敏导出（用于演示系统）
curl -X POST "http://localhost:8000/api/system/database/export" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["system_configs", "llm_providers", "model_catalog"],
    "format": "json",
    "sanitize": true
  }' \
  --output export_sanitized.json

# 完整导出（不脱敏，用于备份）
curl -X POST "http://localhost:8000/api/system/database/export" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": [],
    "format": "json",
    "sanitize": false
  }' \
  --output export_full.json
```

---

## 📊 导出内容对比

### 脱敏前（原始数据）

```json
{
  "export_info": {
    "created_at": "2025-10-24T10:00:00",
    "collections": ["system_configs", "llm_providers", "users"],
    "format": "json"
  },
  "data": {
    "system_configs": [
      {
        "llm_configs": [
          {
            "provider": "openai",
            "api_key": "sk-proj-abc123xyz...",
            "model": "gpt-4"
          }
        ],
        "system_settings": {
          "finnhub_api_key": "c1234567890",
          "tushare_token": "abc123xyz...",
          "app_name": "柳暗花明"
        }
      }
    ],
    "llm_providers": [
      {
        "name": "OpenAI",
        "api_key": "sk-proj-abc123xyz...",
        "base_url": "https://api.openai.com"
      }
    ],
    "users": [
      {
        "username": "admin",
        "email": "admin@example.com",
        "hashed_password": "$2b$12$abc123..."
      }
    ]
  }
}
```

### 脱敏后（安全导出）

```json
{
  "export_info": {
    "created_at": "2025-10-24T10:00:00",
    "collections": ["system_configs", "llm_providers", "users"],
    "format": "json"
  },
  "data": {
    "system_configs": [
      {
        "llm_configs": [
          {
            "provider": "openai",
            "api_key": "",
            "model": "gpt-4"
          }
        ],
        "system_settings": {
          "finnhub_api_key": "",
          "tushare_token": "",
          "app_name": "柳暗花明"
        }
      }
    ],
    "llm_providers": [
      {
        "name": "OpenAI",
        "api_key": "",
        "base_url": "https://api.openai.com"
      }
    ],
    "users": []
  }
}
```

---

## ⚠️ 注意事项

### 导出后的处理

1. **脱敏导出**（`sanitize: true`）
   - ✅ 可以安全地分享给他人
   - ✅ 可以上传到公开仓库（如 GitHub）
   - ✅ 可以用于演示系统部署
   - ⚠️ 导入后需要重新配置 API 密钥
   - ⚠️ 导入后需要创建管理员用户

2. **完整导出**（`sanitize: false`）
   - ⚠️ 包含敏感信息，仅用于备份
   - ⚠️ 不要分享或上传到公开位置
   - ⚠️ 应加密存储或使用安全传输
   - ✅ 导入后可直接使用（包含所有配置和用户）

### 导入脱敏数据后的配置

使用脱敏导出的数据部署新系统后，需要：

1. **创建管理员用户**
   ```bash
   python scripts/create_default_admin.py
   ```

2. **配置 API 密钥**
   - 登录系统
   - 进入：`系统管理` → `系统配置`
   - 重新填写各个服务的 API 密钥：
     - LLM 提供商 API Key
     - 数据源 API Key（Finnhub、Tushare 等）
     - 其他第三方服务密钥

---

## 🔧 技术实现

### 脱敏算法

```python
def _sanitize_document(doc):
    """递归清空文档中的敏感字段"""
    SENSITIVE_KEYWORDS = [
        "api_key", "api_secret", "secret", "token", "password",
        "client_secret", "webhook_secret", "private_key"
    ]
    
    if isinstance(doc, dict):
        sanitized = {}
        for k, v in doc.items():
            # 检查字段名是否包含敏感关键词（忽略大小写）
            if any(keyword in k.lower() for keyword in SENSITIVE_KEYWORDS):
                sanitized[k] = ""  # 清空敏感字段
            elif isinstance(v, (dict, list)):
                sanitized[k] = _sanitize_document(v)  # 递归处理
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(doc, list):
        return [_sanitize_document(item) for item in doc]
    else:
        return doc
```

### 特殊处理

- **users 集合**：在脱敏模式下，直接返回空数组 `[]`，不读取任何用户数据
- **大小写不敏感**：`API_KEY`、`Api_Key`、`api_key` 都会被识别并清空
- **嵌套结构**：递归处理所有嵌套的字典和列表

---

## 📚 相关文档

- [使用 Python 脚本导入配置数据](../import_config_with_script.md)
- [数据库管理指南](../../guides/config-management-guide.md)
- [Docker 部署指南](../../guides/docker-deployment-guide.md)

---

## 🆘 常见问题

### Q1: 为什么导入脱敏数据后无法登录？

**A**: 脱敏导出不包含用户数据。导入后需要运行 `scripts/create_default_admin.py` 创建管理员用户。

### Q2: 导入后系统提示"API 密钥未配置"？

**A**: 脱敏导出已清空所有 API 密钥。登录后进入"系统配置"重新填写各个服务的 API 密钥。

### Q3: 如何判断导出文件是否已脱敏？

**A**: 打开 JSON 文件，检查：
- 所有 `api_key`、`password` 等字段的值是否为空字符串 `""`
- `users` 集合是否为空数组 `[]`

### Q4: 可以对单个集合进行脱敏导出吗？

**A**: 可以。通过 API 调用时，设置 `sanitize: true` 并指定 `collections` 数组。

### Q5: 脱敏会影响系统配置的结构吗？

**A**: 不会。脱敏只清空敏感字段的值，所有字段名和数据结构保持不变，导入后系统可以正常识别配置结构。

---

## 📝 更新日志

- **2025-10-24**: 初始版本，支持自动脱敏导出功能

