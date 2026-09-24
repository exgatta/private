"""GPMF KLV パーサ/ライタのラウンドトリップテスト。"""

import struct
import unittest

from gpmf_tool import klv


class TestKLVRoundtrip(unittest.TestCase):

    def _roundtrip(self, key, type_char, values, struct_count=1):
        data = klv.make_item(key, type_char, values, struct_count)
        self.assertEqual(len(data) % 4, 0, "4 バイトアラインされていない")
        items = klv.parse(data)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.key, key)
        self.assertEqual(item.type_char, type_char)
        return item

    def test_integer_types(self):
        for tc, vals in [("b", [-5, 127]), ("B", [0, 255]),
                         ("s", [-30000, 42]), ("S", [65535, 0]),
                         ("l", [-2000000000, 7]), ("L", [4000000000, 1]),
                         ("j", [-(2**60), 5]), ("J", [2**63, 9])]:
            item = self._roundtrip("TSTA", tc, vals)
            self.assertEqual(item.values, vals, f"型 {tc}")

    def test_float_types(self):
        item = self._roundtrip("TSTB", "f", [1.5, -2.25])
        self.assertEqual(item.values, [1.5, -2.25])
        item = self._roundtrip("TSTC", "d", [3.141592653589793])
        self.assertEqual(item.values, [3.141592653589793])

    def test_fixed_point(self):
        item = self._roundtrip("TSTD", "q", [1.5, -0.25])
        self.assertEqual(item.values, [1.5, -0.25])
        item = self._roundtrip("TSTE", "Q", [2.5])
        self.assertEqual(item.values, [2.5])

    def test_string_and_fourcc(self):
        item = self._roundtrip("STNM", "c", "GPS (Lat., Long.)")
        self.assertEqual(item.values, ["GPS (Lat., Long.)"])
        item = self._roundtrip("SIUN", "c", ["deg", "deg", "m", "m/s"])
        self.assertEqual(item.values, ["deg", "deg", "m", "m/s"])
        item = self._roundtrip("GPSA", "F", "MSLV")
        self.assertEqual(item.values, ["MSLV"])

    def test_utc(self):
        item = self._roundtrip("GPSU", "U", "240102123456.789")
        self.assertEqual(item.values, ["240102123456.789"])
        dt = klv.gpsu_to_datetime(item.values[0])
        self.assertEqual(dt.year, 2024)
        self.assertEqual(dt.month, 1)
        self.assertEqual(klv.datetime_to_gpsu(dt), "240102123456.789")

    def test_multi_element_samples(self):
        samples = [(379460123, 1394386000, 12345, 1500, 155),
                   (379460456, 1394386222, 12400, 1600, 165)]
        item = self._roundtrip("GPS5", "l", samples, struct_count=5)
        self.assertEqual(item.values, samples)
        self.assertEqual(item.struct_size, 20)
        self.assertEqual(item.repeat, 2)

    def test_nested(self):
        inner = klv.make_item("DVID", "L", 1)
        inner += klv.make_item("DVNM", "c", "HERO9 Black")
        strm = klv.make_item("SCAL", "l", [(10,)], struct_count=1)
        inner += klv.make_nested("STRM", strm)
        devc = klv.make_nested("DEVC", inner)

        items = klv.parse(devc)
        self.assertEqual(len(items), 1)
        root = items[0]
        self.assertTrue(root.is_nested)
        self.assertEqual(root.key, "DEVC")
        self.assertEqual(root.find_first("DVNM").value(), "HERO9 Black")
        self.assertEqual(root.find_first("SCAL").value(), 10)

    def test_complex_type(self):
        # TYPE "lL" で定義された複合型 '?' を手組みしてパース
        type_item = klv.make_item("TYPE", "c", "lL")
        body = struct.pack(">iI", -5, 7) + struct.pack(">iI", 9, 11)
        header = b"FACE" + bytes([ord("?"), 8]) + struct.pack(">H", 2)
        data = type_item + header + body
        items = klv.parse(data)
        face = items[1]
        self.assertEqual(face.values, [(-5, 7), (9, 11)])

    def test_type_def_expansion(self):
        self.assertEqual(klv.expand_type_def("lL"), ["l", "L"])
        self.assertEqual(klv.expand_type_def("f[3]S"), ["f", "f", "f", "S"])
        self.assertEqual(klv.complex_struct_size("lLf[2]"), 16)

    def test_lenient_parse_skips_garbage(self):
        good = klv.make_item("DVID", "L", 1)
        bad = b"BADD" + bytes([0xEE, 4]) + struct.pack(">H", 1) + b"\x00" * 4
        items = klv.parse(bad + good, strict=False)
        self.assertEqual([i.key for i in items], ["DVID"])
        with self.assertRaises(klv.GPMFError):
            klv.parse(bad + good, strict=True)

    def test_dump_and_to_dict(self):
        devc = klv.make_nested("DEVC", klv.make_item("DVNM", "c", "Test"))
        items = klv.parse(devc)
        text = klv.dump(items)
        self.assertIn("DEVC", text)
        self.assertIn("DVNM", text)
        d = klv.to_dict(items)
        self.assertEqual(d[0]["key"], "DEVC")
        self.assertEqual(d[0]["children"][0]["values"], ["Test"])


if __name__ == "__main__":
    unittest.main()
