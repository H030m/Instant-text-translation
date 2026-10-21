.\start.ps1 -Model base -Language auto -RefreshSeconds 25


.\alert.ps1              # 自動監看 output\ 最新的 live-*.txt，下一堂課換檔會自動切過去
.\alert.ps1 --test       # 先發一則測試通知，確認有跳出來
.\alert.ps1 --replay output\live-20261014-152031.txt   # 掃舊逐字稿，看哪些行會觸發

.\ask.ps1