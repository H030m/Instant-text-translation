r"""監看逐字稿檔，出現 quiz 相關關鍵字時跳出 Windows 通知。

用法：
    .\alert.ps1                      # 自動監看 output\ 下最新的 live-*.txt
    .\alert.ps1 output\xxx.txt       # 指定檔案
    .\alert.ps1 --test               # 只發一則測試通知
    .\alert.ps1 --replay output\xxx.txt   # 掃整份檔案、印出會觸發的行（不通知），用來調關鍵字
"""
import argparse
import base64
import glob
import os
import re
import subprocess
import sys
import time

# 單行關鍵字：一行命中就通知。Whisper 會混出簡體，所以繁簡都寫。
KEYWORDS = [
    ("小考", r"小考|隨堂|随堂"),
    ("同學問題", r"回答.{0,4}同[學学]|同[學学].{0,3}[問问]|同[學学]的?[問问]題?|[問问]題?.{0,2}同[學学]"),
    ("點名/抽問", r"點名|点名|抽[問问]|請.{0,3}回答|请.{0,3}回答"),
]
COOLDOWN = 30.0  # 同一類別幾秒內不重複通知

# Quiz 計分：看「最近 QUIZ_WINDOW 秒」內所有線索，每種線索只算一次，總分 >= QUIZ_THRESHOLD 就通知。
# Whisper 常把 Quiz 聽錯（跪子、CREASE…），單靠一個詞會漏；多個弱線索加起來就能補上。
QUIZ_CUES = [
    (3, "Quiz字樣", r"quiz|quize|crease|quis|kwiz|跪子|奎[茲兹]|考[茲兹]"),
    (2, "接下來進入", r"接下[來来]我[們们]就[進进]|接下[來来].{0,3}[問问]大家"),
    (1, "題目用語", r"考[題题]|[這这]一?題|[答對对]對?幾題|選項|选项|作答|投票|民調|民调|小考|測驗|测验|考試|考试"),
    (1, "第N個/階段", r"第[一二三四五六七八九十\d]+(?:個|个|階段|阶段|段|題|题)"),
]
QUIZ_WINDOW = 40.0
QUIZ_THRESHOLD = 3
QUIZ_COOLDOWN = 90.0

COMPILED = [(n, re.compile(p, re.IGNORECASE)) for n, p in KEYWORDS]
QUIZ_COMPILED = [(w, n, re.compile(p, re.IGNORECASE)) for w, n, p in QUIZ_CUES]
LINE_RE = re.compile(r"^\[\s*(\d+(?:\.\d+)?)s[^\]]*\]\s*(.*)$")


class Detector:
    """逐行餵入逐字稿，回傳 [(類別, 通知內文)]。live 與 replay 共用同一套邏輯。"""

    def __init__(self):
        self.window = []  # (時間, 文字)
        self.last = {}

    def feed(self, t, text):
        out = []
        for name, rx in COMPILED:
            if rx.search(text) and t - self.last.get(name, -1e9) >= COOLDOWN:
                self.last[name] = t
                out.append((name, text))
        self.window = [(wt, x) for wt, x in self.window if t - wt <= QUIZ_WINDOW] + [(t, text)]
        joined = " ".join(x for _, x in self.window)
        score, why = 0, []
        for w, n, rx in QUIZ_COMPILED:
            if rx.search(joined):
                score += w
                why.append(n)
        if score >= QUIZ_THRESHOLD and t - self.last.get("quiz", -1e9) >= QUIZ_COOLDOWN:
            self.last["quiz"] = t
            out.append((f"疑似 Quiz（{score}分：{'+'.join(why)}）", " / ".join(x for _, x in self.window[-4:])))
        return out


def parse(line):
    m = LINE_RE.match(line.strip())
    return (float(m.group(1)), m.group(2)) if m else (None, line.strip())


def toast(title, body):
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "''")

    ps = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml('<toast scenario="reminder"><visual><binding template="ToastGeneric"><text>{esc(title)}</text><text>{esc(body)}</text></binding></visual><audio src="ms-winsoundevent:Notification.Reminder"/></toast>')
$id = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def latest(outdir):
    files = glob.glob(os.path.join(outdir, "live-*.txt"))
    return max(files, key=os.path.getmtime) if files else None


def replay(path):
    det = Detector()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            t, text = parse(line)
            if t is None:
                continue
            for name, body in det.feed(t, text):
                print(f"[{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}] {name}: {body}")


def watch(path, outdir):
    det = Detector()
    cur, fh = None, None
    print("監看中，Ctrl+C 結束。提醒類別：疑似 Quiz（計分）、" + "、".join(n for n, _ in KEYWORDS))
    while True:
        # 沒指定檔案時，跟著最新的 live-*.txt（換新一堂課會自動切換）
        target = path or latest(outdir)
        if target and target != cur:
            if fh:
                fh.close()
            fh = open(target, encoding="utf-8", errors="replace")
            fh.seek(0, os.SEEK_END)  # 只看之後新增的內容
            cur = target
            print(f"監看檔案：{cur}")
        if fh:
            while True:
                pos = fh.tell()
                line = fh.readline()
                if not line:
                    break
                if not line.endswith("\n"):  # 寫到一半，下次再讀
                    fh.seek(pos)
                    break
                t, text = parse(line)
                if t is None:
                    continue
                for name, body in det.feed(t, text):
                    print(f"[{time.strftime('%H:%M:%S')}] {name}: {body}")
                    toast(f"課程提醒：{name}", body)
        time.sleep(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="逐字稿檔；省略則自動取 output\\ 最新的 live-*.txt")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--replay", action="store_true")
    a = ap.parse_args()
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    if a.test:
        toast("課程關鍵字：測試", "同學，這是測試通知")
        time.sleep(2)
        return
    if a.replay:
        replay(a.file or latest(outdir))
        return
    try:
        watch(a.file, outdir)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
