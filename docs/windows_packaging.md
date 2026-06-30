# Windows 打包说明

这套 Windows 包使用 `factory_main.py` 作为入口，功能仍然是完整程序，但不会把当前电脑里的历史记录、小说项目、图片/视频缓存或 API 配置打进发布包。

## 在 Windows 上打包

1. 建议安装 Windows x64 版 Python 3.11 或 3.12，安装时勾选 “Add python.exe to PATH” 和 Python Launcher。未安装也可以直接运行脚本，脚本会优先从国内镜像自动下载安装 Python 3.11.9。
2. 把整个项目文件夹复制到 Windows 电脑，建议放在短路径，例如：

```text
C:\GPTLocalToolbox
```

3. 双击项目根目录里的 `build_windows_exe.bat`。
4. 脚本会把虚拟环境、pip 缓存、PyInstaller 临时目录放到短路径：

```text
%LOCALAPPDATA%\GPTLocalToolboxBuild
```

这样可以避开 PySide6 在 Windows 上经常遇到的路径过长问题。

5. 打包完成后，程序会直接出现在当前目录：

```text
GPTLocalToolbox.exe
```

脚本成功后会自动打开当前文件夹并选中 `GPTLocalToolbox.exe`。

## 生成安装包

如果这台 Windows 电脑安装了 Inno Setup 6，脚本会在生成 `.exe` 后自动继续生成安装包：

```text
GPTLocalToolbox_Setup.exe
```

以后给别人用时，直接发 `GPTLocalToolbox_Setup.exe` 就行。对方不需要安装 Python，也不需要手动安装 Python 依赖。

安装包会安装主程序，并创建：

- 开始菜单快捷方式
- 桌面快捷方式

如果没有安装 Inno Setup，脚本会跳过安装包步骤，但当前目录里的 `GPTLocalToolbox.exe` 仍然可以直接运行和分发。

## 依赖下载太慢

Windows 首次打包最慢的通常是下载 PySide6/Qt，单个包可能超过 100MB。构建脚本默认使用清华 PyPI 镜像：

```text
https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
```

如果当前镜像很慢，可以在运行脚本前切换镜像：

```bat
set PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
build_windows_exe.bat
```

或：

```bat
set PIP_INDEX_URL=https://pypi.org/simple
build_windows_exe.bat
```

更推荐先把所有依赖下载到本地 `wheelhouse`，以后反复打包会快很多：

```bat
prepare_windows_wheels.bat
build_windows_exe.bat
```

如果 `wheelhouse` 已经下载完整，也可以强制离线安装，避免 pip 再访问网络：

```bat
set USE_LOCAL_WHEELS_ONLY=1
build_windows_exe.bat
```

`wheelhouse` 可以从网络更快的 Windows 电脑下载好后复制过来。只要 Python 版本和系统架构一致，例如 Windows x64 + Python 3.11，就能复用。

## 找不到 Python

如果窗口里出现：

```text
Could not find Python
```

新版脚本会自动从清华镜像下载安装 Windows x64 Python 3.11.9：

```text
https://mirrors.tuna.tsinghua.edu.cn/python/3.11.9/python-3.11.9-amd64.exe
```

然后继续使用清华 PyPI 源安装依赖：

```text
https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
```

如果自动安装仍失败，再在 Windows 的 CMD 里检查：

```bat
py -3.11 --version
python --version
where python
```

如果都找不到，可以手动安装 Windows x64 版 Python 3.11 或 3.12，并在安装界面勾选 “Add python.exe to PATH” 和 Python Launcher。

如果已经安装 Python，但没有加入 PATH，可以手动指定地址后再运行脚本，例如：

```bat
set PYTHON_EXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe
prepare_windows_wheels.bat
build_windows_exe.bat
```

常见安装地址：

```text
C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe
C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe
C:\Program Files\Python311\python.exe
C:\Program Files\Python312\python.exe
```

## 运行库和系统依赖

