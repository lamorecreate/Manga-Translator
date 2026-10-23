# 安装教程

> 适用：Windows 10 / 11 64 位。首次安装约需 3 GB 下载、8 GB 磁盘空间。

## 方式 A：下载 Release 便携包（推荐）

1. 打开 GitHub 仓库的 **Releases** 页面。
2. 下载 `MangaTranslator-1.0.0-win-x64.zip`。
3. 解压到一个**普通文件夹**，例如 `D:\MangaTranslator`。
   - 不要只把 exe 拖出来；`native\`、`scripts\` 必须和 exe 在一起。
4. 双击 **`scripts\setup.bat`**。
   - 它会创建 `.venv`、安装 Python 依赖、下载 llama.cpp / Qwen3-4B / manga-ocr / RapidOCR。
   - 首次约 3 GB，视网络需要 5–30 分钟。
   - 如果 SmartScreen 拦截，点“更多信息 → 仍要运行”。
5. 双击根目录 **`MangaTranslator.exe`**。
   - 会打开程序自己的原生窗口，不是浏览器。
   - 首次启动加载模型约 10–20 秒。
6. 把 PDF 或一组图片拖进窗口即可。

> `setup.bat` 只负责准备依赖和模型；它不是程序本体。程序本体是 `MangaTranslator.exe` + `native\`。

## 方式 B：从源码运行

需要 Python 3.11–3.14（64 位）。

```powershell
git clone https://github.com/<your-name>/manga-translator.git
cd manga-translator
.\scripts\setup.bat
.\MangaTranslator.exe
```

如果你修改了 `desktop/` 里的原生窗口源码，再运行：

```powershell
.\scripts\build-native.ps1   # 需要 .NET 10 SDK
```

## 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10 / 11 64 位 |
| Python | 3.11–3.14，64 位 |
| WebView2 | Windows 11 自带；Windows 10 如缺失请安装 Evergreen Runtime |
| 显卡 | 推荐 4 GB 显存；没有独显也能 CPU 跑，但慢 |
| 磁盘 | 至少 8 GB 可用 |
| 网络 | 首次安装需要；装好后运行完全离线 |

## 安装后目录

```
MangaTranslator/
├─ MangaTranslator.exe      双击这个
├─ native/                  原生窗口运行库（必须保留）
├─ scripts/setup.bat        首次安装
├─ models/                  setup 下载的模型
├─ vendor/llama/            setup 下载的 llama.cpp
├─ .venv/                   setup 创建的 Python 环境
└─ data/                    你的项目、译文、设置
```

## 更新

- 保留 `data/`（你的项目）和 `models/`；
- 用新版本覆盖其余文件；
- 如果依赖有变化，再运行一次 `scripts\setup.bat`。

## 卸载

直接删除整个程序文件夹即可。所有项目数据都在 `data/` 里；删除前请自行备份。

## 常见问题

| 现象 | 处理 |
|---|---|
| 双击 exe 没反应 | 先运行 `start.bat` 看 Python 报错；检查是否被杀毒软件拦截 |
| 窗口空白 / 一直转圈 | 看 `data/desktop.log`；确认 `native\` 完整、WebView2 Runtime 已安装 |
| `setup.bat` 下载失败 | 检查网络；重新运行会从断点继续/覆盖重下 |
| 提示找不到模型 | 确认 `models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf` 存在；或重新运行 setup |
| 显存不足 | 设置里把 `llama_gpu_layers` 调低（20 或 0） |
| 中文显示方块 | 安装微软雅黑字体（Windows 通常自带） |

更多说明见仓库根目录 `README.md`。
