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

# ドラッグ&ドロップ用 tkinterdnd2 を (インストールされていれば) 同梱する
# 結合選択画面 (Web UI) の静的ファイルはパッケージと同じ相対位置に置く
# (server.py が os.path.dirname(__file__)/static で見つける)
_datas = [
    ('gpmf_tool/README.md', 'gpmf_tool'),
    ('gpmf_tool/webui/static', 'gpmf_tool/webui/static'),
]
_binaries = []
_hidden = ['gpmf_tool.gui', 'gpmf_tool.webui', 'gpmf_tool.webui.server']
try:
    from PyInstaller.utils.hooks import collect_all
    _d, _b, _h = collect_all('tkinterdnd2')
    _datas += _d
    _binaries += _b
    _hidden += _h
except Exception:
    pass  # 無ければ D&D なしでビルド (アプリ側でフォールバック)

a = Analysis(
    ['gpmf_app.py'],
    pathex=[],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # PIL(Pillow) はサムネイル表示に使うので除外しない
        'numpy', 'pandas', 'scipy', 'matplotlib',
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
