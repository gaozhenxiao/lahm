@echo off
REM 柳暗花明 Docker服务停止脚本
REM 停止MongoDB、Redis和Redis Commander

echo ========================================
echo 柳暗花明 Docker服务停止脚本
echo ========================================

echo 🛑 停止柳暗花明相关服务...

REM 停止Redis Commander
echo 📊 停止Redis Commander...
docker stop lahm-redis-commander 2>nul
docker rm lahm-redis-commander 2>nul

REM 停止Redis
echo 📦 停止Redis...
docker stop lahm-redis 2>nul
docker rm lahm-redis 2>nul

REM 停止MongoDB
echo 📊 停止MongoDB...
docker stop lahm-mongodb 2>nul
docker rm lahm-mongodb 2>nul

echo.
echo 📋 检查剩余容器...
docker ps --filter "name=lahm-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo.
echo ========================================
echo ✅ 所有柳暗花明服务已停止
echo ========================================
echo.
echo 💡 提示:
echo    - 数据已保存在Docker卷中，下次启动时会自动恢复
echo    - 如需完全清理数据，请手动删除Docker卷:
echo      docker volume rm mongodb_data redis_data
echo.

pause
