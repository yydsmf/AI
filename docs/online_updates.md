# 在线升级发布说明

## 发布第一优先级：保护更新通道

发布新版本时，第一优先级是保证用户能正常检查更新和下载安装包。发布、验证、排查期间不要频繁点击程序内“检查更新”，也不要反复请求 GitHub Release API 或重复下载同一个安装包；GitHub 对未认证 API、共享代理出口和短时间重复访问都有可能限流或降速。

推荐做法：

- 发布前用本地测试和单元测试确认逻辑，少用线上 GitHub 反复试。
- 推送标签后只做一次必要的 Release/安装包确认。
- Windows/macOS 各用一台测试机做一次端到端更新即可，不要连续多次点“检查更新”。
- 如果必须反复验证下载流程，优先用浏览器或手动下载已生成的安装包，避免让程序持续打 GitHub API。
- 如果遇到 GitHub API 限流或下载明显变慢，先等待一段时间再测，避免把限流窗口越打越长。

本项目使用 GitHub Releases 作为更新源。

程序内的“设置 -> 检查更新”会访问：

`https://api.github.com/repos/yydsmf/AI/releases/latest`

检查到新版本后，会自动选择当前电脑适用的安装包。

Windows 会启动独立更新器：主程序先保存状态并退出，更新器把安装包下载到系统默认“下载”目录，确认主程序退出后自动打开安装包。这样可以避免主程序还在后台残留时安装器无法覆盖旧文件。

macOS 会继续下载对应架构的 DMG，并打开安装包。

## 版本号

本地开发默认版本在：

`gpt_desktop/version.py`

发布正式版本时，推荐使用 Git 标签，例如：

`v1.0.12`

GitHub Actions 会在打包时把 `1.0.12` 写入程序版本和 Windows 安装器版本。

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

Windows 安装包会同时包含主程序 `GPTLocalToolbox.exe` 和独立更新器 `GPTToolboxUpdater.exe`。用户在程序内点击“退出并自动安装”时，主程序只负责启动更新器并退出；下载、等待退出、结束残留进程和打开安装包都由更新器完成。

macOS 发布包当前面向 macOS 12 及以上系统。PySide6 6.10 及更新版本的 macOS wheel 要求 macOS 13 及以上，因此发布依赖会固定在 6.10 之前，避免 Intel 旧系统安装后无法启动。

Windows 安装器会在打包时下载微软官方 `VC_redist.x64.exe`，并在用户安装时检测 Microsoft Visual C++ 运行库。如果用户电脑缺少该运行库，安装器会自动静默安装。

独立更新器本身也会随包携带 Python 运行所需的 VC++ DLL。这样用户在旧版本里点击在线更新时，即使本机还没安装 Microsoft Visual C++ 运行库，更新器也能先启动并打开新版安装包。

当前程序没有使用 .NET Runtime、WebView2 Runtime 或 Node.js 作为运行依赖，因此不需要用户额外安装这些环境。

用户仍然需要在程序设置里填写自己的 AI 服务地址、API Key 和模型名称；这些属于账号配置，不会预置在安装包里。

程序会按当前系统自动匹配：

- Windows 优先选择 `windows/x64/setup/exe/msi`
- Mac M 芯片优先选择 `macos/arm64`
- Mac Intel 优先选择 `macos/intel/x64`
- 如果以后做成通用包，可命名为 `macos_universal2.dmg`，优先级会高于单独架构包

## 新版本发布流程

1. 把代码推送到 GitHub 仓库 `https://github.com/yydsmf/AI`。
2. 创建并推送版本标签，例如 `v1.0.12`。
3. 等待 GitHub Actions 构建完成。
4. 打开 GitHub Releases，确认三个安装包都已上传。
5. 旧版本用户打开程序，进入设置页点击“检查更新”。

## 重要说明

当前方案是免费、可控的安装包更新方式：程序检查新版本，Windows 交给独立更新器下载安装包并打开安装向导，macOS 下载 DMG 后打开安装包。

正式公开发布必须启用发布签名：

- Windows：给安装器做代码签名，降低 SmartScreen 拦截概率
- macOS：给 `.app` 和 `.dmg` 做 Developer ID 签名，并做 notarization 公证，确保用户从浏览器下载后可以正常打开

Windows 签名仍然是可选增强；macOS 如果配置了 Apple 签名和公证凭据，会自动生成用户下载后可正常打开的公证包。缺少这些配置时，GitHub Actions 会生成内部测试用的 ad-hoc 签名包，适合团队内测试，但不是 Apple 公证包。

需要配置的 GitHub Secrets：

- `WINDOWS_SIGNING_PFX_BASE64`
- `WINDOWS_SIGNING_PFX_PASSWORD`
- `WINDOWS_SIGNTOOL_PATH`
- `WINDOWS_TIMESTAMP_URL`
- `MAC_CERTIFICATE_P12_BASE64`
- `MAC_CERTIFICATE_PASSWORD`
- `MAC_CODESIGN_IDENTITY`
- `MAC_NOTARY_APPLE_ID`
- `MAC_NOTARY_TEAM_ID`
- `MAC_NOTARY_PASSWORD`

macOS 证书需要使用 Apple Developer 账号创建 `Developer ID Application` 证书，导出为 `.p12` 后把文件内容做 Base64，写入 `MAC_CERTIFICATE_P12_BASE64`；导出密码写入 `MAC_CERTIFICATE_PASSWORD`。`MAC_CODESIGN_IDENTITY` 通常形如 `Developer ID Application: 公司或个人名称 (TEAMID)`。`MAC_NOTARY_PASSWORD` 建议使用 Apple ID 的 app-specific password。

macOS 打包流程会自动导入证书、签名 `.app`、签名 `.dmg`、提交 Apple notarization、公证完成后 stapler 固定票据，并用 `spctl` 验证 DMG 能通过 Gatekeeper 检查。

内部测试包会使用免费 ad-hoc 签名，不需要 Apple Developer Program。由于没有 Apple 公证，个别机器从浏览器下载后仍可能需要右键打开或移除隔离属性。
