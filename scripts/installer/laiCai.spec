# -*- mode: python ; coding: utf-8 -*-
"""
来财 (LaiCai) — PyInstaller 打包配置
将 Python 应用打包为 Windows 原生可执行文件。

使用方法:
    cd D:\来财\Attract-wealth
    pyinstaller scripts\installer\laiCai.spec --clean --noconfirm
"""
import os
import sys
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / 'src'
DATA_DIR = ROOT_DIR / 'data'
CONFIG_DIR = ROOT_DIR / 'config'
SKILLS_DIR = ROOT_DIR / 'skills'

# 排除项 (减少体积)
EXCLUDES = [
    'tkinter',
    'matplotlib',
    'scipy',
    'numpy.testing',
    'jupyter',
    'notebook',
    'IPython',
    'pytest',
    'setuptools',
    'distutils',
]

# 隐藏导入 (PyInstaller 无法自动检测的模块)
HIDDEN_IMPORTS = [
    # 核心框架
    'fastapi',
    'uvicorn',
    'pydantic',
    'pydantic_settings',
    # LangGraph & LLM
    'langgraph',
    'langchain',
    'langchain_openai',
    # 数据源
    'akshare',
    'baostock',
    'tushare',
    # 数据库
    'lancedb',
    'sqlite3',
    # 交易通道
    'easytrader',
    # 前端 (可选打包)
    # MCP
    'mcp',
    # 工具
    'sse_starlette',
    'aiohttp',
    'requests',
    # 内部模块
    'src.core',
    'src.agents',
    'src.dataflows',
    'src.evolution',
    'src.execution',
    'src.routers',
    'src.mcp',
    'src.channels',
    'src.graph',
    'src.llm',
    'src.frontend',
]

# 数据文件收集
DATAS = []

# 配置文件
if CONFIG_DIR.exists():
    DATAS.append((str(CONFIG_DIR), 'config'))

# 技能文件
if SKILLS_DIR.exists():
    DATAS.append((str(SKILLS_DIR), 'skills'))

# 前端构建产物 (如果存在)
FRONTEND_DIST = SRC_DIR / 'frontend' / 'dist'
if FRONTEND_DIST.exists():
    DATAS.append((str(FRONTEND_DIST), 'frontend/dist'))

# 模板文件
TEMPLATES_DIR = SRC_DIR / 'templates'
if TEMPLATES_DIR.exists():
    DATAS.append((str(TEMPLATES_DIR), 'templates'))

a = Analysis(
    [str(SRC_DIR / 'main.py')],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='laiCai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 保留控制台用于调试，生产可改为 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可添加 .ico 文件
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='laiCai',
)
