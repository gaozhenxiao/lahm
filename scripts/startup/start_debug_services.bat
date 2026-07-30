@echo off
echo ========================================
echo Starting Debug MongoDB and Redis
echo ========================================

echo Checking Docker...
docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker not running
    pause
    exit /b 1
)

echo Cleaning up existing containers...
docker stop lahm-mongodb lahm-redis 2>nul
docker rm lahm-mongodb lahm-redis 2>nul

echo Starting MongoDB on port 27017...
docker run -d ^
    --name lahm-mongodb ^
    -p 27017:27017 ^
    -e MONGO_INITDB_ROOT_USERNAME=admin ^
    -e MONGO_INITDB_ROOT_PASSWORD=lahm123 ^
    -e MONGO_INITDB_DATABASE=lahm ^
    --restart unless-stopped ^
    mongo:4.4

if %errorlevel% equ 0 (
    echo [OK] MongoDB started successfully
) else (
    echo [ERROR] MongoDB failed to start
)

echo Starting Redis on port 6379...
docker run -d ^
    --name lahm-redis ^
    -p 6379:6379 ^
    --restart unless-stopped ^
    redis:latest redis-server --appendonly yes --requirepass lahm123

if %errorlevel% equ 0 (
    echo [OK] Redis started successfully
) else (
    echo [ERROR] Redis failed to start
)

echo Waiting 10 seconds for services to start...
timeout /t 10 /nobreak >nul

echo.
echo Service Status:
docker ps --filter "name=lahm-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo.
echo ========================================
echo Debug Services Started!
echo ========================================
echo MongoDB: localhost:27017
echo   Username: admin
echo   Password: lahm123
echo   Database: lahm
echo.
echo Redis: localhost:6379
echo   Password: lahm123
echo.
echo To stop services: docker stop lahm-mongodb lahm-redis
echo.

pause
