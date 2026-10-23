from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

# The bundled dependency directory lives next to this file; make `python app.py`
# work without having to set PYTHONPATH first.
ROOT = Path(__file__).resolve().parent
if str(ROOT / ".pylibs") not in sys.path:
    sys.path.insert(0, str(ROOT / ".pylibs"))

# Fully local by default: never reach out to HuggingFace, and keep torch's
# compilation cache inside data/ instead of the project root.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", str(ROOT / "data" / ".torch_cache"))
(ROOT / "data" / ".torch_cache").mkdir(parents=True, exist_ok=True)

import uvicorn
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from mt import jobs, llm, pdf, pipeline, store
from mt.config import DATA_DIR, ROOT, STATIC_DIR, TARGET_NAMES, load_settings, save_settings

app = FastAPI(title="漫画译站", docs_url="/api/docs", redoc_url=None)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

MAX_UPLOAD = 150 * 1024 * 1024
MAX_PAGES = 300


def _page(pid: str, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    project = store.load_project(pid)
    if index < 0 or index >= project["page_count"]:
        raise HTTPException(404, "页码超出范围")
    return project, project["pages"][index]


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    path = STATIC_DIR / "index.html"
    if not path.exists():
        return HTMLResponse("<h3>前端文件缺失：static/index.html</h3>", status_code=500)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "version": "1.0.0"}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    cfg = load_settings()
    safe = dict(cfg)
    safe["openai_api_key"] = "***" if cfg.get("openai_api_key") else ""
    return {
        "settings": safe,
        "model": llm.model_info(cfg),
        "llm_running": llm.health(cfg),
        "targets": TARGET_NAMES,
    }


