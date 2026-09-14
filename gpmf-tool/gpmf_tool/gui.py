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

    # ドラッグ&ドロップ (tkinterdnd2 があれば有効。無ければボタン操作で代替)
    dnd_files = None
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        app = TkinterDnD.Tk()
        dnd_files = DND_FILES
    except Exception:
        app = tk.Tk()
    app.title("GPMF GoPro化ツール")
    app.geometry("660x620")
    app.minsize(560, 520)

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
    use_embedded = tk.BooleanVar(value=False)

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

    in_entry = _row(frm, "入力 MP4", in_path, pick_in)
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

    r3 = ttk.Frame(opt)
    r3.pack(fill="x", pady=2)
    ttk.Checkbutton(
        r3, text="動画に埋め込まれたGPSを使う (DJI/iPhone/Android/Sony)",
        variable=use_embedded).pack(side="left")

    # ボタン
    btns = ttk.Frame(frm)
    btns.pack(fill="x", **pad)
    run_btn = ttk.Button(btns, text="GoPro化を実行")
    run_btn.pack(side="left")
    batch_btn = ttk.Button(btns, text="複数ファイルを一括")
    batch_btn.pack(side="left", padx=6)
    folder_btn = ttk.Button(btns, text="フォルダを一括")
    folder_btn.pack(side="left", padx=6)
    info_btn = ttk.Button(btns, text="入力の情報を表示")
    info_btn.pack(side="left", padx=6)

    # 結合ボタン (分割された動画を1本に)
    btns2 = ttk.Frame(frm)
    btns2.pack(fill="x", **pad)
    join_btn = ttk.Button(btns2, text="フォルダから結合 (分割動画をまとめる)")
    join_btn.pack(side="left")
    ttk.Label(btns2,
              text="  ← フォルダを精査して一覧から選べます（画質そのまま）"
              ).pack(side="left")

    # ドラッグ&ドロップ案内
    drop_hint = ("↓ ここに動画やフォルダをドラッグ&ドロップでも一括処理できます"
                 if dnd_files else
                 "（ドラッグ&ドロップは未対応の環境です。上のボタンをお使いください）")
    drop_lbl = ttk.Label(frm, text=drop_hint, anchor="center",
                         relief="groove", padding=6)
    drop_lbl.pack(fill="x", **pad)

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
        for b in (run_btn, batch_btn, folder_btn, info_btn, join_btn):
            b.configure(state=state)

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
                    from_video=use_embedded.get(),
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
    def run_batch_paths(paths):
        """ファイル/フォルダの列を一括処理する (ボタン・D&D 共通)。"""
        if not paths:
            return
        try:
            files = collect_videos(list(paths), recursive=True)
        except Exception as e:
            messagebox.showerror("エラー", humanize_error(e))
            return
        if not files:
            messagebox.showinfo(
                "対象なし",
                "処理できる動画が見つかりませんでした。\n"
                "(.mp4 / .mov / .m4v / .360 が対象)")
            return
        out_dir = filedialog.askdirectory(
            title=f"{len(files)} 本の出力先フォルダを選択")
        if not out_dir:
            return
        set_running(True)

        def work():
            try:
                hz = float(rate.get())
            except ValueError:
                hz = 10.0
            gpx = gpx_path.get().strip() or None
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
                                from_video=use_embedded.get(),
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

    def do_batch():
        paths = filedialog.askopenfilenames(
            title="一括処理する動画を複数選択 (Shift/⌘ で複数選択)",
            filetypes=[("動画", "*.mp4 *.mov *.m4v *.MP4 *.MOV *.360"),
                       ("すべて", "*.*")])
        run_batch_paths(list(paths))

    def do_folder():
        d = filedialog.askdirectory(title="一括処理するフォルダを選択")
        if d:
            run_batch_paths([d])

    # ------------------------------------------------------------------
    # 分割動画の結合
    # ------------------------------------------------------------------
    def _run_join(groups, also_gopro, out_dir):
        """ブラウザ画面で選ばれた組を結合する。"""
        from . import concat
        set_running(True)

        def work():
            made = 0
            try:
                for gi, g in enumerate(groups, 1):
                    files = [e.path for e in g.selected_entries]
                    stem, ext = os.path.splitext(os.path.basename(files[0]))
                    stem = stem.rstrip("0123456789_-") or stem
                    suffix = "_結合_gopro" if also_gopro else "_結合"
                    out = os.path.join(out_dir, f"{stem}{suffix}{ext}")
                    log(f"--- [{gi}/{len(groups)}] {len(files)} 個を結合 ---")
                    try:
                        hz = float(rate.get())
                    except ValueError:
                        hz = 10.0
                    stats = concat.concat_files(
                        files, out, log=log,
                        gopro_device=device.get() if also_gopro else None,
                        gpx=(gpx_path.get().strip() or None) if also_gopro else None,
                        from_video=use_embedded.get() if also_gopro else False,
                        rate=hz)
                    d = stats["duration_sec"]
                    log(f"  完了: {out}")
                    log(f"    長さ {int(d // 60)}分{d % 60:.0f}秒 / "
                        f"{stats['bytes'] / 1024**3:.2f} GB")
                    if stats["shot_at"]:
                        log(f"    撮影日時: "
                            f"{stats['shot_at'].astimezone():%Y-%m-%d %H:%M:%S}")
                    made += 1
                app.after(0, lambda: messagebox.showinfo(
                    "結合 完了",
                    f"{made} 本のファイルを作成しました:\n{out_dir}"))
            except Exception as e:
                jp = humanize_error(e)
                log("エラー: " + jp)
                app.after(0, lambda: messagebox.showerror("エラー", jp))
            finally:
                app.after(0, lambda: set_running(False))

        threading.Thread(target=work, daemon=True).start()

    def do_join():
        """フォルダを精査し、結合対象を一覧から選ぶ画面を開く。"""
        from .browser_ui import BrowserWindow
        start = os.path.dirname(in_path.get().strip()) or None
        BrowserWindow(app, tk, ttk, filedialog, messagebox,
                      on_join=_run_join, default_device=device.get(),
                      initial_dir=start)

    def on_drop(event):
        # tkinterdnd2 は空白入りパスを {..} で囲むので splitlist で正しく分解
        try:
            paths = list(app.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]
        run_batch_paths(paths)

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
    folder_btn.configure(command=do_folder)
    join_btn.configure(command=do_join)
    info_btn.configure(command=do_info)

    # ドラッグ&ドロップ登録 (ウィンドウ全体とドロップ枠を対象に)
    if dnd_files is not None:
        for target in (drop_lbl, log_box, app):
            try:
                target.drop_target_register(dnd_files)
                target.dnd_bind("<<Drop>>", on_drop)
            except Exception:
                pass
        # 単発の入力欄には「ドロップで入力欄にセット」も許可
        def on_drop_single(event):
            try:
                paths = list(app.tk.splitlist(event.data))
            except Exception:
                paths = [event.data]
            files = [p for p in paths if os.path.isfile(p)]
            if len(files) == 1:
                in_path.set(files[0])
                if not out_path.get():
                    base, ext = os.path.splitext(files[0])
                    out_path.set(f"{base}_gopro{ext or '.mp4'}")
            else:
                on_drop(event)
        try:
            in_entry.drop_target_register(dnd_files)
            in_entry.dnd_bind("<<Drop>>", on_drop_single)
        except Exception:
            pass

    flush_log()
    app.mainloop()
    return 0
