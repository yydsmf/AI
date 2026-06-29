# 在线升级发布说明

本项目使用 GitHub Releases 作为更新源。

程序内的“设置 -> 检查更新”会访问：

`https://api.github.com/repos/yydsmf/AI/releases/latest`

检查到新版本后，会自动选择当前电脑适用的安装包，下载到本地更新目录并打开安装包。

## 版本号

本地开发默认版本在：

`gpt_desktop/version.py`

发布正式版本时，推荐使用 Git 标签，例如：

`v1.0.1`

GitHub Actions 会在打包时把 `1.0.1` 写入程序版本和 Windows 安装器版本。

## 自动打包

工作流文件：

`.github/workflows/release.yml`

触发方式：

- 推送 `v*` 标签时自动构建并上传到 GitHub Release。
- 也可以在 GitHub 网页的 Actions 页面手动运行。

构建产物：

- Windows: `GPTLocalToolbox_Setup_v版本号_windows_x64.exe`
- macOS Intel: `GPTLocalToolbox_v版本号_macos_intel.app.zip`
- macOS Apple Silicon: `GPTLocalToolbox_v版本号_macos_arm64.app.zip`

程序会按当前系统自动匹配：

- Windows 优先选择 `windows/x64/setup/exe/msi`
- Mac M 芯片优先选择 `macos/arm64`
- Mac Intel 优先选择 `macos/intel/x64`
- 如果以后做成通用包，可命名为 `macos_universal2`

## 新版本发布流程

1. 把代码推送到 GitHub 仓库 `https://github.com/yydsmf/AI`。
2. 创建并推送版本标签，例如 `v1.0.1`。
3. 等待 GitHub Actions 构建完成。
4. 打开 GitHub Releases，确认三个安装包都已上传。
5. 旧版本用户打开程序，进入设置页点击“检查更新”。

## 重要说明

当前方案是免费、可控的安装包更新方式：程序检查新版本，下载安装包，然后打开安装包让用户安装。

macOS 如果要做到更丝滑的后台自动更新，需要接入 Sparkle，并且最好做 Apple 开发者签名和公证。当前免费方案不强制签名，但用户第一次打开时可能会看到 macOS 安全提示。
