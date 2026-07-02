"""シンプルな GUI (Tkinter, 標準ライブラリのみ)。

MP4 と任意の GPX を選び、機種を選んで「GoPro化」ボタンを押すと注入する。
info / extract もタブで提供する。追加依存なし＝単体 exe 化しても軽い。
"""

from __future__ import annotations

import io
import os
import queue
import threading
import traceback

from . import gopro, klv, mp4, telemetry


def run() -> int:
    from .__main__ import (ensure_utf8_output, humanize_error, inject_file,
                           collect_videos, _default_output)
    ensure_utf8_output()
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as e:  # pragma: no cover
        print(f"Tkinter が利用できません: {e}")
        return 1

    app = tk.Tk()
    app.title("GPMF GoPro化ツール")
    app.geometry("640x560")
    app.minsize(560, 480)

    log_q: "queue.Queue[str]" = queue.Queue()

    def log(msg: str) -> None:
        log_q.put(msg)

    # ------------------------------------------------------------------
    # 状態
    # ------------------------------------------------------------------
    in_path = tk.StringVar()
    out_path = tk.StringVar()
    gpx_path = tk.StringVar()
    device = tk.StringVar(value=gopro.DEFAULT_PRESET)
    rate = tk.StringVar(value="10")
    fit = tk.BooleanVar(value=True)
    rename = tk.BooleanVar(value=True)
    gopro_ftyp = tk.BooleanVar(value=True)

    # ------------------------------------------------------------------
    # レイアウト
    # ------------------------------------------------------------------
    pad = {"padx": 8, "pady": 4}
    frm = ttk.Frame(app, padding=10)
    frm.pack(fill="both", expand=True)

    def _row(parent, label, var, browse=None, save=False):
        row = ttk.Frame(parent)
        row.pack(fill="x", **pad)
        ttk.Label(row, text=label, width=12).pack(side="left")
        ent = ttk.Entry(row, textvariable=var)
        ent.pack(side="left", fill="x", expand=True)
        if browse:
            ttk.Button(row, text="参照",
                       command=browse).pack(side="left", padx=4)
        return ent

    def pick_in():
        p = filedialog.askopenfilename(
            title="入力 MP4 を選択",
            filetypes=[("動画", "*.mp4 *.mov *.MP4 *.MOV *.360"), ("すべて", "*.*")])
        if p:
            in_path.set(p)
            if not out_path.get():
                base, ext = os.path.splitext(p)
                out_path.set(f"{base}_gopro{ext or '.mp4'}")

    def pick_out():
        p = filedialog.asksaveasfilename(
            title="出力 MP4", defaultextension=".mp4",
            filetypes=[("動画", "*.mp4")])
        if p:
            out_path.set(p)

    def pick_gpx():
        p = filedialog.askopenfilename(
            title="GPX を選択 (任意)",
            filetypes=[("GPX", "*.gpx *.GPX"), ("すべて", "*.*")])
        if p:
            gpx_path.set(p)

    ttk.Label(frm, text="他社カメラの動画を GoPro のメタデータ付きに変換します",
              font=("", 11, "bold")).pack(anchor="w", pady=(0, 6))

    _row(frm, "入力 MP4", in_path, pick_in)
    _row(frm, "出力 MP4", out_path, pick_out)
    _row(frm, "GPX (任意)", gpx_path, pick_gpx)

    opt = ttk.LabelFrame(frm, text="オプション", padding=8)
    opt.pack(fill="x", **pad)

    r1 = ttk.Frame(opt)
    r1.pack(fill="x", pady=2)
    ttk.Label(r1, text="機種", width=12).pack(side="left")
    ttk.Combobox(r1, textvariable=device, values=sorted(gopro.DEVICE_PRESETS),
                 state="readonly", width=12).pack(side="left")
    ttk.Label(r1, text="  GPS Hz").pack(side="left")
    ttk.Entry(r1, textvariable=rate, width=6).pack(side="left", padx=4)

    r2 = ttk.Frame(opt)
    r2.pack(fill="x", pady=2)
    ttk.Checkbutton(r2, text="GPXを動画長に合わせる", variable=fit).pack(side="left")
    ttk.Checkbutton(r2, text="handler名をGoPro化", variable=rename).pack(side="left")
    ttk.Checkbutton(r2, text="ftypをGoPro化", variable=gopro_ftyp).pack(side="left")

    # ボタン
    btns = ttk.Frame(frm)
    btns.pack(fill="x", **pad)
    run_btn = ttk.Button(btns, text="GoPro化を実行")
    run_btn.pack(side="left")
    batch_btn = ttk.Button(btns, text="複数ファイルを一括処理")
    batch_btn.pack(side="left", padx=6)
    info_btn = ttk.Button(btns, text="入力の情報を表示")
    info_btn.pack(side="left", padx=6)

    # ログ表示
    ttk.Label(frm, text="ログ").pack(anchor="w", **pad)
    log_box = tk.Text(frm, height=12, wrap="word", state="disabled")
    log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def flush_log():
        try:
            while True:
                msg = log_q.get_nowait()
                log_box.configure(state="normal")
                log_box.insert("end", msg + "\n")
                log_box.see("end")
                log_box.configure(state="disabled")
        except queue.Empty:
            pass
        app.after(100, flush_log)

    # ------------------------------------------------------------------
    # 処理
    # ------------------------------------------------------------------
    def set_running(active: bool):
        state = "disabled" if active else "normal"
        run_btn.configure(state=state)
        batch_btn.configure(state=state)
        info_btn.configure(state=state)

    def do_inject():
        src = in_path.get().strip()
        dst = out_path.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showerror("エラー", "入力 MP4 を選択してください")
            return
        if not dst:
            messagebox.showerror("エラー", "出力先を指定してください")
            return
        set_running(True)

        def work():
            try:
                try:
                    hz = float(rate.get())
                except ValueError:
                    hz = 10.0
                stats = inject_file(
                    src, dst, device.get(),
                    gpx=gpx_path.get().strip() or None,
                    rate=hz, fit=fit.get(),
                    handler_rename=rename.get(),
                    keep_ftyp=not gopro_ftyp.get(),
                    log=log)
                log(f"完了: {dst}")
                log(f"  機種={stats['device_name']} FW={stats['firmware']}")
                log(f"  ペイロード {stats['payload_count']} 個 / "
                    f"{stats['gpmf_bytes']} bytes")
                app.after(0, lambda: messagebox.showinfo(
                    "完了", f"GoPro化しました:\n{dst}"))
            except Exception as e:
                jp = humanize_error(e)
                log("エラー: " + jp)
                log(traceback.format_exc())
                app.after(0, lambda: messagebox.showerror("エラー", jp))
            finally:
                app.after(0, lambda: set_running(False))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------
    # 一括処理
    # ------------------------------------------------------------------
    def do_batch():
        paths = filedialog.askopenfilenames(
            title="一括処理する動画を複数選択 (Shift/⌘ で複数選択)",
            filetypes=[("動画", "*.mp4 *.mov *.m4v *.MP4 *.MOV *.360"),
                       ("すべて", "*.*")])
        if not paths:
            return
        out_dir = filedialog.askdirectory(title="出力先フォルダを選択")
        if not out_dir:
            return
        set_running(True)

        def work():
            try:
                hz = float(rate.get())
            except ValueError:
                hz = 10.0
            gpx = gpx_path.get().strip() or None
            try:
                files = collect_videos(list(paths))
            except Exception as e:
                log("エラー: " + humanize_error(e))
                app.after(0, lambda: set_running(False))
                return
            log(f"=== 一括処理: {len(files)} 本 ===")
            cache = {}
            ok = skip = fail = 0
            for i, path in enumerate(files, 1):
                name = os.path.basename(path)
                out_path = _default_output(path, out_dir)
                if os.path.exists(out_path):
                    log(f"[{i}/{len(files)}] {name}: スキップ (出力済み)")
                    skip += 1
                    continue
                try:
                    inject_file(path, out_path, device.get(), gpx=gpx,
                                rate=hz, fit=fit.get(),
                                handler_rename=rename.get(),
                                keep_ftyp=not gopro_ftyp.get(),
                                log=lambda m: None, gpx_cache=cache)
                    log(f"[{i}/{len(files)}] {name}: 完了")
                    ok += 1
                except Exception as e:
                    log(f"[{i}/{len(files)}] {name}: 失敗 ({humanize_error(e)})")
                    fail += 1
            log(f"=== おわり: 成功 {ok} / スキップ {skip} / 失敗 {fail} ===")
            app.after(0, lambda: messagebox.showinfo(
                "一括処理 完了",
                f"成功 {ok} / スキップ {skip} / 失敗 {fail}\n出力先: {out_dir}"))
            app.after(0, lambda: set_running(False))

        threading.Thread(target=work, daemon=True).start()

    def do_info():
        src = in_path.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showerror("エラー", "入力 MP4 を選択してください")
            return
        set_running(True)

        def work():
            try:
                buf = io.StringIO()
                import contextlib
                from .__main__ import cmd_info
                import argparse
                with contextlib.redirect_stdout(buf):
                    cmd_info(argparse.Namespace(file=src))
                log(buf.getvalue())
            except Exception as e:
                log("エラー: " + humanize_error(e))
            finally:
                app.after(0, lambda: set_running(False))

        threading.Thread(target=work, daemon=True).start()

    run_btn.configure(command=do_inject)
    batch_btn.configure(command=do_batch)
    info_btn.configure(command=do_info)

    flush_log()
    app.mainloop()
    return 0
