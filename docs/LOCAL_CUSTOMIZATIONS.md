# 云悦云本地定制清单

原版基线：`ac9656af1db02a13075c4acffcb15faeda35b92d`；仓库 `VERSION` 为 `0.7.1`。
本清单描述相对该检出基线的定制，不代表已经同步到最新腾讯上游。

| 范围 | 保留的定制 | 主要位置 |
| --- | --- | --- |
| 品牌 | 云悦云名称、Logo、登录/首页文案、官方外链调整 | `frontend/index.html`、`frontend/src/assets/img/weknora.png`、`Login.vue`、`UserMenu.vue`、中文语言包 |
| 语言 | 界面选择器仅开放中文；保留其他语言包 | `frontend/src/i18n/index.ts`、`GeneralSettings.vue` |
| 会话 | 共享一次刷新、空间失效后重新选择/创建空间、清理旧状态、丢弃旧空间响应、不跨空间重放写请求 | `frontend/src/utils/sessionRecovery.ts`、`request.ts`、auth store/router/onboarding、`TenantInfo.vue` |
| 默认空间 | 登录/刷新时校验默认空间和成员关系；已失效则修复，无剩余空间时保留无空间身份 | `internal/application/service/user.go` |
| 上传 | 删除文档日期筛选及请求状态；可编辑空知识库显示“点击上传”，复用原文件选择和确认流程 | `KnowledgeBase.vue`、`empty-knowledge.vue`、`KbUploadSourceDropdown.vue` |
| 文档图片 | 对 DocReader 明确提供的图片路径增加精确匹配，兼容不配对的中英文括号文件名 | `internal/infrastructure/docparser/image_resolver.go` |
| 视觉模型 | GPT-5/推理模型使用 `max_completion_tokens`，移除不支持的采样参数 | `internal/models/vlm/remote_api.go` |
| 模型配置 | 启用内置 embedding/rerank 模型声明，密钥通过环境变量注入 | `config/builtin_models.yaml`、`docker-compose.yml` |
| 本地操作 | Windows 启停脚本、会话/多账号验证材料、知识上传记录、项目共享演示及截图 | 根目录两个 PowerShell 脚本、`tests/`、`artifacts/` |

多账号、空间、共享和权限体系的主体沿用原版；本次没有另建权限体系。

## 迁移整理补充

- 敏感 SQL 备份从索引排除并保留本机原文件；`backups/` 和私有迁移目录加入 Git/Docker 忽略规则，`.env.*` 备份不进入构建上下文。
- 补齐韩文/俄文 `workspaceOnboarding.description/help`，解决既有语言键审计的两项失败；中文界面策略保持原样。
- Windows 启停脚本使用脚本所在目录和 `PATH` 中的 Docker CLI，避免迁移后仍指向 `D:\weknora`。
- 增加离线配置/数据/镜像导出、完整性检查、隔离恢复演练和新环境恢复工具，见 [迁移说明](LOCAL_MIGRATION.md)。

## 证据边界

- `artifacts/multi-account/report.md` 与 `artifacts/session-recovery/report.md` 是 2026-09 的历史验收，不作为本次重新执行全部业务场景的证明。
- 本轮应执行会话恢复、文件夹及语言键测试、前端类型/构建检查和相关 Go 测试；实际结果记录在迁移包的 `PREPARATION.md`。
- 迁移镜像保存当前运行环境；本轮对启停脚本、忽略规则和非启用语言包的补齐未部署回当前容器。
- 新机器恢复后仍需验证登录、空间切换、文档预览/下载、检索及模型问答。源机可正常运行不等于目标环境已经验收。
