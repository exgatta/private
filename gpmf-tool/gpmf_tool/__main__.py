"""gpmf_tool CLI。

使い方:
    python -m gpmf_tool parse   <file.mp4|file.bin> [--json out.json]
    python -m gpmf_tool extract <in.mp4> [-o raw.bin] [--json out.json] [--gpx out.gpx]
    python -m gpmf_tool inject  <in.mp4> -o out.mp4 [--gpx track.gpx] [--device hero11] ...
    python -m gpmf_tool info    <file.mp4>
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from . import gopro, klv, mp4, telemetry


def ensure_utf8_output() -> None:
    """標準出力/エラーを UTF-8 に切り替える。

    Windows の既定コンソール (cp932/cp1252) だと日本語のヘルプや
    ダンプ出力で UnicodeEncodeError になるため、表示不能文字は
    置換しつつ UTF-8 で出す。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


# ---------------------------------------------------------------------------
# エラーメッセージの日本語化
# ---------------------------------------------------------------------------

# よくある OS エラー (errno) を分かりやすい日本語にする
_ERRNO_JA = {
    errno.ENOSPC: ("ディスクの空き容量が足りません。保存先の空き容量を確認してください"
                   "（出力ファイルは元動画とほぼ同じサイズが必要です）。"),
    errno.EACCES: ("アクセス権がありません。ファイルやフォルダの権限、"
                   "または書き込み先を確認してください。"),
    errno.EPERM: "操作が許可されていません。ファイルの権限を確認してください。",
    errno.ENOENT: "ファイルまたはフォルダが見つかりません。パスが正しいか確認してください。",
    errno.EISDIR: "フォルダが指定されています。ファイルを指定してください。",
    errno.ENOTDIR: "パスの一部がフォルダではありません。保存先のフォルダがあるか確認してください。",
    errno.EROFS: "書き込み禁止のドライブです。別の保存先を指定してください。",
    errno.ENAMETOOLONG: "ファイル名が長すぎます。",
    errno.EMFILE: "同時に開いているファイルが多すぎます。",
    errno.ENFILE: "システムが開けるファイル数の上限に達しました。",
    errno.EDQUOT: "ディスクの使用量制限に達しました。",
    errno.EEXIST: "同名のファイルが既に存在します。",
    errno.EBUSY: "ファイルが他のプログラムに使用中です。",
}


def humanize_error(e: BaseException) -> str:
    """例外を日本語のわかりやすい 1 行メッセージにする。"""
    if isinstance(e, (klv.GPMFError, mp4.MP4Error)):
        return str(e)
    if isinstance(e, OSError):
        target = getattr(e, "filename", None)
        suffix = f"（対象: {target}）" if target else ""
        base = _ERRNO_JA.get(e.errno)
        if base:
            return base + suffix
        detail = e.strerror or str(e)
        return f"入出力エラー: {detail}{suffix}"
    if isinstance(e, KeyboardInterrupt):
        return "処理を中断しました。"
    msg = str(e).strip()
    return msg if msg else e.__class__.__name__


def _err(msg: str) -> "sys.NoReturn":
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(1)


# argparse が出す英語メッセージ断片 → 日本語 (長い語句から先に置換する)
_ARGPARSE_REPLACEMENTS = [
    ("the following arguments are required:", "必須の引数が指定されていません:"),
    ("unrecognized arguments:", "認識できない引数:"),
    ("expected at least one argument", "引数が少なくとも1つ必要です"),
    ("expected one argument", "引数が1つ必要です"),
    ("not allowed with argument", "は次の引数と同時には指定できません:"),
    ("ambiguous option:", "あいまいなオプション:"),
    ("invalid choice:", "は不正な選択です:"),
    ("(choose from", "(選択肢:"),
    ("is required", "は必須です"),
    ("invalid", "不正な"),
    ("value:", "値:"),
    ("argument", "引数"),
]

# ヘルプ/使い方の見出しを日本語化
_ARGPARSE_SECTIONS = [
    ("usage:", "使い方:"),
    ("positional arguments:", "位置引数:"),
    ("options:", "オプション:"),
    ("optional arguments:", "オプション:"),
    ("show this help message and exit", "このヘルプを表示して終了する"),
    ("positional 引数:", "位置引数:"),  # 二重置換の保険
]


