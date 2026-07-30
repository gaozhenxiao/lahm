@echo off
chcp 65001 >nul
REM 柳暗花明 Docker服务启动脚本
REM 启动MongoDB、Redis和Redis Commander

echo ========================================
echo 柳暗花明 Docker Service Startup
echo ========================================

REM 检查Docker是否运行
echo Checking Docker service status...
docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running or not installed
    echo Please start Docker Desktop first
    pause
    exit /b 1
)
echo [OK] Docker service is running

echo.
echo Starting database services...

REM 启动MongoDB
echo Starting MongoDB...
docker run -d ^
    --name lahm-mongodb ^
    -p 27017:27017 ^
    -e MONGO_INITDB_ROOT_USERNAME=admin ^
    -e MONGO_INITDB_ROOT_PASSWORD=lahm123 ^
    -e MONGO_INITDB_DATABASE=lahm ^
    -v mongodb_data:/data/db ^
    --restart unless-stopped ^
    mongo:4.4

if %errorlevel% equ 0 (
    echo [OK] MongoDB started successfully - Port: 27017
) else (
    echo [WARN] MongoDB may already be running or failed to start
)

REM 启动Redis
echo Starting Redis...
docker run -d ^
    --name lahm-redis ^
    -p 6379:6379 ^
    -v redis_data:/data ^
    --restart unless-stopped ^
    redis:latest redis-server --appendonly yes --requirepass lahm123

if %errorlevel% equ 0 (
    echo [OK] Redis started successfully - Port: 6379
) else (
    echo [WARN] Redis may already be running or failed to start
)

REM 等待服务启动
echo Waiting for services to start...
timeout /t 5 /nobreak >nul

REM 启动Redis Commander (可选的Redis管理界面)
echo Starting Redis Commander...
docker run -d ^
    --name lahm-redis-commander ^
    -p 8081:8081 ^
    -e REDIS_HOSTS=local:lahm-redis:6379:0:lahm123 ^
    --link lahm-redis:redis ^
    --restart unless-stopped ^
    rediscommander/redis-commander:latest

if %errorlevel% equ 0 (
    echo [OK] Redis Commander started - Access: http://localhost:8081
) else (
    echo [WARN] Redis Commander may already be running or failed to start
)

echo.
echo Checking service status...
docker ps --filter "name=lahm-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo.
echo ========================================
echo Docker services startup completed!
echo ========================================
echo.
echo MongoDB:
echo    - Connection: mongodb://admin:lahm123@localhost:27017/lahm
echo    - Port: 27017
echo    - Username: admin
echo    - Password: lahm123
echo.
echo Redis:
echo    - Connection: redis://localhost:6379
echo    - Port: 6379
echo    - Password: lahm123
echo.
echo Redis Commander:
echo    - Web Interface: http://localhost:8081
echo.
echo Tips:
echo    - Use stop_docker_services.bat to stop all services
echo    - Use docker logs [container_name] to view logs
echo    - Data will be persisted in Docker volumes
echo.

pause