当前程序是 PySide6/Qt 桌面程序，PyInstaller 会把 Python、PySide6、Qt、requests、python-docx、pypdf、edge-tts、Pillow 等 Python 依赖打进 `GPTLocalToolbox.exe`。

在线更新用的 `GPTToolboxUpdater.exe` 也会单独打包，并显式携带 Python 启动所需的 VC++ 运行库 DLL。这样它被复制到系统临时目录后，仍能在缺少 VC++ 运行库的 Windows 机器上启动。

当前代码没有发现必须单独安装的 Node.js、.NET Runtime 或 WebView2 Runtime 依赖。

少数 Windows 电脑可能缺少 Microsoft Visual C++ Redistributable。安装脚本已经预留了检测和自动安装逻辑：

1. 从 Microsoft 官方渠道下载 x64 版 `VC_redist.x64.exe`。
2. 在项目里创建这个目录：

```text
installer\redist
```

3. 把下载的文件放到：

```text
installer\redist\VC_redist.x64.exe
```

4. 重新运行 `build_windows_exe.bat`。

如果安装包里带了这个文件，安装时会检查注册表：

```text
HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64
Installed = 1
```

如果没有检测到 VC++ 运行库，就会静默执行：

```text
VC_redist.x64.exe /install /quiet /norestart
```

如果没有放入 `VC_redist.x64.exe`，安装包仍然可以正常编译，只是不会自动安装 VC++ 运行库。

## 发布签名

如果你准备公开分发，建议再给 Windows 安装器加代码签名。这样用户下载时更不容易被 SmartScreen 提示拦住。

当前仓库已经预留了签名入口，后续只要在 GitHub Secrets 里配置：

- `WINDOWS_SIGNING_PFX_BASE64`
- `WINDOWS_SIGNING_PFX_PASSWORD`
- `WINDOWS_SIGNTOOL_PATH`（可选）
- `WINDOWS_TIMESTAMP_URL`（可选）

就会自动签名；没配置则跳过。

如果你本地手工测试，也可以把 `.pfx` 转成 Base64 再放进环境变量里。

## 截图里的 PySide6 安装报错

截图中失败位置是安装 `PySide6_Essentials`，错误类似：

```text
OSError: [Errno 2] No such file or directory:
...\PySide6\qml\Qt\labs\assetdownloader\...
WARNING: The scripts ... installed in ... which is not on PATH
WARNING: This error might have occurred since this system does not have Windows Long Path support enabled.
```

根因通常不是 PySide6 文件缺失，而是 Windows 默认路径长度限制。之前脚本把虚拟环境建在项目目录下，如果项目目录本身很长，安装 PySide6 的 QML 文件时就会超过路径限制。

现在脚本已经改成短路径构建。如果仍然遇到同类错误，按这个顺序处理：

1. 把项目移动到短目录，例如 `C:\GPTLocalToolbox`。
2. 关闭命令行窗口，重新双击 `build_windows_exe.bat`。
3. 如果还失败，用管理员身份打开 CMD 或 PowerShell，执行：

```bat
reg add HKLM\SYSTEM\CurrentControlSet\Control\FileSystem /v LongPathsEnabled /t REG_DWORD /d 1 /f
```

4. 重启 Windows，再重新运行打包脚本。

## 出厂空数据

发布包不会携带本机数据。首次运行时：

- API 厂商配置为空
- 模型选择为空
- 历史记录为空
- 小说项目为空
- 草稿为空

Windows 出厂版的数据会保存在当前 Windows 用户的：

```text
%LOCALAPPDATA%\GPTLocalToolboxFactory
```

这个目录只会在用户运行后逐步产生数据；打包时不会包含它。

## 注意

PyInstaller 不能在 macOS 上直接生成 Windows `.exe`。本项目当前所在的 Mac 可以准备打包脚本和配置，但最终 `.exe` 需要在 Windows 电脑或 Windows 构建环境里生成。
