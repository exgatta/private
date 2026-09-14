"""結合対象を選ぶエクスプローラー風の画面。

フォルダを指定すると中身を精査し、「強制分割された一連の撮影」ごとに
まとめてツリー表示する。Windows のエクスプローラー (詳細表示) に寄せて、
名前・サイズ・長さ・解像度・撮影日時の列を並べ、サムネイルも出す。
チェックで結合に含めるファイルを取捨選択できる。
"""

from __future__ import annotations

import os
import queue
import threading
from typing import List, Optional

from . import browse, thumbs

CHECKED = "☑"
UNCHECKED = "☐"

# Windows エクスプローラー風の配色
BG = "#ffffff"
ALT_BG = "#f7f9fc"
GROUP_BG = "#eaf1fb"
SEL_BG = "#cce4f7"
BORDER = "#d9d9d9"
HEADER_BG = "#f0f0f0"


class BrowserWindow:
    """結合対象を選ぶウィンドウ (Toplevel)。"""

    def __init__(self, parent, tk, ttk, filedialog, messagebox,
                 on_join, default_device: str = "max",
                 initial_dir: Optional[str] = None):
        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.on_join = on_join          # (groups, gopro, out_dir) -> None
        self.groups: List[browse.Group] = []
        self.item_map = {}              # treeview item id -> FileEntry
        self.group_map = {}             # treeview item id -> Group
        self._images = {}               # 参照保持 (GC 防止)
        self._q: "queue.Queue" = queue.Queue()

        win = tk.Toplevel(parent)
        self.win = win
        win.title("結合するファイルを選ぶ")
        win.geometry("1080x680")
        win.minsize(820, 520)
        win.transient(parent)

        self._build_toolbar(initial_dir)
        self._build_tree()
        self._build_statusbar()
        self._pump()

    # ------------------------------------------------------------------
    # 画面の組み立て
    # ------------------------------------------------------------------
    def _build_toolbar(self, initial_dir):
        tk, ttk = self.tk, self.ttk
        bar = ttk.Frame(self.win, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Label(bar, text="フォルダ:").pack(side="left")
        self.folder_var = tk.StringVar(value=initial_dir or "")
        ent = ttk.Entry(bar, textvariable=self.folder_var)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(bar, text="参照...", command=self._pick_folder
                   ).pack(side="left")
        ttk.Button(bar, text="再スキャン", command=self.rescan
                   ).pack(side="left", padx=(6, 0))

        opt = ttk.Frame(self.win, padding=(10, 0))
        opt.pack(fill="x")
        self.show_solo = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="単独の動画も表示",
                        variable=self.show_solo,
                        command=self._refresh_tree).pack(side="left")
        self.show_thumbs = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="サムネイルを表示",
                        variable=self.show_thumbs,
                        command=self._toggle_thumbs).pack(side="left", padx=10)
        ttk.Button(opt, text="すべて選択",
                   command=lambda: self._set_all(True)).pack(side="right")
        ttk.Button(opt, text="すべて解除",
                   command=lambda: self._set_all(False)
                   ).pack(side="right", padx=6)

    def _build_tree(self):
        tk, ttk = self.tk, self.ttk
        wrap = ttk.Frame(self.win, padding=(10, 8))
        wrap.pack(fill="both", expand=True)

        # OS ネイティブのテーマは変えず、この一覧用のスタイルだけ定義する
        self.style = ttk.Style()
        self._apply_row_height()
        self.style.configure("Explorer.Treeview.Heading",
                             background=HEADER_BG, relief="flat",
                             font=("", 10))
        self.style.map("Explorer.Treeview",
                       background=[("selected", SEL_BG)],
                       foreground=[("selected", "#000000")])

        cols = ("check", "size", "duration", "res", "created", "kind")
        tree = ttk.Treeview(wrap, columns=cols, style="Explorer.Treeview",
                            selectmode="extended")
        self.tree = tree
        tree.heading("#0", text="名前", anchor="w")
        tree.heading("check", text="結合", anchor="center")
        tree.heading("size", text="サイズ", anchor="e")
        tree.heading("duration", text="長さ", anchor="e")
        tree.heading("res", text="解像度", anchor="center")
        tree.heading("created", text="撮影日時", anchor="center")
        tree.heading("kind", text="種類", anchor="center")
        tree.column("#0", width=380, minwidth=220, anchor="w")
        tree.column("check", width=54, anchor="center", stretch=False)
        tree.column("size", width=90, anchor="e", stretch=False)
        tree.column("duration", width=80, anchor="e", stretch=False)
        tree.column("res", width=110, anchor="center", stretch=False)
        tree.column("created", width=140, anchor="center", stretch=False)
        tree.column("kind", width=100, anchor="center", stretch=False)

        tree.tag_configure("group", background=GROUP_BG, font=("", 10, "bold"))
        tree.tag_configure("odd", background=ALT_BG)
        tree.tag_configure("even", background=BG)
        tree.tag_configure("error", foreground="#b00020")
        tree.tag_configure("off", foreground="#9a9a9a")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tree.bind("<Button-1>", self._on_click)
        tree.bind("<space>", self._on_space)
        tree.bind("<Double-1>", self._on_double)

    def _toggle_thumbs(self):
        self._apply_row_height()
        self._refresh_tree()

    def _apply_row_height(self):
        """サムネイル表示の有無で行の高さを変える。"""
        h = 76 if self.show_thumbs.get() else 24
        self.style.configure("Explorer.Treeview",
                             background=BG, fieldbackground=BG,
                             rowheight=h, borderwidth=1, relief="solid")

    def _build_statusbar(self):
        ttk = self.ttk
        bar = ttk.Frame(self.win, padding=(10, 8))
        bar.pack(fill="x")
        self.status = ttk.Label(bar, text="フォルダを選んでください")
        self.status.pack(side="left")

        self.join_gopro_btn = ttk.Button(
            bar, text="結合して GoPro 化", command=lambda: self._join(True))
        self.join_gopro_btn.pack(side="right")
        self.join_btn = ttk.Button(bar, text="結合する",
                                   command=lambda: self._join(False))
        self.join_btn.pack(side="right", padx=6)
        ttk.Button(bar, text="閉じる", command=self.win.destroy
                   ).pack(side="right", padx=6)

    # ------------------------------------------------------------------
    # スキャン
    # ------------------------------------------------------------------
    def _pick_folder(self):
        d = self.filedialog.askdirectory(title="動画の入ったフォルダを選択",
                                         parent=self.win)
        if d:
            self.folder_var.set(d)
            self.rescan()

    def rescan(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            self.messagebox.showerror("エラー", "フォルダを選んでください",
                                      parent=self.win)
            return
        self.status.configure(text="精査中...")
        self.tree.delete(*self.tree.get_children())
        self._images.clear()
        thumbs.clear_cache()

        def work():
            try:
                def prog(done, total, name):
                    self._q.put(("progress", (done, total, name)))
                groups = browse.scan_folder([folder], recursive=True,
                                            progress=prog)
                self._q.put(("done", groups))
            except Exception as e:
                self._q.put(("error", e))

        threading.Thread(target=work, daemon=True).start()

    def _pump(self):
        """バックグラウンドからの通知を処理する。"""
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "progress":
                    done, total, name = payload
                    self.status.configure(
                        text=f"精査中... {done}/{total}  {name}")
                elif kind == "done":
                    self.groups = payload
                    self._refresh_tree()
                elif kind == "error":
                    from .__main__ import humanize_error
                    self.status.configure(text="エラー")
                    self.messagebox.showerror(
                        "エラー", humanize_error(payload), parent=self.win)
                elif kind == "thumb":
                    item, photo = payload
                    if self.tree.exists(item):
                        self._images[item] = photo
                        self.tree.item(item, image=photo)
        except queue.Empty:
            pass
        self.win.after(80, self._pump)

    # ------------------------------------------------------------------
    # 一覧の描画
    # ------------------------------------------------------------------
    def _refresh_tree(self):
        tree = self.tree
        tree.delete(*tree.get_children())
        self.item_map.clear()
        self.group_map.clear()

        shown = 0
        for gi, g in enumerate(self.groups, 1):
            if not g.is_split and not self.show_solo.get():
                continue
            gid = tree.insert(
                "", "end", text=f"  {g.title}", open=True,
                values=("", browse.format_size(g.total_size),
                        browse.format_duration(g.total_duration),
                        "", "", "結合対象" if g.is_split else "単独"),
                tags=("group",))
            self.group_map[gid] = g
            for i, e in enumerate(g.entries):
                tags = ["odd" if i % 2 else "even"]
                if e.error:
                    tags.append("error")
                elif not e.selected:
                    tags.append("off")
                iid = tree.insert(
                    gid, "end", text="   " + e.name,
                    values=(CHECKED if e.selected else UNCHECKED,
                            e.size_text, e.duration_text,
                            e.resolution_text, e.created_text,
                            "読めません" if e.error else e.kind_text),
                    tags=tuple(tags))
                self.item_map[iid] = e
                shown += 1
                if self.show_thumbs.get():
                    self._load_thumb_async(iid, e.path)

        self._update_status()
        if not shown:
            self.status.configure(text="動画が見つかりませんでした")

    def _load_thumb_async(self, item, path):
        def work():
            data = thumbs.get_thumbnail(path)
            if not data:
                return
            photo = thumbs.make_photo_image(data, (128, 72))
            if photo is not None:
                self._q.put(("thumb", (item, photo)))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------
    # 取捨選択
    # ------------------------------------------------------------------
    def _toggle(self, item):
        entry = self.item_map.get(item)
        if entry is None or entry.error:
            return
        entry.selected = not entry.selected
        tags = [t for t in self.tree.item(item, "tags") if t != "off"]
        if not entry.selected:
            tags.append("off")
        self.tree.item(item, tags=tuple(tags))
        self.tree.set(item, "check", CHECKED if entry.selected else UNCHECKED)
        self._refresh_group_row(self.tree.parent(item))
        self._update_status()

    def _refresh_group_row(self, gid):
        g = self.group_map.get(gid)
        if g is None:
            return
        self.tree.item(gid, text=f"  {g.title}")
        self.tree.set(gid, "size", browse.format_size(g.total_size))
        self.tree.set(gid, "duration",
                      browse.format_duration(g.total_duration))

    def _on_click(self, event):
        tree = self.tree
        region = tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = tree.identify_column(event.x)
        item = tree.identify_row(event.y)
        if not item:
            return
        if item in self.group_map:
            # グループ行の「結合」列 → まとめて切り替え
            if col == "#1":
                g = self.group_map[item]
                new = not all(e.selected for e in g.entries if not e.error)
                for child in tree.get_children(item):
                    e = self.item_map.get(child)
                    if e and not e.error and e.selected != new:
                        self._toggle(child)
            return
        if col == "#1":
            self._toggle(item)

    def _on_space(self, event):
        for item in self.tree.selection():
            if item in self.item_map:
                self._toggle(item)
        return "break"

    def _on_double(self, event):
        """ダブルクリックで OS の既定アプリで開く (エクスプローラー風)。"""
        item = self.tree.identify_row(event.y)
        entry = self.item_map.get(item)
        if entry is None:
            return
        _open_in_os(entry.path)

    def _set_all(self, value: bool):
        for item, entry in self.item_map.items():
            if entry.error or entry.selected == value:
                continue
            self._toggle(item)

    # ------------------------------------------------------------------
    # 実行
    # ------------------------------------------------------------------
    def _update_status(self):
        targets = [g for g in self.groups
                   if g.is_split and len(g.selected_entries) >= 2]
        n_files = sum(len(g.selected_entries) for g in targets)
        total = sum(g.total_size for g in targets)
        if targets:
            self.status.configure(
                text=f"結合対象: {len(targets)} 件 / {n_files} ファイル / "
                     f"{browse.format_size(total)}  "
                     f"（出力に同容量の空きが必要）")
        else:
            self.status.configure(
                text=browse.summarize(self.groups)
                + " — 結合できる組がありません")
        state = "normal" if targets else "disabled"
        self.join_btn.configure(state=state)
        self.join_gopro_btn.configure(state=state)

    def _join(self, gopro: bool):
        targets = [g for g in self.groups
                   if g.is_split and len(g.selected_entries) >= 2]
        if not targets:
            self.messagebox.showinfo(
                "対象なし", "結合できる組がありません", parent=self.win)
            return
        out_dir = self.filedialog.askdirectory(
            title="結合後の保存先フォルダ", parent=self.win)
        if not out_dir:
            return
        self.win.destroy()
        self.on_join(targets, gopro, out_dir)


def _open_in_os(path: str) -> None:
    """OS の既定アプリでファイルを開く。"""
    import subprocess
    import sys
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
