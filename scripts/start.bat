@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

echo.
echo ============================================
echo    🐉 来财 (LaiCai) — 启动脚本
echo ============================================
echo.

cd /d "%~dp0"

REM 检查 Python 是否可用
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境。
    echo 请先安装 Python 3.11+ (推荐 Miniconda)
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] 检查依赖...
pip show fastapi >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 检测到依赖未安装，正在安装...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败。
        pause
        exit /b 1
    )
)

echo [2/4] 检测同花顺路径...
python -c "from src.core.ths_path_resolver import resolve_ths_path; info = resolve_ths_path(); print(f'  状态: {'✅ 已找到' if info['found'] else '⚠️ 未找到'}'); print(f'  路径: {info[\"install_dir\"] or '未指定'}'); print(f'  来源: {info[\"source\"]}')" 2>nul

echo.
echo [3/4] 启动 LaiCai 后端服务...
echo [提示] 按 Ctrl+C 可停止服务
echo.

REM 启动 FastAPI
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload

echo.
echo [4/4] 服务已停止。
pause
