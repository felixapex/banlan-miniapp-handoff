# 微信小程序执行、识别与导入工具 v2

这是独立的小程序工具交接入口，不包含班兰业务数据，也不包含网站导入器的业务项目。

## 下载

### 我们编写的完整源码

- [miniapp-tool-clean-source-v2-2026-11-21.zip](./miniapp-tool-clean-source-v2-2026-11-21.zip)
- 大小：680,497 字节
- SHA256：`c8362d77679b060fa77f9cd6d4ace573059b29771c63a21797a706299ee4bd5c`

源码包括：

- 微信小程序执行与采集器
- 页面、按钮、文字、截图、接口响应和图片证据采集
- 数据补采、逐项对账和未完成拦截
- 小程序数据导入器
- 编辑器数据契约 `editor-data-contract.mjs`
- 自动化测试和自包含测试夹具

### 第三方离线依赖

第三方依赖没有混入我们自己的源码。需要完全离线运行时，再下载下面四个分卷：

- [依赖分卷 .001](../tool-source-2026-11-21/miniapp-execution-offline-deps-2026-11-21.zip.001)
- [依赖分卷 .002](../tool-source-2026-11-21/miniapp-execution-offline-deps-2026-11-21.zip.002)
- [依赖分卷 .003](../tool-source-2026-11-21/miniapp-execution-offline-deps-2026-11-21.zip.003)
- [依赖分卷 .004](../tool-source-2026-11-21/miniapp-execution-offline-deps-2026-11-21.zip.004)
- [合并脚本](../tool-source-2026-11-21/merge-offline-deps.ps1)
- 合并后 SHA256：`86f33bc99b18207729c93bdd8f505e90991eea577f1c9e40ea0bea92f9f0a963`

电脑可以联网时，也可以不下载离线依赖，直接按照源码包 README 使用 `npm ci` 安装锁定版本。

## 代码结构

- `capture/core/`：品牌无关核心。
- `capture/platforms/`：Android 与 Windows 平台适配。
- `capture/adapters/banlan/`：班兰仅作为参考适配，与核心分开。
- `capture/verification/`：补采、对账和完整性验收。
- `platforms/wmpf/`：微信小程序 WMPF 桥接与 CDP 采集。
- `wechat-miniapp-importer/`：小程序采集结果导入器。
- `import-foundation/`：编辑器共用数据契约。

## 已完成验证

- 在新的空目录中解压复验。
- 167 个源码文件 SHA256 全部一致。
- Python 132/132。
- 采集器 Node 26/26。
- 导入器 Node 16/16。
- 总计 174/174。
- `npm ls --all` 依赖树验证通过。

工具对已发现的页面和按钮建立证据台账；存在任何未核实项时会保留为失败或未完成。真实第三方小程序运行必须使用取得授权的独立测试环境，不能使用个人微信进行批量自动点击。
