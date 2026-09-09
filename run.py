from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from time import perf_counter, sleep
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
MODEL_DIR = ROOT_DIR / "models"
CACHE_DIR = ROOT_DIR / "cache"
OUTPUT_DIR = ROOT_DIR / "output"
DEFAULT_SOURCE = "https://www.youtube.com/live/0Hb5laOEUVs"

os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(MODEL_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_DIR))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
from faster_whisper import WhisperModel
from yt_dlp import YoutubeDL


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="將直播網址或本地影音即時轉成 UTF-8 文字檔。")
    parser.add_argument("source", nargs="?", default=DEFAULT_SOURCE, help=f"直播網址或本地影音路徑（預設：{DEFAULT_SOURCE}）")
    parser.add_argument("--model", default="small", help="Whisper 模型名稱（預設：small）")
    parser.add_argument("--language", default="zh", help="語言代碼（預設：zh；自動偵測用 auto）")
    parser.add_argument("--chunk-seconds", type=float, default=5.0, help="每段音訊秒數（預設：5）")
    parser.add_argument("--cpu-threads", type=int, default=min(10, os.cpu_count() or 1), help="CPU 執行緒數（預設：最多 10）")
    parser.add_argument("--output", type=Path, help="輸出文字檔路徑")
    parser.add_argument(
        "--refresh-seconds",
        type=float,
        default=20.0,
        help="直播 signed URL 刷新間隔（預設：20；本地檔案忽略）",
    )
    parser.add_argument("--download-only", action="store_true", help="只下載／載入模型，完成後離開")
    args = parser.parse_args()
    if args.chunk_seconds <= 0:
        parser.error("--chunk-seconds 必須大於 0")
    if args.cpu_threads <= 0:
        parser.error("--cpu-threads 必須大於 0")
    if args.refresh_seconds < 0:
        parser.error("--refresh-seconds 不可小於 0")
    return args


def is_web_url(value: str) -> bool:
    return urlparse(value).scheme.lower() in {"http", "https"}


def open_audio_stream(
    source: str, buffer_size: int
) -> tuple[subprocess.Popen[bytes], subprocess.Popen[bytes] | None, bool]:
    input_source = source
    http_headers = {}
    live_source = False

    if is_web_url(source):
        print("正在連接直播網址……", flush=True)
        options = {
            "format": "worst[acodec!=none]/best[acodec!=none]",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(source, download=False)
        input_source = info.get("url")
        if not input_source:
            raise RuntimeError("yt-dlp 沒有回傳可播放的直播網址。")
        http_headers = info.get("http_headers") or {}
        live_source = bool(
            info.get("is_live")
            or info.get("live_status") in {"is_live", "is_upcoming"}
        )
    else:
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"找不到影音檔：{path}")
        input_source = str(path)

    ffmpeg_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
    ]
    if http_headers:
        header_text = "".join(
            f"{name}: {value}\r\n" for name, value in http_headers.items()
        )
        ffmpeg_command.extend(["-headers", header_text])
    if is_web_url(source):
        ffmpeg_command.extend([
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_http_error", "403,404,5xx",
            "-reconnect_delay_max", "5",
        ])
    ffmpeg_command.extend([
        "-i", input_source,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-f", "s16le", "pipe:1",
    ])
    process = subprocess.Popen(
        ffmpeg_command,
        stdout=subprocess.PIPE,
        bufsize=buffer_size * 2,
    )
    return process, None, live_source


def read_audio_chunks(
    process: subprocess.Popen[bytes],
    chunk_bytes: int,
    bytes_per_second: int,
    audio_queue: Queue[tuple[float, bytes] | None],
) -> None:
    offset_seconds = 0.0
    try:
        if process.stdout is None:
            return
        while True:
            raw_audio = process.stdout.read(chunk_bytes)
            if not raw_audio:
                break
            audio_queue.put((offset_seconds, raw_audio))
            offset_seconds += len(raw_audio) / bytes_per_second
    finally:
        audio_queue.put(None)


def load_model(model_name: str, cpu_threads: int) -> WhisperModel:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"正在載入模型 {model_name!r}（CPU / int8 / {cpu_threads} threads）……", flush=True)
    return WhisperModel(
        model_name, device="cpu", compute_type="int8",
        cpu_threads=cpu_threads, download_root=str(MODEL_DIR),
    )


