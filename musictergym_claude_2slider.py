"""
gym_recommender.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
의존성:  pip install requests
         brew install yt-dlp ffmpeg
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import csv, json, os, re, random, subprocess, threading
import tkinter as tk
from tkinter import filedialog, scrolledtext
import requests

# ── 설정 ──────────────────────────────────────────────────────
LASTFM_KEY   = "7ce625efb17cf8ecc9cc4eadda8ab3c4"
LASTFM_URL   = "https://ws.audioscrobbler.com/2.0/"
TARGET_SEC   = 90 * 60
MAX_DUR_SEC  = 7 * 60
FILTER_WORDS = ["live", "concert", "unplugged", "acoustic set",
                "cover", "karaoke"]

HERE         = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV  = os.path.join(HERE, "Gym_rat.csv")
DEFAULT_JSON = os.path.join(HERE, "history.json")
DEFAULT_OUT  = os.path.join(HERE, "downloads")
SETTINGS = os.path.join(HERE, "settings.json")

def load_settings():
    try:
        return json.load(open(SETTINGS))
    except:
        return {}

def save_settings(data):
    json.dump(data, open(SETTINGS, "w"))


def _make_btn(parent, text, command, bg="#222", fg="#dddddd"):
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                   font=("Menlo", 10), padx=10, pady=5, cursor="hand2")
    lbl.bind("<Button-1>", lambda e: command())
    return lbl
def _make_path_lbl(parent, var, bg, fg):
    lbl = tk.Label(parent, bg=bg, fg=fg, font=("Menlo",9),
                   width=18, anchor="w", cursor="hand2")
    def update(*_):
        full = var.get()
        name = os.path.basename(full)
        lbl.config(text="…/" + name)
    def open_vscode(e):
        subprocess.run(["open", "-a", "Visual Studio Code", var.get()])
    var.trace_add("write", update)
    lbl.bind("<Button-1>", open_vscode)
    update()
    return lbl

# ══ CSV 로드 ══════════════════════════════════════════════════
def load_csv(path):
    tracks = []
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            artist = row.get("Artist Name(s)", "").split(";")[0].strip()
            name   = row.get("Track Name", "").strip()
            if artist and name:
                tracks.append({"artist": artist, "name": name})
    return tracks


# ══ Last.fm ═══════════════════════════════════════════════════
def lastfm(method, params):
    p = {"method": method, "api_key": LASTFM_KEY, "format": "json", **params}
    try:
        r = requests.get(LASTFM_URL, params=p, timeout=10)
        return r.json()
    except Exception:
        return {}

def get_reco(tracks, similarity, adventure, history_keys, log):
    """
    similarity (0~100): 낮을수록 더 넓은 범위 허용
    adventure  (0~100): 낮으면 인기곡, 높으면 hidden gem
    """
    existing = set(f"{t['name'].lower()}|{t['artist'].lower()}" for t in tracks)
    seen     = set(history_keys) | existing

    # 걔 로직: S 낮으면 limit 넓게
    search_limit = 40 if similarity < 50 else 20

    # 걔 로직: threshold = (S/100) * 0.2 → 낮을수록 더 허용
    threshold = (similarity / 100) * 0.2

    # 랜덤 시드 30개
    seed_pool = random.sample(tracks, min(30, len(tracks)))

    log(f"🔍 시드 {len(seed_pool)}곡 → Last.fm track.getsimilar 수집")
    log(f"   search_limit={search_limit}  threshold={round(0.2 - threshold, 3)}")

    candidates = []

    for seed in seed_pool:
        data = lastfm("track.getsimilar", {
            "artist":      seed["artist"],
            "track":       seed["name"],
            "limit":       search_limit,
            "autocorrect": 1,
        })

        similar_tracks = data.get("similartracks", {}).get("track", [])
        for t in similar_tracks:
            score = float(t.get("match", 0))
            if score < (0.2 - threshold):
                continue

            t_name   = t.get("name", "").strip()
            t_artist = t.get("artist", {}).get("name", "").strip() \
                       if isinstance(t.get("artist"), dict) \
                       else t.get("artist", "").strip()
            if not t_name or not t_artist:
                continue

            key = f"{t_name.lower()}|{t_artist.lower()}"
            if key in seen:
                continue
            seen.add(key)

            # 리스너 수 조회 (adventure 정렬용)
            info = lastfm("track.getInfo", {
                "artist": t_artist, "track": t_name, "autocorrect": 1
            })
            listeners = int(info.get("track", {}).get("listeners", 0) or 0)

            dur = int(t.get("duration", 0)) or 210
            candidates.append({
                "artist":    t_artist,
                "name":      t_name,
                "dur":       dur,
                "key":       key,
                "listeners": listeners,
            })

    # 걔 로직: adventure 낮으면 인기곡, 높으면 hidden gem
    if adventure <= 50:
        candidates.sort(key=lambda x: x["listeners"], reverse=True)
    else:
        candidates.sort(key=lambda x: x["listeners"])

    # 아티스트당 최대 2곡 + 90분 채우기
    artist_count = {}
    reco  = []
    total = 0

    for r in candidates:
        if total >= TARGET_SEC:
            break
        if artist_count.get(r["artist"], 0) >= 2:
            continue
        reco.append(r)
        artist_count[r["artist"]] = artist_count.get(r["artist"], 0) + 1
        total += r["dur"]

    log(f"  → {len(reco)}곡 / 약 {total//60}분")
    return reco

# ══ YouTube 검색 & 다운로드 ═══════════════════════════════════
def search_and_filter(artist, name):
    query = f"{artist} {name}"
    cmd = ["/Library/Frameworks/Python.framework/Versions/3.14/bin/yt-dlp", f"ytsearch5:{query}",
           "--dump-json", "--no-playlist", "--quiet"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        return None, None

    for line in out.decode("utf-8", errors="ignore").strip().splitlines():
        try:
            info = json.loads(line)
        except Exception:
            continue
        title    = info.get("title", "").lower()
        duration = info.get("duration", 0) or 0
        if any(w in title for w in FILTER_WORDS):
            continue
        if duration > MAX_DUR_SEC:
            continue
        return info.get("webpage_url"), info.get("title")

    return None, None


def sanitize(s):
    return re.sub(r'[\\/*?:"<>|]', '', s).strip()


def download_track(artist, name, out_dir, log):
    url, yt_title = search_and_filter(artist, name)
    if not url:
        log(f"  ❌ 검색 실패: {name} — {artist}")
        return False

    log(f"  ▶ {name} — {artist}")
    log(f"    [{yt_title}]")

    fname   = sanitize(f"{name}-{artist}")
    out_tpl = os.path.join(out_dir, f"{fname}.%(ext)s")
    cmd = ["/Library/Frameworks/Python.framework/Versions/3.14/bin/yt-dlp", "-x", "--audio-format", "m4a",
            "--ffmpeg-location", "/usr/local/bin/ffmpeg",
           "--postprocessor-args", "ffmpeg:-b:a 128k",
           "-o", out_tpl, "--quiet", url]
    try:
        subprocess.run(cmd, timeout=180, check=True, stderr=subprocess.DEVNULL)
        log(f"    ✅ {fname}.m4a")
        return True
    except Exception as e:
        log(f"    ❌ 실패: {e}")
        return False


# ══ JSON 이력 ═════════════════════════════════════════════════
def load_history(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(path, history):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ══ GUI ═══════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MusicTerGYM")
        self.resizable(False, False)
        self._out_dir = tk.StringVar(value=DEFAULT_OUT)
        self.configure(bg="#141414")
        self._csv     = tk.StringVar(value=DEFAULT_CSV)
        self._json    = tk.StringVar(value=DEFAULT_JSON)
        self._running = False
        s = load_settings()
        self._json    = tk.StringVar(value=s.get("json", DEFAULT_JSON))
        self._out_dir = tk.StringVar(value=s.get("out",  DEFAULT_OUT))
        self._stop    = False
        self._build()

    def _build(self):
        BG  = "#141414"
        FG  = "#A9A7A7"
        ACC = "#E456B7"
        PAD = dict(padx=8, pady=4)

        # 타이틀 이미지
        self._title_img = tk.PhotoImage(file=os.path.join(HERE, "titleimg.png"))
        tk.Label(self, image=self._title_img, bg=BG).pack(fill="x")

        # ── 파일 행 ──
        r0 = tk.Frame(self, bg=BG); r0.pack(fill="x", **PAD)
        _make_btn(r0, text="CSV",  bg="#222", fg=FG,
                  command=self._pick_csv).pack(side="left", padx=(0,4))
        _make_path_lbl(r0, self._csv, BG, "#888").pack(side="left")
        _make_btn(r0, text="JSON", bg="#222", fg=FG,
                  command=self._pick_json).pack(side="left", padx=(10,4))
        _make_path_lbl(r0, self._json, BG, "#888").pack(side="left")

        # ── 로그창 ──
        frame = scrolledtext.ScrolledText(
            self, width=76, height=20,
            bg="#0d0d0d", fg="#b0b0b0", font=("Menlo",10),
            insertbackground=ACC, relief="flat", bd=0,highlightthickness=0, state="disabled"),
            
        
         
        self._log_box = tk.Text(
                self, width=76, height=15,
                bg="#000000", fg="#b0b0b0", font=("Menlo",10),
                insertbackground=ACC, relief="flat", bd=0,
                highlightthickness=0, state="disabled")
        self._log_box.pack(fill="both", **PAD)
        # ── S 슬라이더 (Similarity) ──
        r1 = tk.Frame(self, bg=BG); r1.pack(fill="x", **PAD)

        tk.Label(r1, text="S=", bg=BG, fg=FG,
                 font=("Menlo",10)).pack(side="left")
        self._s     = tk.IntVar(value=30)
        self._s_lbl = tk.Label(r1, text=" 30", bg=BG, fg=ACC,
                                font=("Menlo",11,"bold"), width=4)
        self._s_lbl.pack(side="left")
        tk.Scale(r1, from_=0, to=100, orient="horizontal",
                 variable=self._s, length=177, bd=0,
                 bg=BG, fg=FG, highlightthickness=0,
                 troughcolor="#222", showvalue=False,
                 command=lambda v: self._s_lbl.config(text=f" {int(float(v))}")
                 ).pack(side="left", padx=(2,16))

        # ── A 슬라이더 (Adventure) ──
        tk.Label(r1, text="A=", bg=BG, fg=FG,
                 font=("Menlo",10)).pack(side="left")
        self._a     = tk.IntVar(value=40)
        self._a_lbl = tk.Label(r1, text=" 40", bg=BG, fg=ACC,
                                font=("Menlo",11,"bold"), width=4)
        self._a_lbl.pack(side="left")
        tk.Scale(r1, from_=0, to=100, orient="horizontal",
                 variable=self._a, length=177, bd=0,
                 bg=BG, fg=FG, highlightthickness=0,
                 troughcolor="#222", showvalue=False,
                 command=lambda v: self._a_lbl.config(text=f" {int(float(v))}")
                 ).pack(side="left", padx=(2,0))

        # ── 버튼 행 ──
        r2 = tk.Frame(self, bg=BG); r2.pack(fill="x", **PAD)
        self._ebtn = _make_btn(r2, text="▶  Execute", bg="#333", fg=ACC,
                               command=self._run)
        self._ebtn.pack(side="left", padx=(0,6))
        _make_btn(r2, text="🧪 Test (1곡)", bg="#222", fg=FG,
                  command=self._run_test).pack(side="left", padx=(0,6))
        _make_btn(r2, text="⏹ Stop", bg="#3d0000", fg="#ff6b6b",
                  command=self._stop_run).pack(side="left", padx=(0,6))
        _make_btn(r0, text="DOWN", bg="#222", fg=FG,
          command=self._pick_out).pack(side="left", padx=(10,4))

        self._out_lbl = tk.Label(r0, bg=BG, fg="#888", font=("Menlo",9),
                                width=14, anchor="e", cursor="hand2")
        self._out_lbl.bind("<Button-1>", lambda e: subprocess.run(["open", self._out_dir.get()]))
        self._update_out_lbl()
        self._out_lbl.pack(side="left")

    def _stop_run(self):
        self._stop = True
        self.log("\n⏹ 중단 요청됨...")

    def _pick_csv(self):
        p = filedialog.askopenfilename(filetypes=[("CSV","*.csv")], initialdir=HERE)
        if p: self._csv.set(p)

    def _pick_json(self):
        p = filedialog.askopenfilename(filetypes=[("JSON","*.json")], initialdir=HERE)
        if p: self._json.set(p)
        save_settings({"json": self._json.get(), "out": self._out_dir.get()})
    
    def _pick_out(self):
        p = filedialog.askdirectory(initialdir=HERE)
        if p:
            self._out_dir.set(p)
            self._update_out_lbl()
            save_settings({"json": self._json.get(), "out": self._out_dir.get()})

    def _update_out_lbl(self):
        full = self._out_dir.get()
        parts = full.split(os.sep)
        short = "…/" + "/".join(parts[-2:]) if len(parts) > 2 else full
        self._out_lbl.config(text=short)


    def log(self, msg):
        def _w():
            self._log_box.config(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.config(state="disabled")
        self.after(0, _w)

    def _clear_log(self):
        self._log_box.config(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.config(state="disabled")

    def _run(self):
        if self._running: return
        self._running = True
        threading.Thread(target=self._worker, args=(False,), daemon=True).start()

    def _run_test(self):
        if self._running: return
        self._running = True
        threading.Thread(target=self._worker, args=(True,), daemon=True).start()

    def _worker(self, test_mode):
        self._clear_log()
        try:
            self._work(test_mode)
        except Exception as e:
            self.log(f"\n💥 오류: {e}")
        finally:
            self._running = False

    def _work(self, test_mode):
        self._stop   = False
        csv_p        = self._csv.get()
        json_p       = self._json.get()
        similarity   = int(self._s.get())
        adventure    = int(self._a.get())
        out          = self._out_dir.get()
        os.makedirs(out, exist_ok=True)

        label = "🧪 TEST (1곡, JSON 미기록)" if test_mode else "▶ EXECUTE"
        self.log(f"{'─'*54}")
        self.log(f"  🏋️  MusicTerGYM  |  {label}")
        self.log(f"  S={similarity}  A={adventure}")
        self.log(f"{'─'*54}")

        # 1. CSV
        self.log(f"\n[1] CSV 로드...")
        tracks = load_csv(csv_p)
        self.log(f"    ✅ {len(tracks)}곡")
        if not tracks:
            self.log("    ❌ 트랙 없음."); return

        # 2. 이력
        self.log(f"\n[2] 이력 로드...")
        history      = load_history(json_p)
        history_keys = {h["key"] for h in history}
        self.log(f"    이전 기록: {len(history_keys)}곡 제외")

        # 3. Last.fm 추천
        self.log(f"\n[3] Last.fm 추천 수집")
        reco = get_reco(tracks, similarity, adventure, history_keys, self.log)
        if not reco:
            self.log("    ❌ 추천곡 없음."); return
        if test_mode:
            reco = reco[:1]

        # 4. 다운로드
        self.log(f"\n[4] 다운로드 시작 ({len(reco)}곡)")
        done = []
        for i, r in enumerate(reco, 1):
            if self._stop:
                self.log("\n⏹ 중단됨."); break
            self.log(f"\n  [{i}/{len(reco)}]")
            if download_track(r["artist"], r["name"], out, self.log):
                done.append(r)

        # 5. JSON
        if not test_mode and done:
            self.log(f"\n[5] JSON 이력 저장")
            from datetime import datetime
            # 날짜 구분선 먼저 추가
            today = datetime.now().strftime("%Y-%m-%d %H:%M")
            history.append({"key": f"──── {today} ────", "name": "", "artist": ""})

            for r in done:
                if r["key"] not in history_keys:
                    history.append({"key": r["key"], "name": r["name"],
                                    "artist": r["artist"]})
                    history_keys.add(r["key"])
            save_history(json_p, history)
            self.log(f"    ✅ {len(done)}곡 기록")

        self.log(f"\n{'─'*54}")
        self.log(f"  🎉 완료  {len(done)}/{len(reco)}곡 다운로드")
        self.log(f"  📁 {out}")
        self.log(f"{'─'*54}\n")


if __name__ == "__main__":
    App().mainloop()
