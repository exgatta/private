# -*- mode: python ; coding: utf-8 -*-
# PyInstaller スペック: 単体実行ファイル (GUI + CLI 兼用) を生成する。
#
#   ビルド:  pyinstaller gpmf_tool.spec
#   出力:    dist/gpmf   (Windows では dist/gpmf.exe / Mac では dist/gpmf.app)
#
# 引数なしで起動すると GUI、引数付きで起動すると CLI として動く
# (gpmf_app.py 参照)。

block_cipher = None

a = Analysis(
    ['gpmf_app.py'],
    pathex=[],
    binaries=[],
    datas=[('gpmf_tool/README.md', 'gpmf_tool')],
    hiddenimports=['gpmf_tool.gui'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 動画/GUI に不要な重量モジュールを除外して小さくする
        'numpy', 'pandas', 'scipy', 'matplotlib', 'PIL',
        'pytest', 'setuptools', 'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='gpmf',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # CLI 出力を出すため console=True。
    disable_windowed_traceback=False,
    argv_emulation=True,   # macOS で Finder からのドラッグ&ドロップを argv に
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 生成物は単一ファイル dist/gpmf (Windows: gpmf.exe)。
# 引数なしで起動すると GUI、引数付きなら CLI として動作する。
# macOS で Finder 用 .app が欲しい場合は onedir モードで別途 BUNDLE 化する
# (onefile と .app は併用不可のため、ここでは単一ファイルに統一)。
