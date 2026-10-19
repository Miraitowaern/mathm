# macOS 桌面应用

原生 Swift / AppKit + WKWebView 外壳启动独立 Python 服务，使用随机本机端口。退出应用时结束其启动的服务。

## 构建要求

- macOS 13+；本项目已在 Apple 芯片机器本地验证。
- Xcode Command Line Tools（提供 `xcrun swiftc` 与签名工具）。
- 已安装 requirements.txt 依赖的 Python 3.12。
- 可搬移的 Python 发行版，布局包含 `bin/python3.12`、`lib/libpython3.12.dylib`、`lib/python3.12/`。Framework 布局和部分 Homebrew Python 不符合这个构建器的布局，不能直接套用。

先按 README 准备依赖和需要的技能，再运行：

```bash
python desktop/build.py
```

输出 `desktop/build/MathM.app`。运行时、解析与绘图依赖、许可元数据、项目页面和选定技能会复制进应用；用户数据和 .env 不会被打包。构建目录已存在时会停止，需先移走旧构建结果，避免混合旧资源。

构建器使用本地临时签名，并非 Apple 开发者公证；未承诺其他系统版本、Intel 架构或任意 Python 发行版下的可移植性。

## 数据与配置

数据、配置和运行日志位于当前用户的 `~/Library/Application Support/MathM/`。菜单提供打开数据目录、模型配置与日志的入口。

旧 `~/mathm/data` 存在且桌面数据为空时，会在首次启动迁移一次；之后网页与桌面数据各自保存，不双向同步。提供模板时仍需可信 LaTeX 环境进行最终编译。
