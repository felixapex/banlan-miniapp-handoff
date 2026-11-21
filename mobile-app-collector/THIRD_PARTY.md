# Third-party boundary

This source package contains no copied Appium, UiAutomator2, XCUITest, emulator,
application, or brand source code.

Runtime integration points are external:

- Appium server
- Android UiAutomator2 driver and an authorized Android device/emulator
- iOS XCUITest driver, WebDriverAgent, Xcode, and an authorized iPhone/iOS Simulator
- Android Debug Bridge, an authorized Android test device, and a dedicated WeChat test account for the mini-program entry

The Python collector itself uses only the Python standard library at runtime. WeChat,
mini-program packages, account data, WMPF/Frida bridges, and brand adapters are not bundled.