def _translate_argparse(text: str, table) -> str:
    for en, ja in table:
        text = text.replace(en, ja)
    return text


class JapaneseArgumentParser(argparse.ArgumentParser):
    """使い方・エラー・ヘルプをすべて日本語で表示する ArgumentParser。"""

    def error(self, message):  # noqa: D401
        msg = _translate_argparse(message, _ARGPARSE_REPLACEMENTS)
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: エラー: {msg}\n")

    def format_usage(self):
        return _translate_argparse(super().format_usage(), _ARGPARSE_SECTIONS)

    def format_help(self):
        return _translate_argparse(super().format_help(), _ARGPARSE_SECTIONS)


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> None:
    path = args.file
    payloads = []  # (time_sec, bytes)
    if path.lower().endswith((".mp4", ".mov", ".360")):
        with open(path, "rb") as f:
            samples = mp4.extract_gpmf_samples(f)
        payloads = [(s.time_sec, s.data) for s in samples]
        print(f"# {os.path.basename(path)}: gpmd サンプル {len(samples)} 個")
    else:
        with open(path, "rb") as f:
            payloads = [(0.0, f.read())]

    all_items = []
    for t, data in payloads:
        items = klv.parse(data, strict=not args.lenient)
        all_items.append({"time_sec": t, "items": klv.to_dict(items)})
        if not args.json:
            print(f"\n--- payload @ {t:.3f}s ({len(data)} bytes) ---")
            print(klv.dump(items, max_values=args.max_values))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(all_items, f, ensure_ascii=False, indent=2)
        print(f"JSON を書き出しました: {args.json}")


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def cmd_extract(args: argparse.Namespace) -> None:
    with open(args.file, "rb") as f:
        samples = mp4.extract_gpmf_samples(f)
    print(f"gpmd サンプル {len(samples)} 個 "
          f"({sum(len(s.data) for s in samples)} bytes) を抽出")

    if args.output:
        with open(args.output, "wb") as f:
            for s in samples:
                f.write(s.data)
        print(f"生 GPMF: {args.output}")

    if args.json or args.gpx:
        parsed = [(s.time_sec, klv.parse(s.data, strict=False)) for s in samples]
        if args.json:
            data = [{"time_sec": t, "items": klv.to_dict(items)}
                    for t, items in parsed]
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"JSON: {args.json}")
        if args.gpx:
            points = telemetry.extract_gps_points(parsed)
            if not points:
                print("警告: GPS ストリーム (GPS5/GPS9) が見つかりません",
                      file=sys.stderr)
            else:
                telemetry.write_gpx(args.gpx, points)
                print(f"GPX: {args.gpx} ({len(points)} 点)")


# ---------------------------------------------------------------------------
# inject (共通処理)
# ---------------------------------------------------------------------------

# 一括処理で対象にする動画拡張子
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".360")


