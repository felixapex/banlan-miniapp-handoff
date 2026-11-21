# Mobile App Collector 1.0.0 交接

日期：2026-11-21

## 交付物

- `mobile-app-collector-source-1.0.0-20261121.zip`：完整干净源码、测试、证据契约和说明。
- `matbox_mobile_app_collector-1.0.0-py3-none-any.whl`：可安装 Python 包。
- `SHA256SUMS.txt`：两份交付物的 SHA256。

## 三个入口

```text
android-collector   Android App + Appium UiAutomator2
ios-collector       iOS App + Appium XCUITest/WebDriverAgent
miniapp-collector   微信小程序 + ADB + 专用安卓测试微信
```

三个入口共享 `collector_core`：证据模型、截图/UI树、按钮遍历、路径恢复、断点续采、逐控件覆盖报告和采集包完整性验收。

## 验证结果

- 原始源码：45/45 测试通过。
- ZIP 解压到全新目录：45/45 测试通过。
- wheel 安装到全新目录：四个 Python 包均从安装目录加载；三个命令入口均可启动并显示独立帮助。
- 源码文件：30 个，共 144,695 字节。
- ZIP 条目：37 个；禁止项扫描为 0。

禁止项包括 `node_modules`、缓存、`build`、`egg-info`、图片、截图、采集数据和品牌数据。

## 验证边界

- Android 公共采集核心来自已完成的真实隔离安卓运行，并在拆分后重新回归。
- iOS 已完成 XCUITest 会话、Bundle ID、Deep Link 和页面树协议测试，尚未在 macOS/iPhone 真机环境验收。
- 小程序入口使用已有 ADB/微信链接处理逻辑并强制专用测试账号确认；本次没有登录或操作微信，也没有进行新的真实小程序采集。
- 不得把协议测试描述为 iOS 真机通过，也不得把可见界面采集描述为取得 App/小程序私有源码或全部服务端数据。
