"""Tests for zkn3_to_zettlr. They build small archives on the fly, so no test data is checked in.

Run from the repository root:  python3 -m unittest discover -s tests -v
"""
import csv
import re
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import zkn3_to_zettlr as z  # noqa: E402


def zettel(title, content="", created="", edited="", author="", keywords="", manlinks="", luhmann="",
           misc="", links=()):
    """One <zettel> element as XML text."""
    return (
        '<zettel zknid="x" ts_created="%s" ts_edited="%s"><title>%s</title><content>%s</content>'
        "<author>%s</author><keywords>%s</keywords><manlinks>%s</manlinks><links>%s</links>"
        "<misc>%s</misc><luhmann>%s</luhmann></zettel>"
        % (created, edited, title, content, author, keywords, manlinks,
           "".join("<link>%s</link>" % link for link in links), misc, luhmann)
    )


def make_archive(path, zettel_xml, keywords=(), authors=(), meta="<metainformation/>", extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        for member, xml in (extra or {}).items():
            archive.writestr(member, xml)
        archive.writestr("zknFile.xml", "<zettelkasten>%s</zettelkasten>" % "".join(zettel_xml))
        archive.writestr("keywordFile.xml", "<keywords>%s</keywords>" % "".join(
            '<entry f="1">%s</entry>' % k for k in keywords))
        archive.writestr("authorFile.xml", "<authors>%s</authors>" % "".join(
            '<entry f="1">%s</entry>' % a for a in authors))
        archive.writestr("metaInformation.xml", meta)


class ConverterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.src = self.root / "Test.zkn3"
        self.out = self.root / "out"
        # the converter prints a summary; keep it out of the test report
        quiet = redirect_stdout(StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def convert(self, *args, **kwargs):
        make_archive(self.src, *args, **kwargs)
        z.convert(str(self.src), str(self.out))

    def notes(self):
        return sorted(p for p in self.out.glob("*.md"))

    def mapping(self):
        with open(self.out / "_zuordnung.csv", encoding="utf-8", newline="") as f:
            return {int(r[0]): r[1] for r in list(csv.reader(f))[1:]}

    def read(self, old_number):
        return (self.out / (self.mapping()[old_number] + ".md")).read_text(encoding="utf-8")

    # --- IDs and file names -------------------------------------------------------------------

    def test_file_names_are_unique_14_digit_ids_from_the_creation_date(self):
        self.convert([zettel("A", created="0504141353"), zettel("B", created="1301011200")])
        self.assertEqual([p.stem for p in self.notes()], ["20050414135300", "20130101120000"])

    def test_notes_from_the_same_minute_get_consecutive_seconds(self):
        self.convert([zettel(t, created="1301011200") for t in "ABC"])
        self.assertEqual([p.stem for p in self.notes()],
                         ["20130101120000", "20130101120001", "20130101120002"])

    def test_note_without_a_date_follows_its_predecessor(self):
        self.convert([zettel("A", created="1301011200"), zettel("B", created="")])
        self.assertEqual(self.mapping(), {1: "20130101120000", 2: "20130101120001"})

    def test_file_date_is_the_creation_date_so_sorting_by_time_matches_the_ids(self):
        self.convert([zettel("Neu", created="1301011300", edited="2001011200"),
                      zettel("Alt", created="0501011200", edited="1501011200")])
        by_mtime = [p.name for p in sorted(self.notes(), key=lambda p: p.stat().st_mtime)]
        self.assertEqual(by_mtime, [p.name for p in self.notes()])

    def test_mapping_file_translates_old_numbers(self):
        self.convert([zettel("Eins", created="1301011200"), zettel("Zwei", created="1301011201")])
        with open(self.out / "_zuordnung.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["alte_nummer", "id", "titel"])
        self.assertEqual(rows[1:], [["1", "20130101120000", "Eins"], ["2", "20130101120100", "Zwei"]])

    # --- note layout --------------------------------------------------------------------------

    def test_title_is_the_first_heading_and_there_is_no_frontmatter(self):
        self.convert([zettel("Mein Titel", "Text", created="1301011200")])
        text = self.read(1)
        self.assertTrue(text.startswith("# Mein Titel\n\nText"))
        self.assertNotIn("---", text.split("\n")[0])

    def test_note_without_title_gets_a_placeholder(self):
        self.convert([zettel("", "nur Text", created="1301011200")])
        self.assertTrue(self.read(1).startswith("# Zettel 1 (ohne Titel)"))

    def test_keywords_become_normalised_hashtags_at_the_end(self):
        self.convert([zettel("A", "x", created="1301011200", keywords="1,2,1")],
                     keywords=["Niklas Luhmann /p", "Bier"])
        self.assertTrue(self.read(1).rstrip().endswith("#niklas-luhmann-p #bier"))

    def test_deleted_slot_is_skipped_but_numbering_is_kept(self):
        self.convert([zettel("A", created="1301011200"), zettel(""), zettel("C", created="1301011202")])
        self.assertEqual(set(self.mapping()), {1, 3})

    # --- links --------------------------------------------------------------------------------

    def test_links_use_the_new_ids_and_all_resolve(self):
        self.convert([
            zettel("Wurzel", "siehe [z 3]den Dritten[/z]", created="1301011200", luhmann="2,3", manlinks="3"),
            zettel("Kind", created="1301011201"),
            zettel("Blatt", created="1301011202"),
        ])
        ids = {p.stem for p in self.notes()}
        found = [m.split("|")[0] for p in self.notes()
                 for m in re.findall(r"\[\[([^\]]+)\]\]", p.read_text(encoding="utf-8"))]
        self.assertGreaterEqual(len(found), 4)
        self.assertTrue(set(found) <= ids)
        root = self.read(1)
        self.assertIn("[[%s|den Dritten]]" % self.mapping()[3], root)
        self.assertIn("## Folgezettel", root)
        self.assertIn("## Verweise", root)
        self.assertIn("## Übergeordnet\n- [[%s|Wurzel]]" % self.mapping()[1], self.read(2))

    def test_links_to_deleted_notes_are_dropped(self):
        self.convert([zettel("A", "[z 2]weg[/z]", created="1301011200", luhmann="2", manlinks="2"),
                      zettel("")])
        text = self.read(1)
        self.assertIn("weg", text)
        self.assertNotIn("[[", text)
        self.assertNotIn("## Folgezettel", text)

    # --- markup -------------------------------------------------------------------------------

    def test_markup_is_converted(self):
        body = ("[h1]Kopf[/h1][br][f]fett[/f] und [k]kursiv[/k][br][q]Zitat[br]zweizeilig[/q]"
                "[l][*]eins[/*][*]zwei[/*][/l][http://example.org] [fn 1:42]")
        self.convert([zettel("A", body, created="1301011200")], authors=["Luhmann 1984"])
        text = self.read(1)
        for expected in ("# Kopf", "**fett**", "*kursiv*", "> Zitat\n> zweizeilig", "- eins\n- zwei",
                         "<http://example.org>", "[Quelle: Luhmann 1984, S. 42]"):
            self.assertIn(expected, text)
        self.assertNotRegex(text, r"\[/?(br|f|k|q|l|fn)[] ]")

    def test_sources_are_listed_as_text(self):
        self.convert([zettel("A", "x", created="1301011200", author="1")], authors=["Luhmann 1984"])
        self.assertIn("## Quellen\n- Luhmann 1984", self.read(1))

    # --- images and attachments ---------------------------------------------------------------

    def test_images_are_copied_with_lowercase_extension_and_the_width_is_dropped(self):
        (self.root / "img").mkdir()
        (self.root / "img" / "FOTO.JPG").write_bytes(b"jpg")
        (self.root / "img" / "mit leerzeichen.png").write_bytes(b"png")
        self.convert([zettel("A", "[img]FOTO.JPG|300[/img] [img]mit leerzeichen.png[/img]",
                             created="1301011200")])
        text = self.read(1)
        self.assertIn("![](img/FOTO.jpg)", text)
        self.assertIn("![](img/mit%20leerzeichen.png)", text)
        self.assertEqual(sorted(p.name for p in (self.out / "img").iterdir()),
                         ["FOTO.jpg", "mit leerzeichen.png"])

    def test_image_in_the_remarks_field_is_copied_too(self):
        (self.root / "img").mkdir()
        (self.root / "img" / "misc.png").write_bytes(b"png")
        self.convert([zettel("A", "x", created="1301011200", misc="Bild: [img]misc.png[/img]")])
        self.assertIn("![](img/misc.png)", self.read(1))
        self.assertTrue((self.out / "img" / "misc.png").is_file())

    def test_missing_images_are_listed_in_a_file_not_in_the_note(self):
        self.convert([zettel("A", "[img]weg.png[/img]", created="1301011200")])
        self.assertEqual((self.out / "_fehlende-bilder.txt").read_text(encoding="utf-8").strip(), "weg.png")

    def test_attachments_are_copied_and_urls_stay_links(self):
        (self.root / "attachments" / "sub").mkdir(parents=True)
        (self.root / "attachments" / "sub" / "doc one.pdf").write_bytes(b"pdf")
        self.convert([zettel("A", "x", created="1301011200",
                             links=["sub/doc one.pdf", "http://example.org/x", "mailto:a@b.de", "fehlt.pdf"])])
        text = self.read(1)
        self.assertIn("- [doc one.pdf](attachments/sub/doc%20one.pdf)", text)
        self.assertIn("- <http://example.org/x>", text)
        self.assertIn("- <mailto:a@b.de>", text)
        self.assertTrue((self.out / "attachments" / "sub" / "doc one.pdf").is_file())
        self.assertEqual((self.out / "_fehlende-anhaenge.txt").read_text(encoding="utf-8").strip(), "fehlt.pdf")

    def test_different_files_with_the_same_name_do_not_overwrite_each_other(self):
        stash = z.FileStash(self.out, "attachments", [])
        (self.root / "x").mkdir()
        (self.root / "y").mkdir()
        (self.root / "x" / "same.txt").write_text("XXX")
        (self.root / "y" / "same.txt").write_text("YYY")
        first = stash.add(str(self.root / "x" / "same.txt"))
        second = stash.add(str(self.root / "y" / "same.txt"))
        self.assertNotEqual(first, second)
        self.assertEqual((self.out / first).read_text(), "XXX")
        self.assertEqual((self.out / second).read_text(), "YYY")

    # --- what is not carried over -------------------------------------------------------------

    def test_reports_what_is_not_migrated_with_counts_only(self):
        rated = zettel("Bewertet", "Geheimer Inhalt", created="1301011200", edited="1401011200")
        rated = rated.replace('zknid="x"', 'zknid="x" rating="4.5" ratingcount="2"')
        extra = {
            "desktop.xml": '<desktops><desktop name="Buch"/><desktop name="Notizen"/></desktops>',
            "bookmarks.xml": "<bookmarks><category/><bookmark><entry>1</entry><entry>2</entry></bookmark></bookmarks>",
            "searchrequests.xml": "<searches><searchrequest/></searches>",
            "synonyms.xml": "<synonyms><entry>a,b</entry></synonyms>",
        }
        make_archive(self.src, [rated], extra=extra)
        buffer = StringIO()
        with redirect_stdout(buffer):
            z.convert(str(self.src), str(self.out))
        line = next(l for l in buffer.getvalue().splitlines() if l.startswith("not migrated"))
        for expected in ("2 desktops (outlines)", "2 bookmarks", "1 saved searches", "1 synonyms",
                         "1 rated zettel", "1 edit dates"):
            self.assertIn(expected, line)
        self.assertNotIn("Geheimer", buffer.getvalue())

    def test_says_nothing_when_there_is_nothing_to_report(self):
        make_archive(self.src, [zettel("A", "x", created="1301011200")])
        buffer = StringIO()
        with redirect_stdout(buffer):
            z.convert(str(self.src), str(self.out))
        self.assertNotIn("not migrated", buffer.getvalue())

    # --- command line -------------------------------------------------------------------------

    def test_command_line_entry_point(self):
        make_archive(self.src, [zettel("A", "x", created="1301011200")])
        z.main([str(self.src), str(self.out)])
        self.assertEqual(len(self.notes()), 1)
        with self.assertRaises(SystemExit):
            z.main([])


if __name__ == "__main__":
    unittest.main()
