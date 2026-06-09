@echo off
chcp 65001 >nul
echo 安装小红书 MCP 依赖...
pip install mcp playwright
playwright install chromium
echo.
echo ✓ 依赖安装完成
echo.
echo 接下来去配置 Claude Desktop，按任意键查看步骤
pause >nul
echo.
echo 1. 用记事本打开这个文件：
echo    %APPDATA%\Claude\claude_desktop_config.json
echo    （如果文件不存在就新建一个）
echo.
echo 2. 把下面这段复制进去（把 YOUR_PATH 替换成 server.py 的实际路径）：
echo.
echo {
echo   "mcpServers": {
echo     "小红书": {
echo       "command": "python",
echo       "args": ["YOUR_PATH\\server.py"]
echo     }
echo   }
echo }
echo.
echo 3. 保存，重启 Claude Desktop，就好了。
echo.
pause