def inject_file(input_path: str, output_path: str, device: str,
                gpx: str = None, rate: float = 10.0, fit: bool = True,
                device_name: str = None, firmware: str = None,
                serial_seed: str = None, handler_rename: bool = True,
                keep_ftyp: bool = False, log=lambda m: None,
                gpx_cache: dict = None) -> dict:
    """1 本の MP4 に GPMF を注入する共通関数 (CLI/GUI/一括処理から呼ぶ)。

    gpx_cache: 同じ GPX を使い回す一括処理用の {path: (points, start)} キャッシュ。
    """
    preset = gopro.DEVICE_PRESETS.get(device)
    if preset is None:
        raise klv.GPMFError(
            f"未知のデバイス: {device} (選択肢: {', '.join(gopro.DEVICE_PRESETS)})")
    dname = device_name or preset.device_name

    with open(input_path, "rb") as f:
        duration = mp4.movie_duration_seconds(f)
    log(f"動画の長さ: {duration:.2f} 秒")

    start_time = None
    if gpx:
        if gpx_cache is not None and gpx in gpx_cache:
            points, start_time = gpx_cache[gpx]
        else:
            points, start_time = telemetry.load_gpx(gpx)
            if gpx_cache is not None:
                gpx_cache[gpx] = (points, start_time)
        resampled = telemetry.resample_track(points, duration, rate_hz=rate,
                                             fit_duration=fit)
        payloads, durations = telemetry.build_payloads(
            resampled, duration, dname, start_time)
        log(f"GPS5 を {rate:g} Hz で {len(resampled)} サンプル生成")
    else:
        payloads, durations = telemetry.build_device_only_payloads(
            duration, dname)
        log("GPX 指定なし: デバイス情報のみの GPMF を生成")

    udta = gopro.build_udta_boxes(
        preset,
        serial_seed=serial_seed or os.path.basename(input_path),
        firmware=firmware, device_name=dname)
    renames = gopro.HANDLER_RENAMES if handler_rename else None
    new_ftyp = None if keep_ftyp else mp4.build_ftyp_gopro()

    with open(input_path, "rb") as src, open(output_path, "wb") as dst:
        stats = mp4.inject_gpmf_track(
            src, dst, payloads=payloads, payload_durations_ms=durations,
            udta_extra=udta, new_ftyp=new_ftyp, handler_renames=renames)
    stats["duration"] = duration
    stats["device_name"] = dname
    stats["firmware"] = firmware or preset.firmware
    return stats


def _default_output(input_path: str, out_dir: str = None) -> str:
    """入力パスから出力パス (<stem>_gopro<ext>) を決める。"""
    base = os.path.basename(input_path)
    stem, ext = os.path.splitext(base)
    if not ext:
        ext = ".mp4"
    name = f"{stem}_gopro{ext}"
    return os.path.join(out_dir or os.path.dirname(input_path) or ".", name)


def cmd_inject(args: argparse.Namespace) -> None:
    stats = inject_file(
        args.file, args.output, args.device,
        gpx=args.gpx, rate=args.rate, fit=not args.no_fit,
        device_name=args.device_name, firmware=args.firmware,
        serial_seed=args.serial_seed,
        handler_rename=not args.no_handler_rename, keep_ftyp=args.keep_ftyp,
        log=print)
    print(f"完了: {args.output}")
    print(f"  gpmd トラック ID: {stats['track_id']}")
    print(f"  ペイロード: {stats['payload_count']} 個 / {stats['gpmf_bytes']} bytes")
    print(f"  機種: {stats['device_name']} / FW: {stats['firmware']}")
    if stats["renamed_handlers"]:
        for h, name in stats["renamed_handlers"]:
            print(f"  hdlr 変更: {h} -> {name!r}")


# ---------------------------------------------------------------------------
# batch (一括処理)
# ---------------------------------------------------------------------------

def collect_videos(paths, recursive: bool = False) -> list:
    """ファイル/フォルダのリストから動画ファイルを集める (出力物 _gopro は除外)。"""
    out = []
    for p in paths:
        if os.path.isdir(p):
            if recursive:
                walker = (os.path.join(r, f)
                          for r, _, fs in os.walk(p) for f in fs)
            else:
                walker = (os.path.join(p, f) for f in sorted(os.listdir(p)))
            for f in walker:
                if (os.path.isfile(f)
                        and f.lower().endswith(VIDEO_EXTS)
                        and not os.path.splitext(f)[0].endswith("_gopro")):
                    out.append(f)
        elif os.path.isfile(p):
            out.append(p)
        else:
            raise FileNotFoundError(p)
    # 重複を除いて順序維持
    seen, uniq = set(), []
    for f in out:
        rp = os.path.realpath(f)
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    return uniq


