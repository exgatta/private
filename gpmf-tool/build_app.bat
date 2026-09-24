@echo off
REM Windows 用ビルドスクリプト (dist\gpmf.exe を生成)。
REM PyInstaller はクロスコンパイル不可なので、Windows の .exe は Windows 上でビルドすること。
cd /d "%~dp0"

echo ==> PyInstaller とドラッグ&ドロップ用ライブラリを確認/インストール
python -m pip install --quiet --upgrade pyinstaller tkinterdnd2 pillow
if errorlevel 1 goto :error

echo ==> 旧ビルドを掃除
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo ==> ビルド
python -m PyInstaller --clean --noconfirm gpmf_tool.spec
if errorlevel 1 goto :error

echo.
echo ==> 完了。dist\gpmf.exe が生成されました。
echo 使い方:
echo   dist\gpmf.exe                                          （GUI 起動）
echo   dist\gpmf.exe inject in.mp4 -o out.mp4 --gpx ride.gpx --device hero11
goto :eof

:error
echo ビルドに失敗しました。
exit /b 1
