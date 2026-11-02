# 安装与维护

普通用户：从项目 [v0.1.3 Release](https://github.com/haoyuebju2/wechat_data/releases/tag/v0.1.3) 下载完整离线 Setup EXE，核对 SHA-256 后执行。安装时不下载运行环境或依赖，也不执行源码构建，不需要预装 Git、Node 或 Python。标准向导提供安装位置、可选自启、组件进度、完成页及卸载入口；首次防火墙配置需要管理员确认。安装后直接使用 `WeChatDataMonitor.exe` 或快捷方式。程序文件与 `%APPDATA%\WeChatDataMonitor` 数据分开，卸载保留该数据目录。安装器未签名，使用新的空目录，不承诺旧聊天数据的自动迁移。[完整说明](RELEASE_0.1.3.md)。

下面的 Node.js、Git 命令和 CMD 启动步骤是直接从源码安装的方式。

要求：Windows x64、PowerShell、可用的 Node.js/npm。安装阶段需要访问 Python、npm、PyPI 和 GitHub 的公开源；正常运行不会调用安装下载脚本。

日常可点击右上角“原图记录”查看自动下载结果。入口上的“新获取”统计上次查看后首次获取成功的图片（原图或清晰图），打开后清零；历史继续保留，可加载更早记录或单独清空。清空不会删除缓存图片，也不会让已完成任务重新下载。旧版已完成任务单独标注为旧记录。

消息没有可下载原图时，程序会尝试获取清晰版本。WXGF 源数据通过消息 MD5 验证后，才允许取得同一资源的 JPEG 转换预览并进行本机图像比对。预览会显示像素尺寸和“非原图文件”，历史将原图和清晰图分开统计；“新获取”包含两类首次获取成功的图片，本地缓存命中不计入。

原图下载组件使用本机 Microsoft .NET Framework 4.x C# 编译器构建，启动时核对源码和生成物摘要，不下载现成组件。在“设置 → 聊天与媒体”打开“自动获取原图”，再将“收到图片后自动下载”设为“全部对话”或“指定私聊 / 群聊”；指定模式下先选微信账号，再勾选对话。设置自动保存，可搜索名称。关闭收到自动下载后，仍可点图获取。程序运行期间，微信新图落盘并通过快照校验后才会排队；不回溯历史，单张依次下载，失败最多尝试 3 次。查看器与后端断网规则保留；HTTP 请求元数据的传输限制见安全说明。

1. 克隆此仓库，放在本机固定磁盘、非共享且非云同步目录。
2. 运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup-Offline.ps1`。安装器下载并校验固定 Python 运行包，按固定 Git blob 获取上游源码，应用字节级变更与新增源码，安装锁定依赖并构建 UI。已有文件与声明的基线/目标都不相符时停止，不覆盖本地编辑。
3. 以管理员身份运行 `Enable-Offline-Firewall.cmd`，安装专用程序的入站/出站阻断规则。
4. 双击 `Start-Offline.cmd`。启动器检查规则和运行文件完整性，不满足就拒绝启动。

本仓库不包含上游完整源码、上游 Git 历史、运行时二进制或原生私有组件。`source-overlay/source-changes.json` 记录固定上游版本中被修改的范围和新增字节，不复制删除的原始源码；`source-overlay/files/` 为新增改造文件。`scripts/upstream-source-manifest.json` 固定公开源码路径及 Git blob 摘要。装配后的 `upstream_local/` 和公开源码缓存均不纳入本仓库。

维护改造后，运行 `scripts/build_source_distribution.py` 重新生成分发内容；该开发脚本需要装配目录保留原固定版本的 Git 对象。随后运行 `scripts/audit_publication.py`，核对显式发布清单，排除本机账号标识、实际密钥和已授权资料。不要在整个工作区执行不加检查的 `git add .`。

完整离线版的构建分三步：用 `scripts/build_offline_app.py --output <新应用目录> --prepared <干净的已安装源码环境>` 打包应用，再用 `scripts/build_inno_installer.py --payload <新应用目录>/application --compiler <ISCC.exe 路径> --output <新安装器目录>` 生成标准安装向导。审核并提交源码后，运行 `scripts/build_release.py --installer <该版本完整离线 Setup.exe> --output <新发布目录>` 生成审核源码包、说明、摘要和提交记录。构建机需要已准备好的固定依赖、Electron 和 Inno Setup；安装者无需这些工具。旧版 `ReleaseInstaller.cs` 仅为 v0.1.0 历史安装器源码，不用于当前完整离线版本。

ChatGPT 连接可运行 `scripts/install_chatgpt_connection.py` 注册为 `wechat_local_context`，再用 `scripts/probe_context_mcp.py` 进行不读取资料的初始化/列工具握手。注册会修改客户端的 MCP 配置，操作前应保留自己的配置快照并核对差异；该脚本不登录、不复制令牌、不发起云端模型请求。授权与回答由用户在 AI 页和 ChatGPT/Codex 客户端操作。

验证范围：改造安全/业务测试与选定上游回归在开发机通过 148 项及 187 个子测试，相关前端通过 9 项；新仓库的源码重建与校验另行验证。它们不证明所有微信版本、所有媒体、用户模型推理和真实 ChatGPT 回答均已验收。首次完整联网依赖安装应在新环境另行验证，不应把已有开发环境构建成功当成全新安装完成。
