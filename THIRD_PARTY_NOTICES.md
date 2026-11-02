# 上游源码与运行时

v0.1.3 完整离线发布附件包含预先构建的桌面程序、必要后端源码、已生成前端、CPython 运行环境、锁定 Python 依赖以及本机从可审查源码构建的图片组件。与早期源码装配方式不同，用户安装时无需再下载这些组件。附件保留 Python LICENSE.txt、Electron LICENSE / LICENSES.chromium.html、依赖包内许可及本说明；不包含账号、聊天数据或私有上游二进制。第三方材料仍受各自权利与许可约束，本项目不对其重新授权。下文关于不提交上游完整源码和运行时的描述针对 Git 源码仓库，不代表离线发布附件不含运行时。

装配后的应用复用 LifeArchiveProject/WeChatDataAnalysis 固定提交 64664bef316897b0bca2d391be4a6d2c0c472062 的源码。此仓库只提交新增改造代码、变更范围和插入字节及固定版本元数据；安装时单独获取并校验上游源码，生成的 upstream_local/ 不纳入本仓库。

装配时保留上游作者、THIRD_PARTY_NOTICES、子组件许可证及源文件信息。未找到覆盖整个上游仓库的明确根许可证，不把源码公开视为任意分发授权，不重新授予第三方源码许可。本仓库公开的是改造分发内容，不包含上游完整源码、历史或运行时二进制。

没有下载或执行上游 wx_key wheels、VoipEngine/img_helper DLL、wechatdb broker/client、wce_integrity PYD/WASM。没有破解或修改其原生授权组件来继续使用；普通导出使用独立本地 SHA-256 清单，不冒称上游签名。

- Python 3.14.10 x64：官方完整运行包，归档 SHA-256 为 cc28026a650970cc1570bb127312f1f9634eb67abfe157ae6ca1acbbc627d091；Python Software Foundation 签名已核对。
- Electron 45.2.1：官方 npm 包指定发行物，下载对照包内 checksum；归档 SHA-256 为 7c342aee45d5b4ccafe5dfe9037028796b082735a576e21e2b4e2d8422ebb727。取得的 electron.exe 没有 Authenticode 签名，不声称它有签名或已经自行从源码重建。
- CPython 随附 Tcl/Tk、SQLite、Zstandard、OpenSSL、Microsoft 运行库；Electron/Chromium 与 Python/npm 依赖各自受其许可证约束，保留随附 notices。
- Python 依赖精确版本见 upstream_local/offline-requirements.lock，前端/桌面见各 package-lock.json。安装阶段使用过 PyPI/Electron 镜像，下载工具不在运行链路；未宣称完成全部第三方依赖源码审计。
- Windows CNG、DPAPI、文件/进程接口来自本机系统。
- 原图直连的 TLV/分片协议实现参考 thisnick/agent-wechat 的 wechat-protocol/src/media.rs，固定提交 bf0400a3b3cde46727e38952752642f718d7ea63，MIT 许可及版权声明保存在 desktop/src/LICENSE-local-cdn.txt。不使用其完整客户端、SILK 或现成二进制。下载组件由本机 Microsoft .NET 编译器从本仓库 C# 源码构建。

以后若分发，应先解决上游授权和实际依赖的许可证及通知义务；本文件不对上游组件再许可。
