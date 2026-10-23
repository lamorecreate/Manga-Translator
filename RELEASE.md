# Release 发布说明

## 发布什么

GitHub Releases 里上传 **一个便携 ZIP**：

```
dist/MangaTranslator-1.0.0-win-x64.zip
```

不要只上传 `setup.bat`。`setup.bat` 只是 ZIP 里的安装脚本，用户单独拿到它无法运行。

ZIP 包含：

- `MangaTranslator.exe`（27 KB 启动器）
- `native/`（原生窗口运行库，约 120 MB）
- `app.py`、`mt/`、`static/`、`desktop/`（源码，供审阅）
- `scripts/setup.bat`、`scripts/setup.ps1`
- `README.md`、`INSTALL.md`、`DISCLAIMER.md`、`LICENSE`
- `start.bat`、`start-hidden.vbs`、`requirements.txt`

ZIP **不包含**：

- `models/`（Qwen3 + manga-ocr，约 2.8 GB）
- `vendor/llama/`（约 100 MB）
- `.venv/`、`.pylibs/`
- `data/`（用户项目）

模型和 llama.cpp 由 `scripts/setup.bat` 从官方镜像下载。

## 打包

在仓库根目录运行：

```powershell
.\scripts\package-release.ps1 -Version 1.0.0
```

产物：

```
dist/MangaTranslator-1.0.0-win-x64.zip
dist/MangaTranslator-1.0.0-win-x64.zip.sha256.txt
```

## 发布步骤

1. 确认 `README.md` 顶部的免责声明没有被删除。
2. 提交并打标签：

```powershell
git add .
git commit -m "release: v1.0.0"
git tag v1.0.0
git push origin main --tags
```

3. 打开 GitHub 仓库 → **Releases** → **Draft a new release**：
   - Tag：`v1.0.0`
   - Title：`Manga Translator v1.0.0`
   - 描述：可以复制 `RELEASE_NOTES_v1.0.0.md`
4. 上传附件：
   - `MangaTranslator-1.0.0-win-x64.zip`
   - 可选：`MangaTranslator-1.0.0-win-x64.zip.sha256.txt`
5. 点击 **Publish release**。

## 为什么不把模型塞进 Release

- Qwen3-4B 约 2.4 GB，manga-ocr 约 450 MB；GitHub 单个 Release asset 上限 2 GB。
- 模型更新频繁，放进仓库会让 clone 极慢。
- 模型有自己的许可；由用户安装时从官方镜像下载更清晰。

如果确实需要离线包，建议单独提供网盘/对象存储，并在 Release 说明里给出链接，而不是塞进 GitHub。

## 版本号

- `VERSION` 文件
- `mt/__init__.py` 的 `__version__`
- `app.py` 的 `/api/health` 返回版本
- Release tag

发布前保持四处一致。
