# -*- mode: python ; coding: utf-8 -*-
"""
来财 (LaiCai) — PyInstaller 打包配置
将 Python 应用打包为 Windows 原生可执行文件。
兼容 GitHub Actions / 本地构建 / 任意路径。
"""
import os
from pathlib import Path

# PyInstaller 在运行时自动注入 SPECPATH (当前 .spec 文件所在目录)
spec_dir = Path(SPECPATH).resolve()

# 动态查找项目根目录 (寻找 pyproject.toml)
ROOT_DIR = spec_dir
while not (ROOT_DIR / 'pyproject.toml').exists():
    ROOT_DIR = ROOT_DIR.parent
    if ROOT_DIR == ROOT_DIR.parent:
        raise RuntimeError("无法找到项目根目录 (pyproject.toml not found)")

SRC_DIR = ROOT_DIR / 'src'
DATA_DIR = ROOT_DIR / 'data'
CONFIG_DIR = ROOT_DIR / 'config'
SKILLS_DIR = ROOT_DIR / 'skills'

print(f"[PyInstaller] Project Root: {ROOT_DIR}")
print(f"[PyInstaller] Source Dir: {SRC_DIR}")

# 排除项 (减少体积)
EXCLUDES = [
    'tkinter', 'matplotlib', 'scipy', 'numpy.testing',
    'jupyter', 'notebook', 'IPython', 'pytest', 'setuptools', 'distutils',
]

# 隐藏导入 (PyInstaller 无法自动检测的模块)
HIDDEN_IMPORTS = [
    'fastapi', 'uvicorn', 'pydantic', 'pydantic_settings',
    'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'langgraph', 'langgraph.graph', 'langgraph.prebuilt',
    'langchain', 'langchain_openai', 'langchain_core',
    'akshare', 'baostock', 'tushare',
    'lancedb', 'sqlite3', 'easytrader', 'sse_starlette',
    'aiohttp', 'requests', 'psutil', 'pywinauto', 'pyautogui', 'pillow',
    'src.core', 'src.agents', 'src.dataflows', 'src.evolution',
    'src.execution', 'src.routers', 'src.mcp', 'src.channels',
    'src.graph', 'src.llm', 'src.frontend',
]

# 数据文件收集
DATAS = [
    (str(ROOT_DIR / 'pyproject.toml'), '.'),
]
if CONFIG_DIR.exists():
    DATAS.append((str(CONFIG_DIR), 'config'))
if SKILLS_DIR.exists():
    DATAS.append((str(SKILLS_DIR), 'skills'))
if DATA_DIR.exists():
    DATAS.append((str(DATA_DIR), 'data'))

FRONTEND_DIST = SRC_DIR / 'frontend' / 'dist'
if FRONTEND_DIST.exists():
    DATAS.append((str(FRONTEND_DIST), 'frontend/dist'))

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
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='laiCai',
)