def cmd_batch(args: argparse.Namespace) -> None:
    files = collect_videos(args.inputs, recursive=args.recursive)
    if not files:
        _err("処理対象の動画が見つかりません "
             f"(対象拡張子: {', '.join(VIDEO_EXTS)})")

    out_dir = args.output_dir
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"一括処理: {len(files)} 本の動画を GoPro 化します")
    if args.gpx:
        print(f"  全ファイルに GPX を適用: {args.gpx}")
    print("")

    gpx_cache: dict = {}
    ok = skipped = failed = 0
    for i, path in enumerate(files, 1):
        out_path = _default_output(path, out_dir)
        label = f"[{i}/{len(files)}] {os.path.basename(path)}"
        if os.path.realpath(out_path) == os.path.realpath(path):
            print(f"{label}: スキップ (入力と出力が同じ)")
            skipped += 1
            continue
        if os.path.exists(out_path) and not args.overwrite:
            print(f"{label}: スキップ (出力済み。上書きは --overwrite)")
            skipped += 1
            continue
        try:
            stats = inject_file(
                path, out_path, args.device,
                gpx=args.gpx, rate=args.rate, fit=not args.no_fit,
                device_name=args.device_name, firmware=args.firmware,
                handler_rename=not args.no_handler_rename,
                keep_ftyp=args.keep_ftyp,
                log=lambda m: None, gpx_cache=gpx_cache)
            print(f"{label}: 完了 -> {os.path.basename(out_path)} "
                  f"({stats['duration']:.0f}秒)")
            ok += 1
        except (klv.GPMFError, mp4.MP4Error) as e:
            print(f"{label}: スキップ ({humanize_error(e)})")
            skipped += 1
        except Exception as e:
            print(f"{label}: 失敗 ({humanize_error(e)})")
            failed += 1
            if os.environ.get("GPMF_DEBUG"):
                raise

    print("")
    print(f"一括処理おわり: 成功 {ok} / スキップ {skipped} / 失敗 {failed}")
    if out_dir:
        print(f"出力先: {out_dir}")
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

def cmd_info(args: argparse.Namespace) -> None:
    with open(args.file, "rb") as f:
        tops = mp4.scan_top_level(f)
        print("トップレベルボックス:")
        for b in tops:
            print(f"  {b.type.decode('latin-1'):6s} offset={b.offset:<12} size={b.size}")

        moov_top = next(b for b in tops if b.type == b"moov")
        moov = mp4.parse_box_tree(mp4.read_box_bytes(f, moov_top), b"moov")
        mvhd = mp4.parse_mvhd(moov.find(b"mvhd").payload)
        print(f"\n長さ: {mvhd['duration'] / mvhd['timescale']:.2f} 秒 "
              f"(timescale={mvhd['timescale']})")

        print("\nトラック:")
        for i, trak in enumerate(moov.find_all(b"trak"), 1):
            hdlr = trak.find(b"mdia", b"hdlr")
            info = mp4.parse_hdlr(hdlr.payload) if hdlr else {}
            handler = info.get("handler", b"????").decode("latin-1")
            print(f"  #{i} handler={handler} name={info.get('name', '')!r}")

        gpmd = mp4.find_gpmd_trak(moov)
        udta = moov.find(b"udta")
        gopro_boxes = ([c.type.decode('latin-1') for c in udta.children
                        if c.type in (b"FIRM", b"LENS", b"CAME", b"MUID",
                                      b"GPMF", b"HMMT", b"SETT")]
                       if udta else [])
        print(f"\ngpmd トラック: {'あり' if gpmd else 'なし'}")
        print(f"GoPro udta ボックス: {', '.join(gopro_boxes) if gopro_boxes else 'なし'}")
        if udta:
            for c in udta.children:
                if c.type == b"FIRM":
                    print(f"  FIRM: {c.payload.decode('ascii', 'replace')}")


# ---------------------------------------------------------------------------