def transcribe_stream_once(args: argparse.Namespace, model: WhisperModel) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("找不到 ffmpeg；請先執行 setup.ps1 或安裝 FFmpeg。")
    output_path = args.output
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = OUTPUT_DIR / f"live-{stamp}.txt"
    elif not output_path.is_absolute():
        output_path = ROOT_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_per_second = 16000 * 2
    chunk_bytes = int(bytes_per_second * args.chunk_seconds)
    language = None if args.language.lower() == "auto" else args.language
    print(f"輸出：{output_path}", flush=True)
    print("開始轉寫；按 Ctrl+C 停止。", flush=True)
    process, downloader, _ = open_audio_stream(args.source, chunk_bytes)
    audio_queue: Queue[tuple[float, bytes] | None] = Queue(maxsize=24)
    reader = Thread(
        target=read_audio_chunks,
        args=(process, chunk_bytes, bytes_per_second, audio_queue),
        daemon=True,
    )
    reader.start()
    try:
        with output_path.open("a", encoding="utf-8", buffering=1) as output_file:
            while True:
                try:
                    item = audio_queue.get(timeout=0.5)
                except Empty:
                    if process.poll() is not None and not reader.is_alive():
                        break
                    continue
                if item is None:
                    break
                offset_seconds, raw_audio = item
                started_at = perf_counter()
                actual_seconds = len(raw_audio) / bytes_per_second
                audio = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
                segments, _ = model.transcribe(
                    audio, language=language, beam_size=1,
                    condition_on_previous_text=False, vad_filter=True,
                )
                for segment in segments:
                    start = offset_seconds + segment.start
                    end = offset_seconds + segment.end
                    line = f"[{start:09.2f}s -> {end:09.2f}s] {segment.text.strip()}"
                    print(line, flush=True)
                    output_file.write(line + "\n")
                elapsed = perf_counter() - started_at
                queued_seconds = audio_queue.qsize() * args.chunk_seconds
                print(
                    f"[效能] {actual_seconds:.1f}s 音訊 / {elapsed:.1f}s 處理"
                    f"；待處理約 {queued_seconds:.0f}s",
                    flush=True,
                )
    except KeyboardInterrupt:
        print("\n收到停止指令，正在關閉……", flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if downloader is not None and downloader.poll() is None:
            downloader.terminate()
            try:
                downloader.wait(timeout=5)
            except subprocess.TimeoutExpired:
                downloader.kill()
                downloader.wait()

    if process.returncode not in {0, 255, -15}:
        print(f"注意：FFmpeg 結束碼為 {process.returncode}。", file=sys.stderr)
    if downloader is not None and downloader.returncode not in {0, 1, -15}:
        print(f"注意：yt-dlp 結束碼為 {downloader.returncode}。", file=sys.stderr)
    return output_path


def transcribe_stream(args: argparse.Namespace, model: WhisperModel) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("找不到 ffmpeg；請先執行 setup.ps1 或安裝 FFmpeg。")
    output_path = args.output
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = OUTPUT_DIR / f"live-{stamp}.txt"
    elif not output_path.is_absolute():
        output_path = ROOT_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_per_second = 16000 * 2
    chunk_bytes = int(bytes_per_second * args.chunk_seconds)
    language = None if args.language.lower() == "auto" else args.language
    refresh_url = False
    stream_offset = 0.0

    print(f"輸出：{output_path}", flush=True)
    print("開始轉寫；按 Ctrl+C 停止。", flush=True)
    try:
        with output_path.open("a", encoding="utf-8", buffering=1) as output_file:
            while True:
                process, downloader, live_source = open_audio_stream(args.source, chunk_bytes)
                refresh_url = live_source and args.refresh_seconds > 0
                audio_queue: Queue[tuple[float, bytes] | None] = Queue(maxsize=24)
                reader = Thread(
                    target=read_audio_chunks,
                    args=(process, chunk_bytes, bytes_per_second, audio_queue),
                    daemon=True,
                )
                reader.start()
                stream_started = perf_counter()
                restart_stream = False
                try:
                    while True:
                        if refresh_url and perf_counter() - stream_started >= args.refresh_seconds:
                            restart_stream = True
                            print("[串流] 刷新 signed URL……", flush=True)
                            break
                        try:
                            item = audio_queue.get(timeout=0.5)
                        except Empty:
                            if process.poll() is not None and not reader.is_alive():
                                restart_stream = refresh_url
                                break
                            continue
                        if item is None:
                            restart_stream = refresh_url
                            break
                        local_offset, raw_audio = item
                        offset_seconds = stream_offset + local_offset
                        started_at = perf_counter()
                        actual_seconds = len(raw_audio) / bytes_per_second
                        audio = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
                        segments, _ = model.transcribe(
                            audio,
                            language=language,
                            beam_size=1,
                            condition_on_previous_text=False,
                            vad_filter=True,
                        )
                        for segment in segments:
                            start = offset_seconds + segment.start
                            end = offset_seconds + segment.end
                            line = f"[{start:09.2f}s -> {end:09.2f}s] {segment.text.strip()}"
                            print(line, flush=True)
                            output_file.write(line + "\n")
                        stream_offset = offset_seconds + actual_seconds
                        elapsed = perf_counter() - started_at
                        queued_seconds = audio_queue.qsize() * args.chunk_seconds
                        print(
                            f"[效能] {actual_seconds:.1f}s 音訊 / {elapsed:.1f}s 處理"
                            f"；待處理約 {queued_seconds:.0f}s",
                            flush=True,
                        )
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                    if downloader is not None and downloader.poll() is None:
                        downloader.terminate()
                        try:
                            downloader.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            downloader.kill()
                            downloader.wait()
                if not restart_stream:
                    break
                sleep(1)
    except KeyboardInterrupt:
        print("\n收到停止指令，正在關閉……", flush=True)
    return output_path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        model = load_model(args.model, args.cpu_threads)
        if args.download_only:
            print(f"模型已就緒：{MODEL_DIR}")
            return 0
        output_path = transcribe_stream(args, model)
        print(f"文字檔已儲存：{output_path}")
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"錯誤：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
