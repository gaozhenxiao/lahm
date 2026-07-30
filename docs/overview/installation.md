# 详细安装指南

## 概述

本指南提供了 柳暗花明 框架的详细安装说明，包括不同操作系统的安装步骤、依赖管理、环境配置和常见问题解决方案。

## 系统要求

### 硬件要求
- **CPU**: 双核 2.0GHz 或更高 (推荐四核)
- **内存**: 最少 4GB RAM (推荐 8GB 或更高)
- **存储**: 至少 5GB 可用磁盘空间
- **网络**: 稳定的互联网连接 (用于API调用和数据获取)

### 软件要求
- **操作系统**: 
  - Windows 10/11 (64位)
  - macOS 10.15 (Catalina) 或更高版本
  - Linux (Ubuntu 18.04+, CentOS 7+, 或其他主流发行版)
- **Python**: 3.10, 3.11, 或 3.12 (推荐 3.11)
- **Git**: 用于克隆代码仓库

## 安装步骤

### 1. 安装 Python

#### Windows
```powershell
# 方法1: 从官网下载安装包
# 访问 https://www.python.org/downloads/windows/
# 下载 Python 3.11.x 安装包并运行

# 方法2: 使用 Chocolatey
choco install python311

# 方法3: 使用 Microsoft Store
# 在 Microsoft Store 搜索 "Python 3.11" 并安装

# 验证安装
python --version
pip --version
```

#### macOS
```bash
# 方法1: 使用 Homebrew (推荐)
brew install python@3.11

# 方法2: 使用 pyenv
brew install pyenv
pyenv install 3.11.7
pyenv global 3.11.7

# 方法3: 从官网下载
# 访问 https://www.python.org/downloads/macos/

# 验证安装
python3 --version
pip3 --version
```

#### Linux (Ubuntu/Debian)
```bash
# 更新包列表
sudo apt update

# 安装 Python 3.11
sudo apt install python3.11 python3.11-pip python3.11-venv

# 设置默认 Python 版本 (可选)
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# 验证安装
python3 --version
pip3 --version
```

#### Linux (CentOS/RHEL)
```bash
# 安装 EPEL 仓库
sudo yum install epel-release

# 安装 Python 3.11
sudo yum install python311 python311-pip

# 或使用 dnf (较新版本)
sudo dnf install python3.11 python3.11-pip

# 验证安装
python3.11 --version
pip3.11 --version
```

### 2. 克隆项目

```bash
# 克隆项目仓库
git clone https://github.com/TauricResearch/TradingAgents.git

# 进入项目目录
cd 柳暗花明

# 查看项目结构
ls -la
```

### 3. 创建虚拟环境

#### 使用 venv (推荐)
```bash
# Windows
python -m venv lahm
lahm\Scripts\activate

# macOS/Linux
python3 -m venv lahm
source lahm/bin/activate

# 验证虚拟环境
which python  # 应该指向虚拟环境中的 Python
```

#### 使用 conda
```bash
# 创建环境
conda create -n lahm python=3.11

# 激活环境
conda activate lahm

# 验证环境
conda info --envs
```

#### 使用 pipenv
```bash
# 安装 pipenv
pip install pipenv

# 创建环境并安装依赖
pipenv install

# 激活环境
pipenv shell
```

### 4. 安装依赖

#### 基础安装
```bash
# 升级 pip
pip install --upgrade pip

# 安装项目依赖
pip install -r requirements.txt

# 验证安装
pip list | grep langchain
pip list | grep lahm
```

#### 开发环境安装
```bash
# 安装开发依赖 (如果有 requirements-dev.txt)
pip install -r requirements-dev.txt

# 或安装可编辑模式
pip install -e .

# 安装额外的开发工具
pip install pytest black flake8 mypy jupyter
```

#### 可选依赖
```bash
# Redis 支持 (用于高级缓存)
pip install redis

# 数据库支持
pip install sqlalchemy psycopg2-binary

# 可视化支持
pip install matplotlib seaborn plotly

# Jupyter 支持
pip install jupyter ipykernel
python -m ipykernel install --user --name=lahm
```

### 5. 配置 API 密钥

#### 获取 API 密钥

