"""gpmf_tool CLI。

使い方:
    python -m gpmf_tool parse   <file.mp4|file.bin> [--json out.json]
    python -m gpmf_tool extract <in.mp4> [-o raw.bin] [--json out.json] [--gpx out.gpx]
    python -m gpmf_tool inject  <in.mp4> -o out.mp4 [--gpx track.gpx] [--device hero11] ...
    python -m gpmf_tool info    <file.mp4>
"""

from __future__ import annotations

import argparse
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


def _err(msg: str) -> "sys.NoReturn":
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(1)


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
# inject
# ---------------------------------------------------------------------------

def cmd_inject(args: argparse.Namespace) -> None:
    preset = gopro.DEVICE_PRESETS.get(args.device)
    if preset is None:
        _err(f"未知のデバイス: {args.device} "
             f"(選択肢: {', '.join(gopro.DEVICE_PRESETS)})")
    device_name = args.device_name or preset.device_name

    with open(args.file, "rb") as f:
        duration = mp4.movie_duration_seconds(f)
    print(f"動画の長さ: {duration:.2f} 秒")

    start_time = None
    if args.gpx:
        points, start_time = telemetry.load_gpx(args.gpx)
        print(f"GPX: {len(points)} 点 "
              f"({points[-1].time - points[0].time:.1f} 秒) を読み込み")
        resampled = telemetry.resample_track(points, duration,
                                             rate_hz=args.rate,
                                             fit_duration=not args.no_fit)
        payloads, durations = telemetry.build_payloads(
            resampled, duration, device_name, start_time)
        print(f"GPS5 を {args.rate:g} Hz で {len(resampled)} サンプル生成")
    else:
        payloads, durations = telemetry.build_device_only_payloads(
            duration, device_name)
        print("GPX 指定なし: デバイス情報のみの GPMF を生成 "
              "(GPS を入れるには --gpx を指定)")

    udta = gopro.build_udta_boxes(
        preset,
        serial_seed=args.serial_seed or os.path.basename(args.file),
        firmware=args.firmware,
        device_name=device_name,
    )
    renames = None if args.no_handler_rename else gopro.HANDLER_RENAMES
    new_ftyp = None if args.keep_ftyp else mp4.build_ftyp_gopro()

    with open(args.file, "rb") as src, open(args.output, "wb") as dst:
        stats = mp4.inject_gpmf_track(
            src, dst,
            payloads=payloads,
            payload_durations_ms=durations,
            udta_extra=udta,
            new_ftyp=new_ftyp,
            handler_renames=renames,
        )

    print(f"完了: {args.output}")
    print(f"  gpmd トラック ID: {stats['track_id']}")
    print(f"  ペイロード: {stats['payload_count']} 個 / {stats['gpmf_bytes']} bytes")
    print(f"  機種: {device_name} / FW: {args.firmware or preset.firmware}")
    if stats["renamed_handlers"]:
        for h, name in stats["renamed_handlers"]:
            print(f"  hdlr 変更: {h} -> {name!r}")


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
    ap = argparse.ArgumentParser(
        prog="gpmf_tool",
        description="GPMF (GoPro Metadata Format) パーサ / MP4 注入ツール")
    sub = ap.add_subparsers(dest="command", required=True)

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

    p = sub.add_parser("info", help="MP4 の構造と GoPro メタデータ状況を表示")
    p.add_argument("file", help="入力 MP4")
    p.set_defaults(func=cmd_info)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except (klv.GPMFError, mp4.MP4Error, FileNotFoundError) as e:
        _err(str(e))
    except BrokenPipeError:
        # `| head` などでの中断は正常終了扱い
        try:
            sys.stdout.close()
        except OSError:
            pass
        sys.exit(0)


if __name__ == "__main__":
    main()
