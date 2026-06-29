# 在线升级发布说明

本项目使用 GitHub Releases 作为更新源。

程序内的“设置 -> 检查更新”会访问：

`https://api.github.com/repos/yydsmf/AI/releases/latest`

检查到新版本后，会自动选择当前电脑适用的安装包，下载到本地更新目录并打开安装包。

## 版本号

本地开发默认版本在：

`gpt_desktop/version.py`

发布正式版本时，推荐使用 Git 标签，例如：

`v1.0.5`

GitHub Actions 会在打包时把 `1.0.5` 写入程序版本和 Windows 安装器版本。

## 自动打包

工作流文件：

`.github/workflows/release.yml`

触发方式：

- 推送 `v*` 标签时自动构建并上传到 GitHub Release。
- 也可以在 GitHub 网页的 Actions 页面手动运行。

构建产物：

- Windows: `GPTLocalToolbox_Setup_v版本号_windows_x64.exe`
- macOS Intel: `GPTLocalToolbox_v版本号_macos_intel.dmg`
- macOS Apple Silicon: `GPTLocalToolbox_v版本号_macos_arm64.dmg`
- 未来如果做成更简洁的 Mac 发布方式，可以改成一个 `universal2.dmg` 包，更新器会优先识别它

## 安装包包含内容

Windows 和 macOS 发布包会把程序运行所需的 Python 运行环境、界面库和项目依赖一起打入安装包，普通用户不需要单独安装 Python、Node.js 或手动执行 `pip install`。

macOS 发布包当前面向 macOS 12 及以上系统。PySide6 6.10 及更新版本的 macOS wheel 要求 macOS 13 及以上，因此发布依赖会固定在 6.10 之前，避免 Intel 旧系统安装后无法启动。

Windows 安装器会在打包时下载微软官方 `VC_redist.x64.exe`，并在用户安装时检测 Microsoft Visual C++ 运行库。如果用户电脑缺少该运行库，安装器会自动静默安装。

当前程序没有使用 .NET Runtime、WebView2 Runtime 或 Node.js 作为运行依赖，因此不需要用户额外安装这些环境。

用户仍然需要在程序设置里填写自己的 AI 服务地址、API Key 和模型名称；这些属于账号配置，不会预置在安装包里。

程序会按当前系统自动匹配：

- Windows 优先选择 `windows/x64/setup/exe/msi`
- Mac M 芯片优先选择 `macos/arm64`
- Mac Intel 优先选择 `macos/intel/x64`
- 如果以后做成通用包，可命名为 `macos_universal2.dmg`，优先级会高于单独架构包

## 新版本发布流程

1. 把代码推送到 GitHub 仓库 `https://github.com/yydsmf/AI`。
2. 创建并推送版本标签，例如 `v1.0.5`。
3. 等待 GitHub Actions 构建完成。
4. 打开 GitHub Releases，确认三个安装包都已上传。
5. 旧版本用户打开程序，进入设置页点击“检查更新”。

## 重要说明

当前方案是免费、可控的安装包更新方式：程序检查新版本，下载安装包，然后打开安装包让用户安装。

建议后续启用发布签名：

- Windows：给安装器做代码签名，降低 SmartScreen 拦截概率
- macOS：给 `.app` 和 `.dmg` 做 Developer ID 签名，并做 notarization 公证

这两项现在都已预留为可选流程：没有证书或账号时，GitHub Actions 会自动跳过，但下载后的 macOS 包可能会被 Gatekeeper 拦截，正式公开发布建议配置签名和公证。

需要配置的 GitHub Secrets：

- `WINDOWS_SIGNING_PFX_BASE64`
- `WINDOWS_SIGNING_PFX_PASSWORD`
- `WINDOWS_SIGNTOOL_PATH`
- `WINDOWS_TIMESTAMP_URL`
- `MAC_CODESIGN_IDENTITY`
- `MAC_NOTARY_APPLE_ID`
- `MAC_NOTARY_TEAM_ID`
- `MAC_NOTARY_PASSWORD`
- `MAC_ENTITLEMENTS_PATH`
