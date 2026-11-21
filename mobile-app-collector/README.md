# Mobile App Collector

一套干净的移动端采集器源代码，提供三个明确、互不混淆的入口：

- `android-collector`：Android + ADB/Appium UiAutomator2
- `ios-collector`：iOS + Appium XCUITest/WebDriverAgent
- `miniapp-collector`：微信小程序 + ADB + 专用安卓测试微信

三个入口共用页面证据、按钮遍历、断点续采和验收逻辑，但设备连接、应用身份和链接打开方式完全分开。

## 代码结构

```text
mobile-app-collector/
├─ collector_core/       # 共用证据、遍历、断点、覆盖报告和完整性验收
├─ android_collector/    # Android 独立客户端与命令入口
├─ ios_collector/        # iOS 独立客户端与命令入口
├─ miniapp_collector/    # 微信小程序独立ADB客户端与命令入口
├─ contracts/            # 结构化证据契约
└─ tests/                # 不依赖品牌数据的测试
```

项目不包含任何小程序、App、商品、图片、账号、模拟器或采集结果。

## 采集输出

每次采集生成：

- `capture/*.png`：真实页面截图
- `capture/*.xml`：Appium 原生 UI 树
- `checkpoint-evidence.json`：从根页面开始保存的中间断点
- `evidence.json`：页面、元素、文字、坐标、交互和流程证据
- `interaction-coverage.json`：逐个控件的已验证、未验证或安全阻止状态

采集器不会把截图误称为目标 App 的原始源码，也不会承诺仅靠 UI 自动化取得服务器私有数据。

## Android 入口

前置条件：Appium、UiAutomator2、授权的安卓真机或模拟器。

```powershell
android-collector capture `
  --appium-url http://127.0.0.1:4723 `
  --appium-options-json '{"automationName":"UiAutomator2","udid":"emulator-5554","appPackage":"com.example","appActivity":".MainActivity","noReset":true}' `
  --app-id com.example `
  --app-name "Example Android" `
  --start-url "example://home" `
  --out E:\collector-output\android-example
```

Android 入口使用包名检查当前应用；跳转到其他 App 会记录为 `BLOCKED_EXTERNAL_APP` 并尝试恢复，不会继续操作外部 App。

## iOS 入口

前置条件：macOS、Xcode、Appium、XCUITest/WebDriverAgent，以及授权的 iPhone 或 iOS Simulator。

```powershell
ios-collector capture `
  --appium-url http://127.0.0.1:4723 `
  --appium-options-json '{"automationName":"XCUITest","udid":"DEVICE_UDID","bundleId":"com.example.ios","noReset":true}' `
  --app-id com.example.ios `
  --app-name "Example iOS" `
  --start-url "example://home" `
  --out /Users/name/collector-output/ios-example
```

iOS 入口通过 `mobile: activeAppInfo` 检查当前 Bundle ID；Deep Link 使用 iOS `bundleId` 参数，不复用 Android 的包名逻辑。

## 微信小程序入口

前置条件：ADB、已授权安卓测试设备、已安装微信，以及专用测试微信号。该入口不允许使用个人主微信号，不包含电脑微信/WMPF/Frida，也不占用宿主鼠标。

URL Scheme 或 URL Link：

```powershell
miniapp-collector capture `
  --adb E:\Android\platform-tools\adb.exe `
  --serial emulator-5554 `
  --link "weixin://dl/business/?t=令牌" `
  --dedicated-test-account `
  --out E:\collector-output\miniapp-example
```

`#小程序://名称/令牌` 是分享文字，需要在微信自己的“文件传输助手”内发送并打开，因此还必须显式加入：

```powershell
--allow-share-text-input
```

没有 `--dedicated-test-account` 时，程序会在创建 ADB 客户端之前停止。可以用 `--account-pause-file` 指定账号暂停标记；文件存在时同样拒绝采集。

小程序入口保存截图、UI 树、可见文字、发现的控件、点击路径和覆盖报告。仅靠界面自动化不能保证获得服务端未返回的数据、私有接口、完整原图或小程序源码，报告不会把这些内容标成已完成。

## 断点续采

```powershell
android-collector capture `
  ... `
  --resume-evidence E:\old-run\evidence.json `
  --out E:\new-run
```

只能续接相同平台、相同 App ID 的证据。已验证的终点动作可跳过，导航仍从最新 UI 树重新定位，不使用旧坐标。

## 验收采集包

安卓和苹果入口都提供同一个 `verify` 子命令：

```powershell
android-collector verify `
  --evidence E:\run\evidence.json `
  --coverage E:\run\interaction-coverage.json `
  --out E:\run\verification-report.json
```

验收内容包括证据图引用、截图 SHA256、UI 树、PNG/XML 配对、空文件和覆盖统计算术。完整性通过不代表所有按钮都已验证；按钮覆盖状态单独保留。

## 源码运行与测试

```powershell
python -m android_collector --help
python -m ios_collector --help
python -m miniapp_collector --help

$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m pytest -p no:cacheprovider -q
```

当前独立代码包回归测试：45 项。

## 验证边界

- Android 底层来自已完成的隔离模拟器真实运行，并在拆包后继续进行独立回归。
- iOS 的会话、XML、Bundle ID、Deep Link 和安全边界已有协议级自动测试。
- iOS 尚未在本机真实运行，因为真实验收必须在 macOS + Xcode + iOS 设备环境完成；不能把协议测试写成真机通过。
- 小程序入口沿用已验证过的 ADB/微信链接处理逻辑，但此干净三入口包尚未重新登录微信做真实采集；当前只完成离线协议和安全门槛测试，不能写成任意小程序实测通过。