**OpenAI API**
1. 访问 [OpenAI Platform](https://platform.openai.com/)
2. 注册账户并登录
3. 导航到 API Keys 页面
4. 创建新的 API 密钥
5. 复制密钥 (注意: 只显示一次)

**FinnHub API**
1. 访问 [FinnHub](https://finnhub.io/)
2. 注册免费账户
3. 在仪表板中找到 API 密钥
4. 复制密钥

**其他可选 API**
- **Anthropic**: [console.anthropic.com](https://console.anthropic.com/)
- **Google AI**: [ai.google.dev](https://ai.google.dev/)

#### 设置环境变量

**Windows (PowerShell)**
```powershell
# 临时设置 (当前会话)
$env:OPENAI_API_KEY="your_openai_api_key"
$env:FINNHUB_API_KEY="your_finnhub_api_key"

# 永久设置 (系统环境变量)
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your_openai_api_key", "User")
[Environment]::SetEnvironmentVariable("FINNHUB_API_KEY", "your_finnhub_api_key", "User")
```

**Windows (Command Prompt)**
```cmd
# 临时设置
set OPENAI_API_KEY=your_openai_api_key
set FINNHUB_API_KEY=your_finnhub_api_key

# 永久设置 (需要重启)
setx OPENAI_API_KEY "your_openai_api_key"
setx FINNHUB_API_KEY "your_finnhub_api_key"
```

**macOS/Linux**
```bash
# 临时设置 (当前会话)
export OPENAI_API_KEY="your_openai_api_key"
export FINNHUB_API_KEY="your_finnhub_api_key"

# 永久设置 (添加到 ~/.bashrc 或 ~/.zshrc)
echo 'export OPENAI_API_KEY="your_openai_api_key"' >> ~/.bashrc
echo 'export FINNHUB_API_KEY="your_finnhub_api_key"' >> ~/.bashrc
source ~/.bashrc
```

#### 使用 .env 文件 (推荐)
```bash
# 创建 .env 文件
cat > .env << EOF
OPENAI_API_KEY=your_openai_api_key
FINNHUB_API_KEY=your_finnhub_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
GOOGLE_API_KEY=your_google_api_key
LAHM_RESULTS_DIR=./results
LAHM_LOG_LEVEL=INFO
EOF

# 安装 python-dotenv (如果未安装)
pip install python-dotenv
```

### 6. 验证安装

#### 基本验证
```bash
# 检查 Python 版本
python --version

# 检查已安装的包
pip list | grep -E "(langchain|lahm|openai|finnhub)"

# 检查环境变量
python -c "import os; print('OpenAI:', bool(os.getenv('OPENAI_API_KEY'))); print('FinnHub:', bool(os.getenv('FINNHUB_API_KEY')))"
```

#### 功能验证
```python
# test_installation.py
import sys
import os

def test_installation():
    """测试安装是否成功"""
    
    print("=== 柳暗花明 安装验证 ===\n")
    
    # 1. Python 版本检查
    print(f"Python 版本: {sys.version}")
    if sys.version_info < (3, 10):
        print("❌ Python 版本过低，需要 3.10 或更高版本")
        return False
    else:
        print("✅ Python 版本符合要求")
    
    # 2. 依赖包检查
    required_packages = [
        'langchain_openai',
        'langgraph',
        'finnhub',
        'pandas',
        'requests'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
            print(f"✅ {package} 已安装")
        except ImportError:
            print(f"❌ {package} 未安装")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n缺少依赖包: {missing_packages}")
        return False
    
    # 3. API 密钥检查
    api_keys = {
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
        'FINNHUB_API_KEY': os.getenv('FINNHUB_API_KEY')
    }
    
    for key_name, key_value in api_keys.items():
        if key_value:
            print(f"✅ {key_name} 已设置")
        else:
            print(f"❌ {key_name} 未设置")
    
    # 4. 柳暗花明 导入测试
    try:
        from lahm.graph.trading_graph import LahmGraph
        from lahm.default_config import DEFAULT_CONFIG
        print("✅ 柳暗花明 核心模块导入成功")
    except ImportError as e:
        print(f"❌ 柳暗花明 导入失败: {e}")
        return False
    
    print("\n🎉 安装验证完成!")
    return True

if __name__ == "__main__":
    success = test_installation()
    sys.exit(0 if success else 1)
```

运行验证脚本:
```bash
python test_installation.py
```

## 常见问题解决

### 1. Python 版本问题
```bash
# 问题: python 命令找不到或版本错误
# 解决方案:

# Windows: 使用 py 启动器
py -3.11 --version

# macOS/Linux: 使用具体版本
python3.11 --version

# 创建别名 (Linux/macOS)
alias python=python3.11
```

### 2. 权限问题
```bash
# 问题: pip 安装时权限被拒绝
# 解决方案:

# 使用用户安装
pip install --user -r requirements.txt

# 或使用虚拟环境 (推荐)
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows
```

### 3. 网络连接问题
```bash
# 问题: pip 安装超时或连接失败
# 解决方案:

# 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/

# 或配置永久镜像源
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple/
```

### 4. 依赖冲突问题
```bash
# 问题: 包版本冲突
# 解决方案:

# 清理环境重新安装
pip freeze > installed_packages.txt
pip uninstall -r installed_packages.txt -y
pip install -r requirements.txt

# 或使用新的虚拟环境
deactivate
rm -rf lahm  # 删除旧环境
python -m venv lahm
source lahm/bin/activate
pip install -r requirements.txt
```

### 5. API 密钥问题
```bash
# 问题: API 密钥无效或未设置
# 解决方案:

# 检查密钥格式
echo $OPENAI_API_KEY | wc -c  # 应该是 51 字符 (sk-...)

# 重新设置密钥
unset OPENAI_API_KEY
export OPENAI_API_KEY="your_correct_api_key"

# 测试 API 连接
python -c "
import openai
import os
client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
print('API 连接测试成功')
"
```

## 高级安装选项

### 1. Docker 安装
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

CMD ["python", "-m", "cli.main"]
```

```bash
# 构建镜像
docker build -t lahm .

# 运行容器
docker run -e OPENAI_API_KEY=$OPENAI_API_KEY -e FINNHUB_API_KEY=$FINNHUB_API_KEY lahm
```

### 2. 开发环境设置
```bash
# 安装开发工具
pip install pre-commit black isort flake8 mypy pytest

# 设置 pre-commit hooks
pre-commit install

# 配置 IDE (VS Code)
code --install-extension ms-python.python
code --install-extension ms-python.black-formatter
```

### 3. 性能优化
```bash
# 安装加速库
pip install numpy scipy numba

# GPU 支持 (如果需要)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

## 卸载指南

### 完全卸载
```bash
# 停用虚拟环境
deactivate

# 删除虚拟环境
rm -rf lahm  # Linux/macOS
rmdir /s lahm  # Windows

# 删除项目文件
cd ..
rm -rf 柳暗花明

# 清理环境变量 (可选)
unset OPENAI_API_KEY
unset FINNHUB_API_KEY
```

安装完成后，您可以继续阅读 [快速开始指南](quick-start.md) 来开始使用 柳暗花明。
