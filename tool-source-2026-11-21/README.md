# 微信小程序执行与导入工具交接

## 推荐下载

- `miniapp-execution-importer-clean-source-v2-2026-11-21.zip`
  - 大小：680,497 字节
  - SHA256：`c8362d77679b060fa77f9cd6d4ace573059b29771c63a21797a706299ee4bd5c`
  - 状态：当前推荐版本；已完成内部架构清理和空目录复验。
- `miniapp-execution-offline-deps-2026-11-21.zip.001` 至 `.004`
  - 合并后大小：65,230,452 字节
  - 合并后 SHA256：`86f33bc99b18207729c93bdd8f505e90991eea577f1c9e40ea0bea92f9f0a963`

旧的 `miniapp-execution-importer-clean-source-2026-11-21.zip` 仅保留作历史版本，不再推荐交接。

## v2 代码结构

- `packages/wechat-miniapp-capture/capture/core/`：品牌无关核心。
- `packages/wechat-miniapp-capture/capture/platforms/`：Android 与 Windows 平台适配。
- `packages/wechat-miniapp-capture/capture/adapters/banlan/`：班兰参考适配。
- `packages/wechat-miniapp-capture/capture/verification/`：补采、对账与完整性验收。
- `packages/wechat-miniapp-capture/platforms/wmpf/`：WMPF 桥接与 CDP 运行时。
- `packages/wechat-miniapp-importer/`：小程序采集结果导入器。
- `packages/import-foundation/`：共用编辑数据契约，含 `editor-data-contract.mjs`。

稳定命令入口仍保留在 `packages/wechat-miniapp-capture/` 根目录；内部不存在旧扁平实现的双份兼容副本。

## 验证结果

- 解压到全新目录后，167 个源码文件 SHA256 全部一致。
- 采集器 Python：132/132。
- 采集器 Node：26/26。
- 导入器 Node：16/16。
- 合计：174/174。
- 离线依赖与 `package-lock.json`：`npm ls --all` 通过。
- 未包含 `node_modules`、缓存、实验目录、个人路径、登录状态、Cookie、Token、后端代码或品牌批量业务数据。

## 使用

1. 下载并解压 v2 源码包。
2. 下载 `.001` 至 `.004` 四个离线依赖分卷，使用 `merge-offline-deps.ps1` 合并并校验。
3. 把依赖包中的 `node_modules` 放入 `packages/wechat-miniapp-capture/`。
4. 在源码包根目录运行 `pwsh -File verify-source.ps1`。

采集器会对已发现的页面和按钮保存证据，并在存在未核实项时保持未完成。它不能凭空取得未显现、无权限、未请求或服务端未返回的数据；真实第三方小程序运行必须使用取得授权的独立测试环境，不能使用个人微信做批量自动点击。

