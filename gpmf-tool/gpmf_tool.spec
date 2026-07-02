# -*- mode: python ; coding: utf-8 -*-
# PyInstaller スペック (プラットフォームで出力形態を変える)。
#
#   macOS  : dist/GPMF-GoPro.app   … Finder でダブルクリック起動できる .app バンドル
#            (console=False。引数なし起動で GUI が開く)
#   Windows: dist/gpmf.exe          … 単体 exe (ダブルクリックで GUI、引数付きで CLI)
#   Linux  : dist/gpmf              … 単体バイナリ
#
#   ビルド:  pyinstaller gpmf_tool.spec
#
# .app 内の実行体は Contents/MacOS/gpmf。CLI で使う場合は
#   ./dist/GPMF-GoPro.app/Contents/MacOS/gpmf inject in.mp4 -o out.mp4 ...

import sys

IS_MAC = sys.platform == "darwin"
APP_NAME = "GPMF-GoPro"

a = Analysis(
    ['gpmf_app.py'],
    pathex=[],
    binaries=[],
    datas=[('gpmf_tool/README.md', 'gpmf_tool')],
    hiddenimports=['gpmf_tool.gui'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'numpy', 'pandas', 'scipy', 'matplotlib', 'PIL',
        'pytest', 'setuptools', 'pip',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

if IS_MAC:
    # --- macOS: ダブルクリック起動できる .app バンドル (onedir + BUNDLE) ---
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='gpmf',
        debug=False,
        strip=False,
        upx=False,
        console=False,          # Terminal を開かず GUI として起動
        argv_emulation=True,    # Finder からのドラッグ&ドロップを argv に
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name='gpmf',
    )
    app = BUNDLE(
        coll,
        name=f'{APP_NAME}.app',
        icon=None,
        bundle_identifier='com.gpmftool.gopro',
        info_plist={
            'CFBundleName': 'GPMF GoPro化',
            'CFBundleDisplayName': 'GPMF GoPro化',
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleVersion': '1.0.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',
            # 動画/GPX をアイコンにドロップして開けるようにする
            'CFBundleDocumentTypes': [{
                'CFBundleTypeName': 'Movie',
                'CFBundleTypeRole': 'Viewer',
                'LSItemContentTypes': ['public.movie', 'public.mpeg-4'],
            }],
        },
    )
else:
    # --- Windows / Linux: 単体実行ファイル (onefile) ---
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='gpmf',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,           # CLI 出力を表示
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
