# stream2txt：本機直播轉文字

這個版本用 `faster-whisper` 在本機 CPU 辨識，`yt-dlp` 解析直播網址，FFmpeg 讀取音訊。Python 環境、模型、快取與輸出都留在本目錄。

## 第一次安裝

```powershell
cd C:\Users\a0905\hpc\tools\stream2txt
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

`setup.ps1` 會建立 `.venv`、安裝固定版本套件，並把 `small` 模型下載到 `models`。

## 開始轉寫

```powershell
.\start.ps1
```

上面會使用原腳本中的預設 YouTube 直播。指定另一個網址或本地影音：

```powershell
.\start.ps1 "https://www.youtube.com/watch?v=你的影片ID"
.\start.ps1 "C:\完整路徑\錄影.mp4"
```

按 `Ctrl+C` 停止。文字即時寫入 `output\live-日期時間.txt`（UTF-8）。

## 常用調整

```powershell
# 速度不夠：改用較小模型
.\start.ps1 -Model base

# 自動偵測語言
.\start.ps1 -Language auto

# 指定輸出檔
.\start.ps1 -Output "output\my-live.txt"

# signed URL 每 20 秒自動刷新（預設值）
.\start.ps1 -Model base -RefreshSeconds 20
```

目前預設為 `small`、CPU `int8`、每 5 秒處理一次。模型越大通常越準，但延遲也越高。
直播網址預設每 20 秒重新由 yt-dlp 取得，避免 YouTube 的 signed HLS URL 在中途失效；設為 `0` 可停用自動刷新。

本機實測 `https://www.youtube.com/live/0Hb5laOEUVs` 的 HLS 分段約 30 秒後會由 Googlevideo 回傳 403；程式現在會每 20 秒重新取得 signed URL 來避開這種失效。如果其他來源仍持續 403，請換另一個穩定的直播 URL：

```powershell
.\start.ps1 "你的直播網址" -Model base
```

實測 `base` 在本機每 5 秒音訊約需 0.4–0.6 秒處理，能跟上即時速度；`small` 精度較高但可用 `-Model small` 自行比較。

## 本目錄內容

- `.venv`：專案專用 Python 與套件
- `models`：Whisper 模型
- `cache`：Hugging Face 與執行快取
- `output`：即時文字檔
- `script/command.sh`：可選的本機啟動便利指令

系統上的 `ffmpeg` 執行檔直接沿用；本機已確認可用。