@app.post("/api/settings")
def update_settings(patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if patch.get("openai_api_key") == "***":
        patch.pop("openai_api_key", None)
    save_settings(patch)
    return get_settings()


@app.get("/api/projects")
def projects() -> dict[str, Any]:
    return {"projects": store.list_projects()}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    return await _ingest([file])


@app.post("/api/upload-batch")
async def upload_batch(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    return await _ingest(files)


def _natural_key(name: str) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


async def _ingest(files: list[UploadFile]) -> dict[str, Any]:
    if not files:
        raise HTTPException(400, "没有收到文件")
    settings = load_settings()
    ordered = sorted(files, key=lambda f: _natural_key(Path(f.filename or "").name))
    entries: list[dict[str, Any]] = []
    sources: list[tuple[str, bytes]] = []
    total_bytes = 0
    for f in ordered:
        data = await f.read()
        if not data:
            continue
        total_bytes += len(data)
        if total_bytes > MAX_UPLOAD * 2:
            raise HTTPException(400, "一次上传的文件总大小超过 300MB")
        filename = Path(f.filename or "upload").name
        suffix = Path(filename).suffix.lower()
        try:
            if suffix == ".pdf":
                rendered = pdf.render_pdf(data)
                if not rendered:
                    raise HTTPException(400, f"{filename} 中没有页面")
                for p in rendered:
                    entries.append({"image": p["image"], "meta": p, "source": filename})
                sources.append((filename, data))
            elif suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"):
                img, meta = pdf.load_image_bytes(data)
                entries.append({"image": img, "meta": meta, "source": filename})
                sources.append((filename, data))
            else:
                raise HTTPException(400, f"不支持的文件类型：{filename}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"读取 {filename} 失败：{e}")
    if not entries:
        raise HTTPException(400, "文件为空")
    if len(entries) > MAX_PAGES:
        raise HTTPException(400, f"总页数过多（{len(entries)}），当前上限 {MAX_PAGES} 页")

    first_stem = Path(sources[0][0]).stem if sources else "漫画"
    if len(entries) > 1:
        m = re.match(r"^(.*?)[\s_\-]*\d+$", first_stem)
        base = m.group(1).strip() if m and len(m.group(1).strip()) >= 2 else first_stem
        name = f"{base}（{len(entries)} 页）"
    else:
        name = first_stem
    kinds = {Path(n).suffix.lower() for n, _ in sources}
    source_type = "pdf" if kinds == {".pdf"} else ("images" if ".pdf" not in kinds else "mixed")

    project = store.create_project(
        name=name,
        source_type=source_type,
        pages=[e["meta"] for e in entries],
        source_filename=", ".join(n for n, _ in sources[:3]) + ("…" if len(sources) > 3 else ""),
        source_lang=settings.get("source_lang", "ja"),
        target_lang=settings.get("target_lang", "zh"),
    )
    pid = project["id"]
    pdir = store.project_dir(pid)
    src_dir = pdir / "source"
    src_dir.mkdir(parents=True, exist_ok=True)
    for si, (fname, data) in enumerate(sources):
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", fname)
        (src_dir / f"{si + 1:03d}_{safe}").write_bytes(data)
    for i, e in enumerate(entries):
        pdf.save_page_png(e["image"], store.page_image_path(pid, i))
    return {"project": project, "page": project["pages"][0], "pages": len(entries)}


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict[str, Any]:
    try:
        return {"project": store.load_project(pid)}
    except FileNotFoundError:
        raise HTTPException(404, "项目不存在")


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    project = store.load_project(pid)
    if "name" in patch:
        project["name"] = str(patch["name"])[:80]
    if "target_lang" in patch and patch["target_lang"] in TARGET_NAMES:
        project["target_lang"] = patch["target_lang"]
    if "source_lang" in patch:
        project["source_lang"] = str(patch["source_lang"])
    if "context" in patch and isinstance(patch["context"], dict):
        ctx = project.setdefault("context", {})
        for k in ("series", "synopsis", "characters", "glossary", "notes"):
            if k in patch["context"]:
                ctx[k] = patch["context"][k]
    store.save_project(project)
    return {"project": project}


@app.delete("/api/projects/{pid}")
def delete_project(pid: str) -> dict[str, Any]:
    store.delete_project(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/pages/{index}/original")
def page_original(pid: str, index: int) -> FileResponse:
    _page(pid, index)
    path = store.page_image_path(pid, index)
    if not path.exists():
        raise HTTPException(404, "原图不存在")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.get("/api/projects/{pid}/pages/{index}/translated")
def page_translated(pid: str, index: int) -> FileResponse:
    _page(pid, index)
    path = store.page_image_path(pid, index, "translated")
    if not path.exists():
        raise HTTPException(404, "译文页尚未生成")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.get("/api/projects/{pid}/pages/{index}/download")
def page_download(pid: str, index: int) -> FileResponse:
    project = store.load_project(pid)
    path = store.page_image_path(pid, index, "translated")
    if not path.exists():
        raise HTTPException(404, "译文页尚未生成")
    name = f"{project['name']}-{index + 1:03d}-zh.png"
    return FileResponse(path, media_type="image/png", filename=name)


@app.get("/api/projects/{pid}/pages/{index}/data")
def page_data(pid: str, index: int) -> dict[str, Any]:
    _page(pid, index)
    data = store.load_page_data(pid, index)
    data["index"] = index
    return data


@app.post("/api/projects/{pid}/pages/{index}/analyze")
def analyze(pid: str, index: int) -> dict[str, Any]:
    _page(pid, index)
    try:
        return pipeline.analyze_page(pid, index)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{pid}/pages/{index}/translate")
def translate(pid: str, index: int) -> dict[str, Any]:
    _page(pid, index)
    try:
        return pipeline.translate_page(pid, index)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{pid}/pages/{index}/render")
def render(pid: str, index: int) -> dict[str, Any]:
    _page(pid, index)
    try:
        return pipeline.render_page(pid, index)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.patch("/api/projects/{pid}/pages/{index}/bubbles/{bid}")
def patch_bubble(pid: str, index: int, bid: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    project, page = _page(pid, index)
    data = store.load_page_data(pid, index)
    target = next((b for b in data.get("bubbles", []) if b["id"] == bid), None)
    if not target:
        raise HTTPException(404, "气泡不存在")
    if "source_text" in patch and patch["source_text"] != target.get("source_text"):
        target.pop("source_fixed", None)
    for key in (
        "translation",
        "source_text",
        "speaker",
        "orientation",
        "skip",
        "font_size",
        "color",
        "stroke",
        "kind",
        "text_bbox",
        "bbox",
        "bubble_poly",
    ):
        if key in patch:
            target[key] = patch[key]
    if "bbox" in patch and "bubble_poly" not in patch and target.get("kind") == "text":
        x0, y0, x1, y1 = target["bbox"]
        target["bubble_poly"] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    store.save_page_data(pid, index, data)
    store.update_page(project, index, status="translated")
    store.save_project(project)
    return {"bubble": target}


@app.post("/api/projects/{pid}/pages/{index}/bubbles")
def add_bubble(pid: str, index: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    project, page = _page(pid, index)
    data = store.load_page_data(pid, index)
    x0, y0, x1, y1 = body.get("bbox", [0, 0, 100, 60])
    bid = "m" + str(int(time.time() * 1000))[-7:]
    bubble = {
        "id": bid,
        "bbox": [x0, y0, x1, y1],
        "bubble_poly": body.get("bubble_poly") or [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "text_bbox": [x0, y0, x1, y1],
        "lines": [],
        "source_text": body.get("source_text", ""),
        "translation": body.get("translation", ""),
        "speaker": "",
        "kind": "text",
        "orientation": "horizontal",
        "confidence": 1.0,
        "bg": 255,
        "bg_rgb": [255, 255, 255],
        "bg_uniform": False,
        "dark_ratio": 0,
        "font_size": 0,
        "color": "#111111",
        "stroke": True,
        "skip": False,
    }
    data.setdefault("bubbles", []).append(bubble)
    store.save_page_data(pid, index, data)
    store.update_page(project, index, status="translated", bubble_count=len(data["bubbles"]))
    store.save_project(project)
    return {"bubble": bubble}


@app.delete("/api/projects/{pid}/pages/{index}/bubbles/{bid}")
def delete_bubble(pid: str, index: int, bid: str) -> dict[str, Any]:
    project, page = _page(pid, index)
    data = store.load_page_data(pid, index)
    data["bubbles"] = [b for b in data.get("bubbles", []) if b["id"] != bid]
    store.save_page_data(pid, index, data)
    store.update_page(project, index, status="translated", bubble_count=len(data["bubbles"]))
    store.save_project(project)
    return {"ok": True}


@app.post("/api/projects/{pid}/pages/{index}/bubbles/{bid}/retranslate")
def retranslate(pid: str, index: int, bid: str) -> dict[str, Any]:
    _page(pid, index)
    try:
        return {"bubble": pipeline.retranslate_bubble(pid, index, bid, load_settings())}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{pid}/process")
def process_project(pid: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    project = store.load_project(pid)
    indices = body.get("indices")
    if indices is None:
        start = int(body.get("start", 0))
        indices = list(range(start, project["page_count"]))
    settings = load_settings()

    def runner(job: jobs.Job) -> dict[str, Any]:
        job.total = len(indices)
        res = pipeline.process_project(
            pid,
            settings,
            progress=lambda d, t, m: job.update(d, t, m),
            should_cancel=job.cancelled,
            indices=indices,
        )
        job.errors.extend(res.get("errors", []))
        return res

    job = jobs.create("process", pid, runner)
    job.total = len(indices)
    return {"job": job.to_dict()}


@app.post("/api/projects/{pid}/analyze-all")
def analyze_all(pid: str) -> dict[str, Any]:
    project = store.load_project(pid)
    settings = load_settings()

    def runner(job: jobs.Job) -> dict[str, Any]:
        total = project["page_count"]
        job.total = total
        found = 0
        for i in range(total):
            if job.cancelled():
                break
            job.update(i, total, f"正在分析第 {i + 1}/{total} 页")
            try:
                res = pipeline.analyze_page(pid, i, settings)
                found += res.get("meta", {}).get("bubbles", 0)
            except Exception as e:
                job.errors.append(f"第 {i + 1} 页：{e}")
        return {"bubbles": found, "pages": total}

    job = jobs.create("analyze", pid, runner)
    return {"job": job.to_dict()}


@app.get("/api/jobs/{jid}")
def job_status(jid: str) -> dict[str, Any]:
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")
    return {"job": job.to_dict()}


@app.post("/api/jobs/{jid}/cancel")
def job_cancel(jid: str) -> dict[str, Any]:
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")
    job.cancel()
    return {"job": job.to_dict()}


@app.get("/api/llm/status")
def llm_status() -> dict[str, Any]:
    cfg = load_settings()
    return {"running": llm.health(cfg), "model": llm.model_info(cfg), "log": llm.server_log_tail(20)}


@app.post("/api/llm/start")
def llm_start() -> dict[str, Any]:
    return llm.start_server()


@app.post("/api/llm/stop")
def llm_stop() -> dict[str, Any]:
    llm.stop_server()
    return {"ok": True}


@app.post("/api/shutdown")
def shutdown() -> dict[str, Any]:
    """Quit the local server and the llama.cpp child process."""

    def _exit() -> None:
        time.sleep(0.4)
        try:
            llm.stop_server()
        finally:
            os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return {"ok": True}


@app.post("/api/translate/preview")
def preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "文本为空")
    cfg = load_settings()
    try:
        if cfg.get("provider") == "google":
            out = llm.google_free(text, cfg.get("source_lang", "ja"), cfg.get("target_lang", "zh"))
        else:
            messages = [
                {"role": "system", "content": "你是漫画汉化译者，把下面的台词翻译成自然口语化的简体中文。只输出译文，不要解释。"},
                {"role": "user", "content": text},
            ]
            out = llm.chat(messages, temperature=0.3, max_tokens=200, settings=cfg).strip()
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"translation": out}


@app.post("/api/projects/{pid}/export/pdf")
def export_pdf(pid: str, body: dict[str, Any] = Body(default={})) -> FileResponse:
    project = store.load_project(pid)
    mode = body.get("mode", "translated")
    if mode not in ("translated", "bilingual"):
        raise HTTPException(400, "导出模式无效")
    try:
        path = pipeline.export_pdf(pid, mode)
    except Exception as e:
        raise HTTPException(400, str(e))
    suffix = "译文" if mode == "translated" else "双语"
    return FileResponse(path, media_type="application/pdf", filename=f"{project['name']}-{suffix}.pdf")


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    return {"projects": len(store.list_projects()), "storage": store.data_usage()}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


def _free_port(start: int = 8765) -> int:
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("找不到可用端口")


def main() -> None:
    settings = load_settings()
    port = int(os.environ.get("MT_PORT") or _free_port())
    url = f"http://127.0.0.1:{port}"
    try:
        (ROOT / "打开界面.url").write_text(f"[InternetShortcut]\r\nURL={url}\r\n", encoding="utf-8")
    except Exception:
        pass

    def open_when_ready() -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.6):
                    break
            except OSError:
                time.sleep(0.4)
        # Only used when running app.py directly for debugging. The shipped
        # MangaTranslator.exe hosts the UI in its own native WebView2 window.
        try:
            webbrowser.open(url)
        except Exception:
            try:
                os.startfile(url)  # type: ignore[attr-defined]
            except Exception:
                pass

    if settings.get("auto_start_llm") and settings.get("provider") == "local":
        threading.Thread(target=lambda: llm.start_server(settings), daemon=True, name="llm-warmup").start()

    if settings.get("source_lang", "ja") in ("ja", "auto"):
        from mt import manga_ocr

        if manga_ocr.available():
            threading.Thread(target=manga_ocr.warmup, daemon=True, name="ocr-warmup").start()

    if not os.environ.get("MT_NO_BROWSER"):
        threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"\n  漫画译站已启动: {url}\n  如果没有自动弹出窗口，直接双击项目里的「打开界面.url」\n  按 Ctrl+C 退出\n")
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        llm.stop_server()


if __name__ == "__main__":
    main()