def main(argv=None) -> None:
    ensure_utf8_output()
    ap = JapaneseArgumentParser(
        prog="gpmf",
        description="GPMF (GoPro Metadata Format) パーサ / MP4 注入ツール",
        add_help=False)
    ap.add_argument("-h", "--help", action="help",
                    help="このヘルプを表示して終了する")
    sub = ap.add_subparsers(dest="command", metavar="コマンド", required=True)

    p = sub.add_parser("parse", help="GPMF を人間可読形式でダンプ")
    p.add_argument("file", help="MP4 または生 GPMF バイナリ")
    p.add_argument("--json", help="JSON 出力先")
    p.add_argument("--lenient", action="store_true",
                   help="壊れた要素をスキップして続行")
    p.add_argument("--max-values", type=int, default=6,
                   help="1 要素あたりの表示サンプル数 (default: 6)")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("extract", help="MP4 から GPMF を抽出")
    p.add_argument("file", help="入力 MP4")
    p.add_argument("-o", "--output", help="生 GPMF バイナリ出力先")
    p.add_argument("--json", help="JSON 出力先")
    p.add_argument("--gpx", help="GPX 出力先 (GPS5/GPS9 ストリームから)")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("inject",
                       help="MP4 に GPMF トラック + GoPro 識別情報を注入")
    p.add_argument("file", help="入力 MP4 (他社カメラの動画)")
    p.add_argument("-o", "--output", required=True, help="出力 MP4")
    p.add_argument("--gpx", help="GPS テレメトリの元になる GPX ファイル")
    p.add_argument("--device", default=gopro.DEFAULT_PRESET,
                   choices=sorted(gopro.DEVICE_PRESETS),
                   help=f"機種プリセット (default: {gopro.DEFAULT_PRESET})")
    p.add_argument("--device-name", help="DVNM に入れるデバイス名の上書き")
    p.add_argument("--firmware", help="FIRM に入れる FW バージョンの上書き")
    p.add_argument("--serial-seed",
                   help="シリアル番号生成用シード (default: ファイル名)")
    p.add_argument("--rate", type=float, default=10.0,
                   help="GPS サンプリングレート Hz (default: 10 = GoPro 実機相当)")
    p.add_argument("--no-fit", action="store_true",
                   help="GPX の時間を動画長に合わせて伸縮しない")
    p.add_argument("--no-handler-rename", action="store_true",
                   help="既存トラックの hdlr 名を GoPro 風に変更しない")
    p.add_argument("--keep-ftyp", action="store_true",
                   help="ftyp を GoPro 風 (mp41) に置換しない")
    p.set_defaults(func=cmd_inject)

    p = sub.add_parser("batch",
                       help="複数の MP4 をまとめて GoPro 化 (フォルダ指定可)")
    p.add_argument("inputs", nargs="+",
                   help="入力の動画ファイルまたはフォルダ (複数指定可)")
    p.add_argument("-o", "--output-dir",
                   help="出力フォルダ (省略時は各入力と同じ場所に <名前>_gopro.mp4)")
    p.add_argument("--gpx", help="全ファイルに適用する GPX (任意)")
    p.add_argument("--device", default=gopro.DEFAULT_PRESET,
                   choices=sorted(gopro.DEVICE_PRESETS),
                   help=f"機種プリセット (default: {gopro.DEFAULT_PRESET})")
    p.add_argument("--device-name", help="デバイス名の上書き")
    p.add_argument("--firmware", help="FW バージョンの上書き")
    p.add_argument("--rate", type=float, default=10.0,
                   help="GPS サンプリングレート Hz (default: 10)")
    p.add_argument("--no-fit", action="store_true",
                   help="GPX の時間を動画長に合わせて伸縮しない")
    p.add_argument("--no-handler-rename", action="store_true",
                   help="既存トラックの hdlr 名を GoPro 風に変更しない")
    p.add_argument("--keep-ftyp", action="store_true",
                   help="ftyp を GoPro 風 (mp41) に置換しない")
    p.add_argument("--recursive", action="store_true",
                   help="フォルダを再帰的に探索する")
    p.add_argument("--overwrite", action="store_true",
                   help="既存の出力ファイルを上書きする")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("info", help="MP4 の構造と GoPro メタデータ状況を表示")
    p.add_argument("file", help="入力 MP4")
    p.set_defaults(func=cmd_info)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except BrokenPipeError:
        # `| head` などでの中断は正常終了扱い
        try:
            sys.stdout.close()
        except OSError:
            pass
        sys.exit(0)
    except KeyboardInterrupt:
        _err("処理を中断しました。")
    except (klv.GPMFError, mp4.MP4Error, OSError) as e:
        _err(humanize_error(e))
    except Exception as e:  # 想定外も日本語で表示 (詳細は GPMF_DEBUG=1)
        if os.environ.get("GPMF_DEBUG"):
            raise
        _err(f"予期しないエラーが発生しました: {humanize_error(e)}\n"
             f"（詳しい情報を見るには環境変数 GPMF_DEBUG=1 を付けて再実行）")


if __name__ == "__main__":
    main()
