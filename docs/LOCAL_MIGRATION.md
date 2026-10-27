# 云悦云离线迁移

Git 保存定制源码和脱敏记录；私有迁移包保存凭据、数据库、上传文件和当前运行镜像。两者需要一起带走。
迁移包含真实密钥、用户数据及数据库角色密码哈希，只能通过受控介质传输，不得提交 Git 或上传公共网盘。

## 已包含的工具

使用 Python 3.12+、Docker Engine、Compose v2。无需安装 Python 第三方依赖。

```powershell
# 在源仓库完成提交后，导出到仓库之外的新目录。
python scripts/migration/migrate.py export --package C:/private/weknora-transfer

# 验证全部文件 SHA-256、压缩包内容及 Git bundle。
python scripts/migration/migrate.py verify --package C:/private/weknora-transfer

# 在隔离容器/临时卷中实际恢复 PostgreSQL、逐表核对行数，并检查 Redis 可加载。
python scripts/migration/migrate.py rehearsal --package C:/private/weknora-transfer
```

导出时只短暂暂停 `WeKnora-frontend/app/docreader/redis`，PostgreSQL 保持运行并生成事务一致的逻辑备份；
上传文件与 Redis 在同一暂停窗口归档。完成或失败后按相反顺序恢复容器。镜像导出在恢复服务后执行。
执行前暂停人工操作和外部写入；若有进程绕过 WeKnora 直接写数据库或文件卷，需要先自行停止该进程。
导出失败不会删除源数据；不完整的输出目录不要用于恢复。

## 包内材料

| 文件 | 用途 |
| --- | --- |
| `source.bundle` | 本地提交及所需 Git 历史，可离线 clone，无需 push |
| `config/.env` | 原部署的环境变量和密钥；保留 JWT/加密相关配置才能正确读取原数据 |
| `config/config.yaml`、`config/builtin_models.yaml` | 当前模型与应用配置 |
| `database.dump` | 新鲜 PostgreSQL custom-format 备份，包含数据库数据、扩展和向量索引定义 |
| `database-globals.private.sql` | 数据库角色/权限的独立留档；含密码哈希，不自动执行 |
| `data-files.tar.gz` | 上传原文件和解析图片 |
| `docreader-tmp.tar.gz` | 文档解析临时卷；一并保留以免遗漏进行中的临时产物 |
| `migration-redis-data.tar.gz` | Redis RDB/AOF，包含队列和其他运行状态 |
| `skills-preloaded.tar.gz` | 实际挂载的预置/自定义技能 |
| `images.tar` | 当前运行的 app、frontend、docreader、PostgreSQL、Redis 镜像，固定为 `linux/amd64` |
| `runtime.private.json` | 容器原始运行配置，仅供私有核对 |
| `compose.migration.private.json` | 固定镜像、原运行环境及 Redis 持久卷的私有 Compose 覆盖配置 |
| `manifest.private.json`、`MANIFEST.sha256` | 文件大小、SHA-256、镜像 ID、源提交、逐表行数和归档统计 |
| `restore-check.private.json` | 本次隔离恢复演练结果；成功演练后生成 |
| `PREPARATION.md` | 本轮检查结果、实际文件位置和迁移限制 |

旧的 `backups/WeKnora-db-0.6.3-20260806-224059.sql` 不是当前数据备份，不用于本次恢复。

## 新环境恢复

1. 安装 Git、Python 3.12+、Docker/Compose v2，将完整私有迁移目录通过受控介质复制过去。
2. 确保为 Linux x86-64 容器环境，磁盘容纳解包后的镜像、数据库索引及全部文件。ARM 主机需要单独适配。
3. 在一个全新的目录离线检出源码；本次 bundle 的分支为 `main`：

   ```powershell
   git clone --branch main C:/private/weknora-transfer/source.bundle C:/work/weknora
   cd C:/work/weknora
   python scripts/migration/migrate.py verify --package C:/private/weknora-transfer
   python scripts/migration/migrate.py restore --package C:/private/weknora-transfer --project weknora
   ```

   Linux 下替换成实际绝对路径；相同 Python 命令可运行。

4. 恢复脚本要求 `.env`、五个 `WeKnora-*` 容器和目标数据卷都不存在；发现现有环境即拒绝覆盖。
   它加载保存镜像、恢复配置/技能/文件卷，启动空 PostgreSQL 后导入备份并逐表核对；核对成功才启动应用。
   自动迁移暂设为 `false`，使用源机同版本镜像，避免意外升级数据库。应用迁移用户复用源数据库用户；
   `database-globals.private.sql` 仅作留档，存在额外外部数据库角色时应单独评估导入。

5. 后续所有启动/停止/排查必须继续使用恢复产生的私有覆盖配置：

   ```powershell
   docker compose -p weknora -f docker-compose.yml -f C:/private/weknora-transfer/compose.restore-weknora.private.json ps
   docker compose -p weknora -f docker-compose.yml -f C:/private/weknora-transfer/compose.restore-weknora.private.json up -d --no-build --pull never
   ```

   恢复工具会生成被 Git 忽略的 `.weknora-migration.json`，Windows 启停脚本自动读取该标记、沿用私有覆盖配置；
   不要删除标记或迁移包中的覆盖配置，避免换回上游 `latest`。
   当前默认访问 `http://localhost:8081`。更换端口、域名或外部服务地址前，核对 `.env` 和私有覆盖文件，后者优先。

## 恢复后验收与切换

- 确认 PostgreSQL、app、docreader 健康，登录已有账号，核对空间、知识库、文件数。
- 实际预览/下载旧文档和解析图片，执行一次检索和模型问答。
- 核对模型服务、代理、邮件、OIDC、公共域名和 Dify 联动地址。`host.docker.internal` 在 Linux 上需要单独配置宿主机映射或改为目标服务地址。
- 本包恢复 Redis 队列；恢复前审阅源机是否有进行中的任务，避免新旧环境同时对同一外部业务执行任务。
- 源机在导出后继续接受的写入不在该快照中；最终切换前应停止写入并重新导出新包。不要把本次准备快照当成未来切换时的最新状态。
- 确认目标环境验收通过前保留源环境和本包。工具不执行 `docker compose down -v`，不删除旧数据卷。

当前远程仍指向腾讯原仓库，迁移工具不会修改远程或执行 push。以后需要在线推送时，先设置我们的独立远程。
