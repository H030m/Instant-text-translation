r"""複製題目 → 按 Enter → 根據當天逐字稿回答（約 5–10 秒）。

用法：
    .\ask.ps1                          # 用 output\ 最新那天的所有 live-*.txt，等你按 Enter
    .\ask.ps1 --model haiku --effort low
    .\ask.ps1 --file output\xxx.txt    # 只用指定的逐字稿

透過本機 Claude Code CLI（claude -p）呼叫，走你現有的帳號，不需要 API key。
問答紀錄寫在 output\ask-log.txt。
"""
import argparse
import glob
import msvcrt
import os
import re
import shutil
import subprocess
import sys
import time

from alert import toast

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(ROOT, "output")
TS_RE = re.compile(r"^\[[^\]]*\]\s*")
SYSTEM = (
    "你是課堂助教。<transcript> 是這堂課到目前為止的逐字稿，由語音辨識產生，錯字和同音字很多，"
    "請依上下文理解。根據逐字稿回答使用者貼上的題目；逐字稿沒提到的，用一般知識回答並註明。"
    "第一行只寫答案（選擇題寫選項），第二行用一句話引用逐字稿依據。繁體中文，不要多寫。"
)

# 終端機顏色（ANSI）；答案第一行亮黃粗體，依據用青色
ANS = "\033[1;93m"
WHY = "\033[96m"
DIM = "\033[2m"
RST = "\033[0m"


def latest():
    files = glob.glob(os.path.join(OUTDIR, "live-*.txt"))
    return max(files, key=os.path.getmtime) if files else None


def same_day(path):
    """同一天的所有 live-YYYYMMDD-*.txt（中途重開 start.ps1 會切成好幾個檔）。"""
    day = os.path.basename(path).split("-")[1]
    return sorted(glob.glob(os.path.join(OUTDIR, f"live-{day}-*.txt")))


def clipboard():
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    return r.stdout.strip()


def transcript(paths):
    lines = []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines += [TS_RE.sub("", l).strip() for l in f if l.strip()]
    return "\n".join(lines)


def flush_keys():
    """丟掉等待期間多按的鍵，免得同一題被重送。"""
    while msvcrt.kbhit():
        msvcrt.getwch()


def ask(question, paths, model, effort, claude):
    prompt = f"<transcript>\n{transcript(paths)}\n</transcript>\n\n題目：\n{question}\n"
    r = subprocess.run(
        [claude, "-p", "--model", model, "--effort", effort,
         "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
         "--no-session-persistence", "--system-prompt", SYSTEM],
        input=prompt, capture_output=True, encoding="utf-8", errors="replace", cwd=OUTDIR,
    )
    return (r.stdout.strip() or r.stderr.strip() or "(沒有回應)")


def show(ans):
    first, _, rest = ans.partition("\n")
    print(f"\n{ANS}{first}{RST}")
    if rest.strip():
        print(f"{WHY}{rest.strip()}{RST}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="只用這份逐字稿；省略則用 output\\ 最新那天的所有 live-*.txt")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="medium")
    a = ap.parse_args()
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    os.system("")  # 讓舊版 Windows 主控台也吃 ANSI 顏色
    claude = shutil.which("claude")
    if not claude:
        sys.exit("找不到 claude 指令（Claude Code CLI）。")
    print(f"模型：{a.model} / {a.effort}。複製題目後回到這裡按 Enter；輸入 q 離開。")
    last_q, last_ans = None, None
    while True:
        try:
            if input("\n[Enter 送出剪貼簿題目] ").strip().lower() == "q":
                break
        except (EOFError, KeyboardInterrupt):
            break
        path = a.file or latest()
        if not path:
            print("output\\ 底下沒有 live-*.txt")
            continue
        q = clipboard()
        if not q:
            print("剪貼簿是空的")
            continue
        if q == last_q:
            print(f"{DIM}剪貼簿跟上一題一樣，不重問。上一題答案：{RST}")
            show(last_ans)
            continue
        paths = [a.file] if a.file else same_day(path)
        names = "、".join(os.path.basename(p) for p in paths)
        print(f"{DIM}題目：{q[:200]}\n逐字稿：{names}　思考中…{RST}", flush=True)
        t0 = time.time()
        try:
            ans = ask(q, paths, a.model, a.effort, claude)
        except KeyboardInterrupt:
            print("\n已取消這題")
            flush_keys()
            continue
        dt = time.time() - t0
        flush_keys()
        last_q, last_ans = q, ans
        show(ans)
        print(f"{DIM}（{dt:.1f} 秒）{RST}")
        toast("Quiz 答案", ans[:250])
        with open(os.path.join(OUTDIR, "ask-log.txt"), "a", encoding="utf-8") as f:
            f.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {names} {a.model}/{a.effort} {dt:.1f}s\n"
                    f"Q: {q}\nA: {ans}\n\n")


if __name__ == "__main__":
    main()
