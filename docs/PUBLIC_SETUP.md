# 安装与维护

要求：Windows x64、PowerShell、可用的 Node.js/npm。安装阶段需要访问 Python、npm、PyPI 和 GitHub 的公开源；正常运行不会调用安装下载脚本。

1. 克隆此仓库，放在本机固定磁盘、非共享且非云同步目录。
2. 运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Setup-Offline.ps1`。安装器下载并校验固定 Python 运行包，按固定 Git blob 获取上游源码，应用字节级变更与新增源码，安装锁定依赖并构建 UI。已有文件与声明的基线/目标都不相符时停止，不覆盖本地编辑。
3. 以管理员身份运行 `Enable-Offline-Firewall.cmd`，安装专用程序的入站/出站阻断规则。
4. 双击 `Start-Offline.cmd`。启动器检查规则和运行文件完整性，不满足就拒绝启动。

本仓库不包含上游完整源码、上游 Git 历史、运行时二进制或原生私有组件。`source-overlay/source-changes.json` 记录固定上游版本中被修改的范围和新增字节，不复制删除的原始源码；`source-overlay/files/` 为新增改造文件。`scripts/upstream-source-manifest.json` 固定公开源码路径及 Git blob 摘要。装配后的 `upstream_local/` 和公开源码缓存均不纳入本仓库。

维护改造后，运行 `scripts/build_source_distribution.py` 重新生成分发内容；该开发脚本需要装配目录保留原固定版本的 Git 对象。随后运行 `scripts/audit_publication.py`，核对显式发布清单，排除本机账号标识、实际密钥和已授权资料。不要在整个工作区执行不加检查的 `git add .`。

ChatGPT 连接可运行 `scripts/install_chatgpt_connection.py` 注册为 `wechat_local_context`，再用 `scripts/probe_context_mcp.py` 进行不读取资料的初始化/列工具握手。注册会修改客户端的 MCP 配置，操作前应保留自己的配置快照并核对差异；该脚本不登录、不复制令牌、不发起云端模型请求。授权与回答由用户在 AI 页和 ChatGPT/Codex 客户端操作。

验证范围：改造安全/业务测试与选定上游回归在开发机通过 148 项及 187 个子测试，相关前端通过 9 项；新仓库的源码重建与校验另行验证。它们不证明所有微信版本、所有媒体、用户模型推理和真实 ChatGPT 回答均已验收。首次完整联网依赖安装应在新环境另行验证，不应把已有开发环境构建成功当成全新安装完成。
