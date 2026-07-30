# 柳暗花明 绿色版：数据备份、还原与升级完全指南

> **作者**: 柳暗花明 团队  
> **日期**: 2025-11-06  
> **标签**: 绿色版, 数据备份, 升级指南, 运维

---

## 📋 目录

- [1. 什么是绿色版](#1-什么是绿色版)
- [2. 数据备份](#2-数据备份)
  - [2.1 需要备份的内容](#21-需要备份的内容)
  - [2.2 手动备份](#22-手动备份)
  - [2.3 自动备份脚本](#23-自动备份脚本)
- [3. 数据还原](#3-数据还原)
  - [3.1 完整还原](#31-完整还原)
  - [3.2 选择性还原](#32-选择性还原)
- [4. 版本升级](#4-版本升级)
  - [4.1 升级前准备](#41-升级前准备)
  - [4.2 升级步骤](#42-升级步骤)
  - [4.3 升级后验证](#43-升级后验证)
- [5. 常见问题](#5-常见问题)
- [6. 最佳实践](#6-最佳实践)

---

## 1. 什么是绿色版

**绿色版**（Portable Version）是指无需安装、解压即用的软件版本。柳暗花明 绿色版具有以下特点：

✅ **免安装**：解压到任意目录即可运行  
✅ **数据独立**：所有数据存储在程序目录内  
✅ **易于迁移**：整个文件夹可以直接复制到其他电脑  
✅ **多版本共存**：可以同时运行多个版本进行测试  

---

## 2. 数据备份

### 2.1 需要备份的内容

在 柳暗花明 绿色版中，以下内容需要定期备份：

#### �️ MongoDB 数据库（核心数据）

柳暗花明 使用 MongoDB 存储所有核心数据，这是**最重要**的备份内容：

| 数据库/集合 | 说明 | 重要性 | 大小估算 |
|-----------|------|--------|---------|
| **`lahm`** | 主数据库 | ⭐⭐⭐⭐⭐ | 1GB - 100GB |
| ├─ `stock_daily_quotes` | 股票日线数据（前复权） | ⭐⭐⭐⭐⭐ | 500MB - 50GB |
| ├─ `stock_basic_info` | 股票基本信息 | ⭐⭐⭐⭐⭐ | 10MB - 100MB |
| ├─ `news_data` | 新闻数据 | ⭐⭐⭐⭐ | 100MB - 10GB |
| ├─ `insider_sentiment` | 内部人情绪数据 | ⭐⭐⭐⭐ | 50MB - 5GB |
| ├─ `insider_transactions` | 内部人交易数据 | ⭐⭐⭐⭐ | 50MB - 5GB |
| ├─ `analysis_results` | 分析结果 | ⭐⭐⭐ | 10MB - 1GB |
| └─ `agent_conversations` | 智能体对话历史 | ⭐⭐⭐ | 10MB - 1GB |
| **`config`** | 配置数据库 | ⭐⭐⭐⭐ | < 10MB |
| └─ `system_config` | 系统配置 | ⭐⭐⭐⭐ | < 1MB |

#### � 配置文件

| 文件/目录 | 说明 | 重要性 | 大小估算 |
|----------|------|--------|---------|
| **`.env`** | 环境配置文件（包含 API Token） | ⭐⭐⭐⭐⭐ | < 10KB |
| **`config/`** | JSON 配置文件 | ⭐⭐⭐⭐ | < 1MB |
| **`logs/`** | 日志文件（可选） | ⭐⭐ | 10MB - 1GB |

---

### 2.2 MongoDB 数据备份

#### 方法 1：使用 mongodump（推荐）

**适用场景**：完整备份、定期备份、迁移数据

##### Windows 备份脚本

```powershell
# MongoDB 完整备份脚本
# 保存为：scripts/backup/backup_mongodb.ps1

param(
    [string]$MongoHost = "localhost",
    [int]$MongoPort = 27017,
    [string]$Database = "lahm",
    [string]$BackupDir = "C:\Backups\MongoDB"
)

# 创建备份目录
$backupDate = Get-Date -Format "yyyyMMdd_HHmmss"
$todayBackup = Join-Path $BackupDir "mongodb_$backupDate"
New-Item -ItemType Directory -Path $todayBackup -Force | Out-Null

Write-Host "🔄 开始备份 MongoDB 数据库..." -ForegroundColor Cyan
Write-Host "📊 数据库: $Database" -ForegroundColor Yellow
Write-Host "📁 备份目录: $todayBackup" -ForegroundColor Yellow

# 执行 mongodump
try {
    # 备份整个数据库
    mongodump --host $MongoHost --port $MongoPort --db $Database --out $todayBackup

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ MongoDB 备份成功！" -ForegroundColor Green

        # 压缩备份
        Write-Host "🗜️  压缩备份文件..." -ForegroundColor Yellow
        $zipFile = "$todayBackup.zip"
        Compress-Archive -Path $todayBackup -DestinationPath $zipFile -Force

        # 删除未压缩的备份
        Remove-Item -Path $todayBackup -Recurse -Force

        # 显示备份信息
        $backupSize = [math]::Round((Get-Item $zipFile).Length / 1MB, 2)
        Write-Host "📦 备份文件：$zipFile" -ForegroundColor Green
        Write-Host "📊 备份大小：$backupSize MB" -ForegroundColor Green
    } else {
        Write-Host "❌ MongoDB 备份失败！" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ 备份过程出错：$_" -ForegroundColor Red
    exit 1
}
```

##### Linux / macOS 备份脚本

```bash
#!/bin/bash
# MongoDB 完整备份脚本
# 保存为：scripts/backup/backup_mongodb.sh

MONGO_HOST="localhost"
MONGO_PORT=27017
DATABASE="lahm"
BACKUP_DIR="/backups/mongodb"

# 创建备份目录
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
TODAY_BACKUP="$BACKUP_DIR/mongodb_$BACKUP_DATE"
mkdir -p "$TODAY_BACKUP"

echo "🔄 开始备份 MongoDB 数据库..."
echo "📊 数据库: $DATABASE"
echo "📁 备份目录: $TODAY_BACKUP"

# 执行 mongodump
mongodump --host $MONGO_HOST --port $MONGO_PORT --db $DATABASE --out $TODAY_BACKUP

if [ $? -eq 0 ]; then
    echo "✅ MongoDB 备份成功！"

    # 压缩备份
    echo "🗜️  压缩备份文件..."
    tar -czf "$TODAY_BACKUP.tar.gz" -C "$BACKUP_DIR" "mongodb_$BACKUP_DATE"

    # 删除未压缩的备份
    rm -rf "$TODAY_BACKUP"

    # 显示备份信息
    BACKUP_SIZE=$(du -h "$TODAY_BACKUP.tar.gz" | cut -f1)
    echo "📦 备份文件：$TODAY_BACKUP.tar.gz"
    echo "📊 备份大小：$BACKUP_SIZE"
else
    echo "❌ MongoDB 备份失败！"
    exit 1
fi
```

##### 使用方法

```bash
# Windows
powershell -ExecutionPolicy Bypass -File scripts/backup/backup_mongodb.ps1

# Linux / macOS
chmod +x scripts/backup/backup_mongodb.sh
./scripts/backup/backup_mongodb.sh
```

---

#### 方法 2：备份特定集合

**适用场景**：只备份重要数据、节省空间

```bash
# Windows PowerShell
$backupDate = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "C:\Backups\MongoDB\partial_$backupDate"

# 只备份股票数据和配置
mongodump --host localhost --port 27017 --db lahm `
    --collection stock_daily_quotes `
    --collection stock_basic_info `
    --collection system_config `
    --out $backupDir

# 压缩
Compress-Archive -Path $backupDir -DestinationPath "$backupDir.zip" -Force
Remove-Item -Path $backupDir -Recurse -Force
```

```bash
# Linux / macOS
backup_date=$(date +%Y%m%d_%H%M%S)
backup_dir="/backups/mongodb/partial_$backup_date"

# 只备份股票数据和配置
mongodump --host localhost --port 27017 --db lahm \
    --collection stock_daily_quotes \
    --collection stock_basic_info \
    --collection system_config \
    --out $backup_dir

# 压缩
tar -czf "$backup_dir.tar.gz" -C /backups/mongodb "partial_$backup_date"
rm -rf "$backup_dir"
```

---

#### 方法 3：增量备份（高级）

**适用场景**：数据量大、需要频繁备份

```bash
# 使用 MongoDB Oplog 进行增量备份
# 需要 MongoDB 配置为副本集模式

# 首次完整备份
mongodump --host localhost --port 27017 --db lahm --out /backups/full

# 后续增量备份（只备份变化的数据）
mongodump --host localhost --port 27017 --oplog --out /backups/incremental_$(date +%Y%m%d_%H%M%S)
```

---

### 2.3 配置文件备份

除了 MongoDB 数据，还需要备份配置文件：

```bash
# Windows PowerShell
$backupDate = Get-Date -Format "yyyyMMdd_HHmmss"
$configBackup = "C:\Backups\Config_$backupDate"
New-Item -ItemType Directory -Path $configBackup -Force | Out-Null

# 备份配置文件
Copy-Item -Path "C:\Lahm\.env" -Destination $configBackup
Copy-Item -Path "C:\Lahm\config\*.json" -Destination $configBackup

# 压缩
Compress-Archive -Path $configBackup -DestinationPath "$configBackup.zip" -Force
Remove-Item -Path $configBackup -Recurse -Force

Write-Host "✅ 配置文件备份完成：$configBackup.zip" -ForegroundColor Green
```

---

### 2.4 自动备份脚本

#### Windows 自动备份脚本（MongoDB + 配置）

创建文件 `scripts/backup/auto_backup_all.ps1`：

```powershell
# 柳暗花明 完整自动备份脚本（MongoDB + 配置文件）
# 使用方法：在 Windows 任务计划程序中设置定时运行

param(
    [string]$MongoHost = "localhost",
    [int]$MongoPort = 27017,
    [string]$Database = "lahm",
    [string]$SourceDir = "C:\Lahm",
    [string]$BackupDir = "C:\Backups\柳暗花明",
    [int]$RetentionDays = 30  # 保留最近30天的备份
)

# 创建备份目录
$backupDate = Get-Date -Format "yyyyMMdd_HHmmss"
$todayBackup = Join-Path $BackupDir $backupDate
New-Item -ItemType Directory -Path $todayBackup -Force | Out-Null

Write-Host "🔄 开始完整备份 柳暗花明..." -ForegroundColor Cyan
Write-Host "📅 备份时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Yellow

# 1. 备份 MongoDB 数据库
Write-Host "`n� [1/3] 备份 MongoDB 数据库..." -ForegroundColor Yellow
$mongoBackupDir = Join-Path $todayBackup "mongodb"
try {
    mongodump --host $MongoHost --port $MongoPort --db $Database --out $mongoBackupDir --quiet
    if ($LASTEXITCODE -eq 0) {
        $mongoSize = (Get-ChildItem -Path $mongoBackupDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
        Write-Host "   ✅ MongoDB 备份成功 ($([math]::Round($mongoSize, 2)) MB)" -ForegroundColor Green
    } else {
        Write-Host "   ❌ MongoDB 备份失败！" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "   ❌ MongoDB 备份出错：$_" -ForegroundColor Red
    exit 1
}

# 2. 备份配置文件
Write-Host "`n� [2/3] 备份配置文件..." -ForegroundColor Yellow
$configBackupDir = Join-Path $todayBackup "config"
New-Item -ItemType Directory -Path $configBackupDir -Force | Out-Null

Copy-Item -Path "$SourceDir\.env" -Destination $configBackupDir -ErrorAction SilentlyContinue
Copy-Item -Path "$SourceDir\config\*.json" -Destination $configBackupDir -ErrorAction SilentlyContinue
Write-Host "   ✅ 配置文件备份成功" -ForegroundColor Green

# 3. 备份日志文件（可选，最近7天）
Write-Host "`n📝 [3/3] 备份最近日志..." -ForegroundColor Yellow
$logBackupDir = Join-Path $todayBackup "logs"
New-Item -ItemType Directory -Path $logBackupDir -Force | Out-Null

$sevenDaysAgo = (Get-Date).AddDays(-7)
Get-ChildItem -Path "$SourceDir\logs" -File |
    Where-Object { $_.LastWriteTime -gt $sevenDaysAgo } |
    Copy-Item -Destination $logBackupDir -ErrorAction SilentlyContinue
Write-Host "   ✅ 日志文件备份成功" -ForegroundColor Green

# 4. 压缩备份
Write-Host "`n🗜️  压缩备份文件..." -ForegroundColor Yellow
$zipFile = "$todayBackup.zip"
Compress-Archive -Path $todayBackup -DestinationPath $zipFile -Force

# 删除未压缩的备份目录
Remove-Item -Path $todayBackup -Recurse -Force

# 5. 清理旧备份
Write-Host "🧹 清理旧备份..." -ForegroundColor Yellow
$cutoffDate = (Get-Date).AddDays(-$RetentionDays)
$deletedCount = 0
Get-ChildItem -Path $BackupDir -Filter "*.zip" |
    Where-Object { $_.CreationTime -lt $cutoffDate } |
    ForEach-Object {
        Remove-Item $_.FullName -Force
        $deletedCount++
    }
Write-Host "   🗑️  删除了 $deletedCount 个旧备份" -ForegroundColor Gray

# 6. 显示备份摘要
Write-Host "`n✅ 备份完成！" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "📦 备份文件：$zipFile" -ForegroundColor Cyan
Write-Host "📊 备份大小：$([math]::Round((Get-Item $zipFile).Length / 1MB, 2)) MB" -ForegroundColor Cyan
Write-Host "📅 备份时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "🗂️  保留天数：$RetentionDays 天" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
```

#### 设置 Windows 定时任务

1. 打开"任务计划程序"（Task Scheduler）
2. 点击"创建基本任务"
3. 设置任务名称：`柳暗花明 自动备份`
4. 设置触发器：
   - **每天凌晨 2:00**（推荐）
   - 或**每周日凌晨 2:00**
5. 操作：启动程序
   - 程序：`powershell.exe`
   - 参数：`-ExecutionPolicy Bypass -File "C:\Lahm\scripts\backup\auto_backup_all.ps1"`
6. 完成设置

#### Linux / macOS 定时任务（Cron）

```bash
# 编辑 crontab
crontab -e

# 添加定时任务（每天凌晨 2:00 执行）
0 2 * * * /opt/Lahm/scripts/backup/backup_mongodb.sh >> /var/log/lahm_backup.log 2>&1
```

---

## 3. 数据还原

### 3.1 MongoDB 完整还原

**场景**：系统崩溃、重装系统、迁移到新电脑

#### 步骤 1：准备新环境

```bash
# 1. 安装 MongoDB
# Windows: 下载 MongoDB Community Server
# Linux: sudo apt-get install mongodb-org

# 2. 启动 MongoDB 服务
# Windows: net start MongoDB
# Linux: sudo systemctl start mongod

# 3. 确保 MongoDB 正常运行
mongo --eval "db.version()"
```

#### 步骤 2：还原 MongoDB 数据

##### Windows 还原脚本

```powershell
# MongoDB 数据还原脚本
# 保存为：scripts/restore/restore_mongodb.ps1

param(
    [string]$BackupFile = "C:\Backups\柳暗花明\20251106_020000.zip",
    [string]$MongoHost = "localhost",
    [int]$MongoPort = 27017,
    [string]$Database = "lahm",
    [switch]$Drop = $false  # 是否删除现有数据库
)

Write-Host "🔄 开始还原 MongoDB 数据库..." -ForegroundColor Cyan
Write-Host "📦 备份文件: $BackupFile" -ForegroundColor Yellow
Write-Host "📊 目标数据库: $Database" -ForegroundColor Yellow

# 1. 解压备份文件
$tempDir = "C:\Temp\MongoDB_Restore_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Write-Host "`n📂 解压备份文件..." -ForegroundColor Yellow
Expand-Archive -Path $BackupFile -DestinationPath $tempDir -Force

# 查找 MongoDB 备份目录
$mongoBackupDir = Get-ChildItem -Path $tempDir -Directory -Recurse -Filter "mongodb" | Select-Object -First 1
if (-not $mongoBackupDir) {
    Write-Host "❌ 未找到 MongoDB 备份目录！" -ForegroundColor Red
    Remove-Item -Path $tempDir -Recurse -Force
    exit 1
}

# 2. 执行 mongorestore
Write-Host "`n📊 还原 MongoDB 数据..." -ForegroundColor Yellow
try {
    $restoreArgs = @(
        "--host", $MongoHost,
        "--port", $MongoPort,
        "--db", $Database,
        "$($mongoBackupDir.FullName)\$Database"
    )

    if ($Drop) {
        Write-Host "⚠️  警告：将删除现有数据库！" -ForegroundColor Red
        $restoreArgs += "--drop"
    }

    & mongorestore $restoreArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n✅ MongoDB 数据还原成功！" -ForegroundColor Green
    } else {
        Write-Host "`n❌ MongoDB 数据还原失败！" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "`n❌ 还原过程出错：$_" -ForegroundColor Red
    exit 1
} finally {
    # 3. 清理临时文件
    Write-Host "`n🧹 清理临时文件..." -ForegroundColor Yellow
    Remove-Item -Path $tempDir -Recurse -Force
}

# 4. 验证还原结果
Write-Host "`n🔍 验证还原结果..." -ForegroundColor Yellow
$collections = mongo $Database --quiet --eval "db.getCollectionNames().join(',')"
Write-Host "   📋 集合列表: $collections" -ForegroundColor Cyan

$docCount = mongo $Database --quiet --eval "db.stock_daily_quotes.count()"
Write-Host "   📊 股票数据条数: $docCount" -ForegroundColor Cyan

Write-Host "`n✅ 还原完成！" -ForegroundColor Green
```

##### Linux / macOS 还原脚本

```bash
#!/bin/bash
# MongoDB 数据还原脚本
# 保存为：scripts/restore/restore_mongodb.sh

BACKUP_FILE="/backups/柳暗花明/20251106_020000.tar.gz"
MONGO_HOST="localhost"
MONGO_PORT=27017
DATABASE="lahm"
DROP_DB=false  # 是否删除现有数据库

echo "🔄 开始还原 MongoDB 数据库..."
echo "📦 备份文件: $BACKUP_FILE"
echo "📊 目标数据库: $DATABASE"

# 1. 解压备份文件
TEMP_DIR="/tmp/MongoDB_Restore_$(date +%Y%m%d_%H%M%S)"
echo -e "\n📂 解压备份文件..."
mkdir -p "$TEMP_DIR"
tar -xzf "$BACKUP_FILE" -C "$TEMP_DIR"

# 查找 MongoDB 备份目录
MONGO_BACKUP_DIR=$(find "$TEMP_DIR" -type d -name "mongodb" | head -n 1)
if [ -z "$MONGO_BACKUP_DIR" ]; then
    echo "❌ 未找到 MongoDB 备份目录！"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# 2. 执行 mongorestore
echo -e "\n📊 还原 MongoDB 数据..."
RESTORE_ARGS="--host $MONGO_HOST --port $MONGO_PORT --db $DATABASE $MONGO_BACKUP_DIR/$DATABASE"

if [ "$DROP_DB" = true ]; then
    echo "⚠️  警告：将删除现有数据库！"
    RESTORE_ARGS="$RESTORE_ARGS --drop"
fi

mongorestore $RESTORE_ARGS

if [ $? -eq 0 ]; then
    echo -e "\n✅ MongoDB 数据还原成功！"
else
    echo -e "\n❌ MongoDB 数据还原失败！"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# 3. 清理临时文件
echo -e "\n🧹 清理临时文件..."
rm -rf "$TEMP_DIR"

# 4. 验证还原结果
echo -e "\n🔍 验证还原结果..."
COLLECTIONS=$(mongo $DATABASE --quiet --eval "db.getCollectionNames().join(',')")
echo "   📋 集合列表: $COLLECTIONS"

DOC_COUNT=$(mongo $DATABASE --quiet --eval "db.stock_daily_quotes.count()")
echo "   📊 股票数据条数: $DOC_COUNT"

echo -e "\n✅ 还原完成！"
```

##### 使用方法

```bash
# Windows - 还原数据（保留现有数据）
powershell -ExecutionPolicy Bypass -File scripts/restore/restore_mongodb.ps1 `
    -BackupFile "C:\Backups\柳暗花明\20251106_020000.zip"

# Windows - 还原数据（删除现有数据）
powershell -ExecutionPolicy Bypass -File scripts/restore/restore_mongodb.ps1 `
    -BackupFile "C:\Backups\柳暗花明\20251106_020000.zip" `
    -Drop

# Linux / macOS
chmod +x scripts/restore/restore_mongodb.sh
./scripts/restore/restore_mongodb.sh
```

#### 步骤 3：还原配置文件

```bash
# Windows PowerShell
$backupZip = "C:\Backups\柳暗花明\20251106_020000.zip"
$tempDir = "C:\Temp\Config_Restore"

# 解压
Expand-Archive -Path $backupZip -DestinationPath $tempDir -Force

# 还原配置文件
Copy-Item -Path "$tempDir\config\.env" -Destination "C:\Lahm\" -Force
Copy-Item -Path "$tempDir\config\*.json" -Destination "C:\Lahm\config\" -Force

# 清理
Remove-Item -Path $tempDir -Recurse -Force

Write-Host "✅ 配置文件还原完成" -ForegroundColor Green
```

#### 步骤 4：验证还原

```bash
# Windows PowerShell
# 1. 检查 MongoDB 连接
mongo lahm --eval "db.stats()"

# 2. 检查数据量
mongo lahm --eval "db.stock_daily_quotes.count()"

# 3. 检查配置文件
Get-Content "C:\Lahm\.env" | Select-String "TUSHARE_TOKEN"

# 4. 启动服务测试
cd C:\Lahm
python -m lahm.cli start
```

---

### 3.2 选择性还原

**场景**：只需要还原部分数据

#### 只还原特定集合

```bash
# Windows PowerShell
# 只还原股票基本信息和配置
$backupZip = "C:\Backups\柳暗花明\20251106_020000.zip"
$tempDir = "C:\Temp\Partial_Restore"

# 解压
Expand-Archive -Path $backupZip -DestinationPath $tempDir -Force

# 查找 MongoDB 备份目录
$mongoBackupDir = Get-ChildItem -Path $tempDir -Directory -Recurse -Filter "mongodb" | Select-Object -First 1

# 只还原特定集合
mongorestore --host localhost --port 27017 `
    --db lahm `
    --collection stock_basic_info `
    "$($mongoBackupDir.FullName)\lahm\stock_basic_info.bson"

mongorestore --host localhost --port 27017 `
    --db lahm `
    --collection system_config `
    "$($mongoBackupDir.FullName)\lahm\system_config.bson"

# 清理
Remove-Item -Path $tempDir -Recurse -Force
```

#### 只还原特定日期范围的数据

```bash
# 使用 MongoDB 查询还原特定日期的数据
# 1. 先完整还原到临时数据库
mongorestore --host localhost --port 27017 --db temp_restore backup/lahm

# 2. 从临时数据库复制特定日期的数据
mongo lahm --eval '
db.stock_daily_quotes.insertMany(
    db.getSiblingDB("temp_restore").stock_daily_quotes.find({
        trade_date: { $gte: "2025-01-01", $lte: "2025-11-06" }
    }).toArray()
)
'

# 3. 删除临时数据库
mongo temp_restore --eval "db.dropDatabase()"
```

---

## 4. 版本升级

### 4.1 升级前准备

#### ✅ 升级前检查清单

- [ ] 阅读新版本的 Release Notes
- [ ] 检查是否有破坏性变更（Breaking Changes）
- [ ] 完整备份当前版本（参考 2.2 节）
- [ ] 记录当前版本号
- [ ] 确保有足够的磁盘空间
- [ ] 关闭所有正在运行的 柳暗花明 进程

#### 查看当前版本

```bash
# 方法 1：查看代码
python -c "import lahm; print(lahm.__version__)"

# 方法 2：查看 git 标签
cd C:\Lahm
git describe --tags

# 方法 3：查看 README
Get-Content README.md | Select-String "版本"
```

---

### 4.2 升级步骤

#### 方法 1：原地升级（推荐）

**优点**：保留所有数据和配置  
**缺点**：如果升级失败，需要还原备份

```bash
# Windows PowerShell
cd C:\Lahm

# 1. 停止服务
Stop-Process -Name "python" -Force

# 2. 备份当前版本
$backupDate = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item -Path ".env" -Destination ".env.backup_$backupDate"
Copy-Item -Path "config" -Destination "config.backup_$backupDate" -Recurse

# 3. 拉取最新代码
git fetch --all
git pull origin main

# 4. 更新依赖
pip install -r requirements.txt --upgrade

# 5. 检查配置文件变化
# 对比 .env.example 和 .env，看是否有新增配置项
code --diff .env.example .env

# 6. 运行数据库迁移（如果有）
python scripts/setup/migrate_database.py

# 7. 重启服务
python -m lahm.cli start
```

#### 方法 2：并行升级（最安全）

**优点**：新旧版本共存，可以对比测试  
**缺点**：占用更多磁盘空间

```bash
# Windows PowerShell
# 1. 下载新版本到新目录
cd C:\
git clone https://github.com/yourusername/Lahm.git Lahm_v2

# 2. 复制配置文件
Copy-Item -Path "C:\Lahm\.env" -Destination "C:\Lahm_v2\"

# 3. 复制数据文件（可选，如果数据量大可以共享）
# 方式 A：复制数据
Copy-Item -Path "C:\Lahm\data" -Destination "C:\Lahm_v2\data" -Recurse

# 方式 B：创建符号链接（共享数据）
New-Item -ItemType SymbolicLink -Path "C:\Lahm_v2\data" -Target "C:\Lahm\data"

# 4. 安装依赖
cd C:\Lahm_v2
pip install -r requirements.txt

# 5. 测试新版本
python -m lahm.cli --version

# 6. 如果测试通过，停止旧版本，启动新版本
# 如果测试失败，继续使用旧版本
```

---

### 4.3 升级后验证

#### 验证清单

```bash
# 1. 检查版本号
python -c "import lahm; print(lahm.__version__)"

# 2. 检查配置文件
python -c "from lahm.config import get_config; print(get_config())"

# 3. 检查数据库连接
python scripts/validation/check_dependencies.py

# 4. 运行测试
python -m pytest tests/ -v

# 5. 测试核心功能
python scripts/validation/test_market_analyst_lookback.py

# 6. 查看日志
Get-Content logs/lahm.log -Tail 50
```

#### 常见升级问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 配置文件缺少新参数 | 新版本增加了配置项 | 对比 `.env.example`，添加缺失的配置 |
| 依赖包版本冲突 | requirements.txt 更新 | `pip install -r requirements.txt --upgrade --force-reinstall` |
| 数据库结构变化 | 数据模型更新 | 运行迁移脚本 `python scripts/setup/migrate_database.py` |
| 提示词模板不兼容 | 提示词格式变化 | 删除 `prompts/` 目录，使用新版本的默认模板 |

---

## 5. 常见问题

### Q1: MongoDB 备份文件太大怎么办？

**A**: 有几种方法可以减小备份文件大小：

#### 方法 1：只备份重要集合

```bash
# 只备份股票数据和配置，不备份日志和临时数据
mongodump --host localhost --port 27017 --db lahm \
    --collection stock_daily_quotes \
    --collection stock_basic_info \
    --collection system_config \
    --out /backups/mongodb_essential
```

#### 方法 2：备份特定日期范围

```bash
# 只备份最近3个月的数据
$threeMonthsAgo = (Get-Date).AddMonths(-3).ToString("yyyy-MM-dd")
mongodump --host localhost --port 27017 --db lahm \
    --collection stock_daily_quotes \
    --query "{trade_date: {\$gte: '$threeMonthsAgo'}}" \
    --out /backups/mongodb_recent
```

#### 方法 3：使用压缩

```bash
# mongodump 自带压缩功能
mongodump --host localhost --port 27017 --db lahm \
    --gzip \
    --out /backups/mongodb_compressed
```

---

### Q2: 还原数据时提示"duplicate key error"怎么办？

**A**: 这是因为目标数据库中已经存在相同的数据。有两种解决方案：

#### 方案 1：删除现有数据库后还原（推荐）

```bash
# Windows PowerShell
# 使用 --drop 参数
mongorestore --host localhost --port 27017 --db lahm --drop backup/lahm
```

#### 方案 2：手动删除冲突的集合

```bash
# 删除特定集合
mongo lahm --eval "db.stock_daily_quotes.drop()"

# 然后还原
mongorestore --host localhost --port 27017 --db lahm backup/lahm
```

---

### Q3: 如何验证备份文件的完整性？

**A**: 可以通过以下方法验证：

```bash
# Windows PowerShell
# 1. 检查备份文件大小
$backupFile = "C:\Backups\柳暗花明\20251106_020000.zip"
$fileSize = [math]::Round((Get-Item $backupFile).Length / 1MB, 2)
Write-Host "备份文件大小: $fileSize MB"

# 2. 解压并检查内容
$tempDir = "C:\Temp\Verify_Backup"
Expand-Archive -Path $backupFile -DestinationPath $tempDir -Force

# 3. 检查 MongoDB 备份目录
$mongoBackupDir = Get-ChildItem -Path $tempDir -Directory -Recurse -Filter "mongodb"
if ($mongoBackupDir) {
    Write-Host "✅ MongoDB 备份目录存在"
    Get-ChildItem -Path $mongoBackupDir.FullName -Recurse | Measure-Object -Property Length -Sum
} else {
    Write-Host "❌ MongoDB 备份目录不存在"
}

# 4. 检查配置文件
if (Test-Path "$tempDir\config\.env") {
    Write-Host "✅ 配置文件存在"
} else {
    Write-Host "❌ 配置文件不存在"
}

# 清理
Remove-Item -Path $tempDir -Recurse -Force
```

---

### Q4: 如何在多台电脑之间同步数据？

**A**: 有几种方案：

#### 方案 1：使用 MongoDB 副本集（推荐生产环境）

```bash
# 配置 MongoDB 副本集，实现自动同步
# 参考 MongoDB 官方文档：https://docs.mongodb.com/manual/replication/
```

#### 方案 2：定期备份并同步到云存储

```bash
# 1. 备份到本地
powershell -File scripts/backup/backup_mongodb.ps1

# 2. 同步到云存储（例如 OneDrive）
$backupFile = Get-ChildItem "C:\Backups\柳暗花明" -Filter "*.zip" |
    Sort-Object CreationTime -Descending |
    Select-Object -First 1

Copy-Item -Path $backupFile.FullName -Destination "D:\OneDrive\柳暗花明\Backups\"
```

#### 方案 3：使用 MongoDB Atlas（云数据库）

```bash
# 将数据迁移到 MongoDB Atlas
# 所有电脑连接到同一个云数据库
# 修改 .env 文件：
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/lahm
```

---

### Q5: 升级后 MongoDB 数据丢失怎么办？

**A**: 从最近的备份还原：

```bash
# 1. 查找最近的备份
Get-ChildItem "C:\Backups\柳暗花明" -Filter "*.zip" |
    Sort-Object CreationTime -Descending |
    Select-Object -First 1

# 2. 还原 MongoDB 数据
$latestBackup = "C:\Backups\柳暗花明\20251106_020000.zip"
powershell -ExecutionPolicy Bypass -File scripts/restore/restore_mongodb.ps1 `
    -BackupFile $latestBackup `
    -Drop

# 3. 验证数据
mongo lahm --eval "db.stock_daily_quotes.count()"
```

---

### Q6: 如何迁移到新电脑？

**A**: 完整迁移步骤：

#### 步骤 1：在旧电脑上备份

```bash
# 1. 备份 MongoDB
powershell -File scripts/backup/backup_mongodb.ps1

# 2. 备份配置文件
Copy-Item -Path "C:\Lahm\.env" -Destination "C:\Backups\柳暗花明\"
Copy-Item -Path "C:\Lahm\config" -Destination "C:\Backups\柳暗花明\config" -Recurse
```

#### 步骤 2：传输备份文件

```bash
# 使用 U 盘、网络共享或云存储传输备份文件到新电脑
```

#### 步骤 3：在新电脑上还原

```bash
# 1. 安装 Python、MongoDB
# 2. 下载 柳暗花明 绿色版
# 3. 还原 MongoDB 数据
powershell -File scripts/restore/restore_mongodb.ps1 -BackupFile "备份文件路径"

# 4. 还原配置文件
Copy-Item -Path "备份目录\.env" -Destination "C:\Lahm\"
Copy-Item -Path "备份目录\config\*" -Destination "C:\Lahm\config\"

# 5. 启动服务
python -m lahm.cli start
```

---

### Q7: 如何回滚到旧版本？

**A**: 使用 git 回滚代码，然后还原对应版本的数据：

```bash
# 1. 备份当前数据
powershell -File scripts/backup/backup_mongodb.ps1

# 2. 回滚代码到旧版本
cd C:\Lahm
git log --oneline --decorate
git checkout v1.0.0

# 3. 如果数据结构有变化，还原旧版本的数据备份
powershell -File scripts/restore/restore_mongodb.ps1 `
    -BackupFile "C:\Backups\柳暗花明\v1.0.0_backup.zip" `
    -Drop

# 4. 重启服务
python -m lahm.cli start
```

---

## 6. 最佳实践

### 📅 备份策略建议

#### MongoDB 数据备份策略

| 备份类型 | 频率 | 保留时间 | 备份内容 | 适用场景 |
|---------|------|---------|---------|---------|
| **完整备份** | 每周日凌晨 | 4周 | 所有 MongoDB 数据 + 配置 | 重大版本升级前 |
| **增量备份** | 每天凌晨 2:00 | 7天 | MongoDB 数据 | 日常使用 |
| **配置备份** | 修改配置后立即 | 永久 | .env + config/*.json | 修改配置前 |
| **升级前备份** | 升级前 | 永久 | 所有数据 + 配置 | 版本升级 |
| **测试前备份** | 测试新功能前 | 测试完成后 | 相关数据 | 功能测试 |

#### 备份保留策略（3-2-1 原则）

- **3 份副本**：原始数据 + 2 份备份
- **2 种介质**：本地硬盘 + 云存储/移动硬盘
- **1 份异地**：至少 1 份备份存储在不同地点

```
示例：
├─ 原始数据：C:\Lahm\（MongoDB 运行中）
├─ 本地备份：C:\Backups\柳暗花明\（本地硬盘）
├─ 云端备份：OneDrive\柳暗花明\Backups\（云存储）
└─ 异地备份：移动硬盘（每周同步一次）
```

---

### 🔒 安全建议

#### 1. 加密备份文件

MongoDB 备份包含敏感的股票数据和配置信息，务必加密：

```bash
# Windows - 使用 7-Zip 加密
7z a -p"your_strong_password" -mhe=on `
    "C:\Backups\柳暗花明\encrypted_backup.7z" `
    "C:\Backups\柳暗花明\20251106_020000.zip"

# Linux - 使用 GPG 加密
gpg --symmetric --cipher-algo AES256 backup.tar.gz
```

#### 2. 异地备份

**云存储备份**：

```powershell
# 自动同步到 OneDrive
$backupFile = Get-ChildItem "C:\Backups\柳暗花明" -Filter "*.zip" |
    Sort-Object CreationTime -Descending |
    Select-Object -First 1

# 复制到 OneDrive
Copy-Item -Path $backupFile.FullName `
    -Destination "D:\OneDrive\柳暗花明\Backups\" `
    -Force

Write-Host "✅ 备份已同步到 OneDrive" -ForegroundColor Green
```

**移动硬盘备份**：

```bash
# 每周同步到移动硬盘
robocopy "C:\Backups\柳暗花明" "E:\Lahm_Backups" /MIR /Z /W:5
```

#### 3. 保护敏感信息

```bash
# .env 文件包含 API Token，单独加密存储
$envFile = "C:\Lahm\.env"
$encryptedEnv = "C:\Backups\Config\.env.encrypted"

# 使用 Windows DPAPI 加密
$content = Get-Content $envFile -Raw
$secureString = ConvertTo-SecureString $content -AsPlainText -Force
$encrypted = ConvertFrom-SecureString $secureString
Set-Content -Path $encryptedEnv -Value $encrypted
```

---

### ⚡ 性能优化

#### 1. MongoDB 备份性能优化

```bash
# 使用并行备份（多线程）
mongodump --host localhost --port 27017 --db lahm \
    --numParallelCollections=4 \
    --gzip \
    --out /backups/mongodb

# 只备份索引定义，不备份索引数据（减小备份大小）
mongodump --host localhost --port 27017 --db lahm \
    --excludeCollectionsWithPrefix=system. \
    --out /backups/mongodb
```

#### 2. 增量备份（减少备份时间）

```bash
# 首次完整备份
mongodump --host localhost --port 27017 --db lahm \
    --out /backups/full_backup

# 后续只备份变化的数据（需要 MongoDB 副本集）
mongodump --host localhost --port 27017 \
    --oplog \
    --out /backups/incremental_$(date +%Y%m%d)
```

#### 3. 压缩备份文件

```bash
# mongodump 自带 gzip 压缩（推荐）
mongodump --host localhost --port 27017 --db lahm \
    --gzip \
    --out /backups/mongodb_compressed

# 压缩率对比：
# - 不压缩：1000 MB
# - gzip：200-300 MB（压缩率 70-80%）
# - 7z 最高压缩：150-200 MB（压缩率 80-85%）
```

#### 4. 备份时避免影响性能

```bash
# 在 MongoDB 从节点上备份（不影响主节点性能）
mongodump --host secondary-node --port 27017 --db lahm \
    --out /backups/mongodb

# 或者在低峰时段备份（凌晨 2:00-4:00）
```

---

### 📊 监控和告警

#### 1. 备份成功率监控

```powershell
# 在备份脚本中添加日志记录
$logFile = "C:\Logs\backup_history.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

if ($LASTEXITCODE -eq 0) {
    Add-Content -Path $logFile -Value "$timestamp | SUCCESS | Backup completed"
} else {
    Add-Content -Path $logFile -Value "$timestamp | FAILED | Backup failed"

    # 发送告警邮件
    Send-MailMessage -To "admin@example.com" `
        -From "backup@example.com" `
        -Subject "柳暗花明 备份失败" `
        -Body "备份任务执行失败，请检查日志" `
        -SmtpServer "smtp.example.com"
}
```

#### 2. 备份文件大小监控

```powershell
# 检查备份文件大小是否异常
$backupFile = Get-ChildItem "C:\Backups\柳暗花明" -Filter "*.zip" |
    Sort-Object CreationTime -Descending |
    Select-Object -First 1

$fileSize = $backupFile.Length / 1MB

# 如果备份文件小于 100MB，可能备份不完整
if ($fileSize -lt 100) {
    Write-Host "⚠️  警告：备份文件异常小 ($fileSize MB)" -ForegroundColor Red
    # 发送告警
}
```

---

### 🧪 定期测试还原

**重要**：定期测试备份文件是否可以成功还原！

```bash
# 每月测试一次还原流程
# 1. 在测试环境还原备份
mongorestore --host test-server --port 27017 --db lahm_test \
    backup/lahm

# 2. 验证数据完整性
mongo lahm_test --eval "
    var count = db.stock_daily_quotes.count();
    print('数据条数: ' + count);
    if (count < 1000) {
        print('❌ 数据不完整');
        quit(1);
    } else {
        print('✅ 数据完整');
    }
"

# 3. 清理测试数据
mongo lahm_test --eval "db.dropDatabase()"
```

---

## 📚 相关文档

- [安装指南](../guides/installation/README.md)
- [配置指南](../guides/configuration/README.md)
- [故障排除](../troubleshooting/common-issues/README.md)
- [开发文档](../development/README.md)

---

## 🆘 获取帮助

如果在备份、还原或升级过程中遇到问题：

1. 查看 [常见问题](../troubleshooting/common-issues/README.md)
2. 搜索 [GitHub Issues](https://github.com/yourusername/Lahm/issues)
3. 加入社区讨论群
4. 提交新的 Issue

---

**最后更新**: 2025-11-06  
**适用版本**: 柳暗花明 v1.0.0+

