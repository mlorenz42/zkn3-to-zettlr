#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Convert a Zettelkasten 3 (.zkn3) archive into a folder of Markdown notes in Zettlr's own style:
one file per note named by a 14-digit timestamp ID (<ID>.md), the title as first "# heading",
[[ID|Title]] links and #hashtags for the keywords -- no frontmatter, like a note written in Zettlr.

A .zkn3 is a ZIP of XML files. Cross references (author, keywords, manlinks,
luhmann) are 1-based *positions* in the zettel/author/keyword lists, and deleted
zettel stay in the list as empty slots -- so positions must never be re-numbered.
"""
import os
import re
import sys
import csv
import shutil
import zipfile
import collections
from urllib.parse import quote
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

ID_FORMAT = "%Y%m%d%H%M%S"  # Zettlr's default note ID, "%Y%M%D%h%m%s" in its own notation


def parse_dt(ts):
    """Zettelkasten timestamps are yymmddHHMM, e.g. 0504141353 = 2005-04-14 13:53."""
    try:
        return datetime.strptime(ts, "%y%m%d%H%M")
    except (ValueError, TypeError):
        return None


def assign_ids(created):
    """One unique 14-digit ID per note. The old timestamps only have minute precision, so notes
    created in the same minute get the following seconds; a note without a valid timestamp
    follows its predecessor. `created` is a list of datetimes or None."""
    used, result, previous = set(), [], datetime(2000, 1, 1)
    for dt in created:
        candidate = dt or previous
        while candidate.strftime(ID_FORMAT) in used:
            candidate += timedelta(seconds=1)
        used.add(candidate.strftime(ID_FORMAT))
        result.append(candidate.strftime(ID_FORMAT))
        previous = candidate
    return result


def ids(text):
    return [int(x) for x in (text or "").split(",") if x.strip().isdigit()]


def tag_name(keyword):
    """Zettlr hashtags (#tag) may only contain letters, digits, '_' and '-', and Zettlr lowercases
    tags anyway, so 'Niklas Luhmann /p' becomes 'niklas-luhmann-p'."""
    return re.sub(r"[^\w-]+", "-", keyword.lower()).strip("-")


UNKNOWN = collections.Counter()
# http://..., mailto:..., ftp://... -- but not a Windows drive letter like C:\
IS_URL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]+:")


def ubb_to_md(text, wikilink, authors, image=lambda p: p):
    """Convert the [tag]-markup used in <content> to Markdown. Unknown tags stay as-is.

    `wikilink(number, label=None)` returns the internal link for a note position, and
    `image` maps the path inside [img]path|width[/img] to the link target to emit.
    """
    t = text

    # [img]name.jpg[/img] or [img]name.jpg|300[/img] (the part after | is a display width)
    t = re.sub(r"\[img\](.*?)\[/img\]",
               lambda m: "![](%s)" % image(m.group(1).split("|")[0].strip()), t, flags=re.S)

    # Tags that carry an argument
    # [z 3]text[/z] -> [[ID|text]]; a bare [z 3] without closing tag -> [[ID|Title of note 3]]
    t = re.sub(r"\[z (\d+)\](.*?)\[/z\]", lambda m: wikilink(int(m.group(1)), m.group(2)), t, flags=re.S)
    t = re.sub(r"\[z (\d+)\]", lambda m: wikilink(int(m.group(1))), t)

    def footnote(m):
        ref = m.group(1).split(":")[0]
        page = m.group(1).split(":")[1] if ":" in m.group(1) else None
        label = authors.get(int(ref), ref) if ref.isdigit() else ref
        return "[Quelle: %s%s]" % (label, ", S. " + page if page else "")

    t = re.sub(r"\[fn ([^\]]+)\]", footnote, t)
    t = re.sub(r"\[(?:color|font) [^\]]*\]|\[/(?:color|font)\]", "", t)
    t = re.sub(r"\[/?(?:c|al|ar|ab)\]", "", t)  # alignment has no Markdown equivalent

    # URLs written as [http://...] / [mailto:...]
    t = re.sub(r"\[((?:https?|ftp|mailto):[^\]\s]+)\]", r"<\1>", t)

    # Lists: [l][*]a[/*][*]b[/*][/l]
    t = re.sub(r"\[l\]", "\n", t)
    t = re.sub(r"\[n\]", "\n", t)
    t = re.sub(r"\[/(?:l|n)\]", "\n", t)
    t = re.sub(r"\[\*\]", "\n- ", t)
    t = t.replace("[/*]", "")

    simple = {
        "[br]": "\n",
        "[h1]": "# ", "[/h1]": "\n",
        "[h2]": "## ", "[/h2]": "\n",
        "[f]": "**", "[/f]": "**",
        "[k]": "*", "[/k]": "*",
        "[u]": "<u>", "[/u]": "</u>",
        "[d]": "~~", "[/d]": "~~",
        "[sup]": "<sup>", "[/sup]": "</sup>",
        "[sub]": "<sub>", "[/sub]": "</sub>",
        "[code]": "`", "[/code]": "`",
        "[qm]": "„", "[/qm]": "“",
    }
    for k, v in simple.items():
        t = t.replace(k, v)

    # Block quotes: prefix every line inside [q]...[/q]
    def quote(m):
        return "\n" + "\n".join("> " + l for l in m.group(1).strip("\n").split("\n")) + "\n"

    t = re.sub(r"\[q\](.*?)\[/q\]", quote, t, flags=re.S)

    for tag in re.findall(r"\[/?(?:form|tc)[^\]]*\]", t):
        UNKNOWN[tag.split()[0].strip("[]/")] += 1
    return re.sub(r"\n{3,}", "\n\n", t).strip() + "\n"


class FileStash:
    """Finds files referenced by notes (images, attachments), copies them to <out>/<subdir>/
    and returns the relative Markdown link target."""

    def __init__(self, out, subdir, search_dirs, lower_ext=False):
        self.out, self.subdir, self.dirs, self.lower_ext = Path(out), subdir, search_dirs, lower_ext
        self.done, self.used, self.missing = {}, {}, []

    def add(self, path):
        if path in self.done:
            return self.done[path]
        p = Path(path.replace("\\", "/"))
        # same lookup order as the app: path as given, then inside the known folders
        candidates = ([p] if p.is_absolute() else []) + [d / p for d in self.dirs] + [d / p.name for d in self.dirs]
        found = next((c for c in candidates if c.is_file()), None)
        # keep a simple relative sub-path, otherwise flatten to the file name
        rel = p if (not p.is_absolute() and ".." not in p.parts) else Path(p.name)
        if self.lower_ext:
            # Zettlr only knows the content type of ".jpg", not ".JPG" (safe-file protocol handler)
            rel = rel.with_suffix(rel.suffix.lower())
        stem, n = rel, 1
        # different file, same name -- compared case-insensitively, since macOS volumes are
        while str(rel).lower() in self.used and self.used[str(rel).lower()] != found:
            n += 1
            rel = stem.with_name("%s-%d%s" % (stem.stem, n, stem.suffix))
        self.used[str(rel).lower()] = found
        if found:
            (self.out / self.subdir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found, self.out / self.subdir / rel)
        else:
            self.missing.append(path)
        self.done[path] = "/".join([self.subdir] + [quote(part) for part in rel.parts])
        return self.done[path]

    def report(self, label, listfile):
        if not self.done:
            return
        print("%s: %d referenced, %d copied to %s/, %d not found"
              % (label, len(self.done), len(self.done) - len(self.missing), self.subdir, len(self.missing)))
        if self.missing:
            # file names can be private too, so they go to a local file instead of the terminal
            (self.out / listfile).write_text("\n".join(self.missing) + "\n", encoding="utf-8")
            print("  missing ones are listed in %s" % (self.out / listfile))


def count_not_migrated(archive, zettel):
    """Things stored in the archive that this converter does not carry over. Only counted, so the
    result can be printed without revealing any content."""
    def count(member, counter):
        if member not in archive.namelist():
            return 0
        try:
            return counter(ET.fromstring(archive.read(member)))
        except ET.ParseError:
            return 0

    def is_rated(el):
        try:
            return float(el.get("rating") or 0) > 0
        except ValueError:
            return False

    return {
        "desktops (outlines)": count("desktop.xml", lambda r: len(r.findall("desktop"))),
        "bookmarks": count("bookmarks.xml", lambda r: sum(len(b) for b in r.findall("bookmark"))),
        "saved searches": count("searchrequests.xml", lambda r: len(r.findall("searchrequest"))),
        "synonyms": count("synonyms.xml", lambda r: len(r)),
        "rated zettel": sum(1 for el in zettel if is_rated(el)),
        "edit dates": sum(1 for el in zettel if el.get("ts_edited")),
    }


def convert(src, out, data_dir=None):
    UNKNOWN.clear()  # the counter is module-level; start every conversion from zero
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # The app keeps images and attachments OUTSIDE the archive: in the folders named in
    # metaInformation.xml, else in "img/" and "attachments/" next to the .zkn3 file.
    base = Path(data_dir) if data_dir else Path(src).resolve().parent
    with zipfile.ZipFile(src) as z:
        read = lambda n: ET.fromstring(z.read(n))
        meta = read("metaInformation.xml") if "metaInformation.xml" in z.namelist() else None
        meta_text = lambda tag: ((meta.findtext(tag) if meta is not None else "") or "").strip()
        zettel = read("zknFile.xml").findall("zettel")
        keywords = {i: (e.text or "").strip() for i, e in enumerate(read("keywordFile.xml").findall("entry"), 1)}
        authors = {i: (e.text or "").strip() for i, e in enumerate(read("authorFile.xml").findall("entry"), 1)}
        bib = z.read("references.bib") if "references.bib" in z.namelist() else b""
        skipped = count_not_migrated(z, zettel)

    # deleted zettel are empty slots (see Daten.deleteZettel) -- keep numbering, skip file
    def is_empty(el):
        return not (el.findtext("title") or el.findtext("content") or el.findtext("author"))

    # Zettlr's standard: the file name is a timestamp ID. Deleted slots get none, so links to them
    # cannot point anywhere and fall back to their link text.
    live = [i for i, el in enumerate(zettel, 1) if not is_empty(el)]
    created = {i: parse_dt(zettel[i - 1].get("ts_created")) for i in live}
    zid = dict(zip(live, assign_ids([created[i] for i in live])))

    def title_of(n):
        return re.sub(r"\s+", " ", zettel[n - 1].findtext("title") or "").strip() or "Zettel %d (ohne Titel)" % n

    def wikilink(n, label=None):
        """[[ID|label]], the way Zettlr writes internal links (link|title format)."""
        if n not in zid:
            return label or ""
        if label is None:
            label = re.sub(r"[\[\]]", " ", title_of(n))
        label = re.sub(r"\s+", " ", label.replace("|", " ")).strip()
        return "[[%s|%s]]" % (zid[n], label) if label else "[[%s]]" % zid[n]

    dirs = lambda user, default: [Path(d) for d in (user, str(base / default)) if d]
    images = FileStash(out, "img", dirs(meta_text("imagepath"), "img"), lower_ext=True)
    attachments = FileStash(out, "attachments", dirs(meta_text("attachmentpath"), "attachments") + [base])

    # invert the luhmann trail so every child knows its parent
    parent = {}
    for i, el in enumerate(zettel, 1):
        for c in ids(el.findtext("luhmann")):
            parent[c] = i

    written, mapping = 0, []
    for i in live:
        el = zettel[i - 1]
        title = title_of(i)
        # A note written in Zettlr itself starts empty: no frontmatter, the title is the first "# heading"
        # (Zettlr shows it in the file list) and keywords are #hashtags. The creation date is the ID and
        # the file date, the old note number goes to _zuordnung.csv. The old edit date is not kept.
        kws = [tag_name(keywords[k]) for k in ids(el.findtext("keywords")) if k in keywords]
        kws = [k for k in dict.fromkeys(kws) if k]  # drop empties and duplicates, keep order

        body = ubb_to_md(el.findtext("content") or "", wikilink, authors, images.add)
        extra = []
        if i in parent and parent[i] in zid:
            extra.append("## Übergeordnet\n- " + wikilink(parent[i]))
        follow = [c for c in ids(el.findtext("luhmann")) if c in zid]
        if follow:
            extra.append("## Folgezettel\n" + "\n".join("- " + wikilink(c) for c in follow))
        rel = [c for c in ids(el.findtext("manlinks")) if c in zid]
        if rel:
            extra.append("## Verweise\n" + "\n".join("- " + wikilink(c) for c in rel))
        srcs = [authors[a] for a in ids(el.findtext("author")) if a in authors]
        if srcs:
            extra.append("## Quellen\n" + "\n".join("- " + re.sub(r"\s+", " ", s) for s in srcs))
        links = el.find("links")
        atts = [a.text for a in (links if links is not None else []) if a.text]
        if atts:
            extra.append("## Anhänge\n" + "\n".join(
                "- <%s>" % a if IS_URL.match(a)
                else "- [%s](%s)" % (Path(a.replace("\\", "/")).name, attachments.add(a)) for a in atts))
        if el.findtext("misc"):
            # the remarks field can hold the same markup (and images) as the note text
            extra.append("## Bemerkungen\n" + ubb_to_md(el.findtext("misc"), wikilink, authors, images.add).strip())
        if kws:
            extra.append(" ".join("#" + k for k in kws))

        path = out / (zid[i] + ".md")
        path.write_text(
            "# %s\n\n" % title + body + ("\n" + "\n\n".join(extra) + "\n" if extra else ""), encoding="utf-8")
        # File date = creation date (the ID). Zettlr's "sort by time" uses the modification date by
        # default, so with the old edit dates here the oldest note would not come first. On macOS
        # this also moves the file's creation date back, so sorting by creation time works too.
        stamp = datetime.strptime(zid[i], ID_FORMAT).timestamp()
        os.utime(path, (stamp, stamp))
        mapping.append((i, zid[i], title))
        written += 1

    with open(out / "_zuordnung.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["alte_nummer", "id", "titel"])
        w.writerows(mapping)
    if bib:
        (out / "references.bib").write_bytes(bib)
    print("%d zettel in file, %d written, %d empty slots skipped, %d keywords, %d sources"
          % (len(zettel), written, len(zettel) - written, len(keywords), len(authors)))
    oldest = min(live, key=lambda n: zid[n]) if live else None
    if oldest is not None and oldest != live[0]:
        print("note: sorted by time, old zettel number %d comes first, not number %d (their creation dates say so)"
              % (oldest, live[0]))
    undated = sum(1 for i in live if created[i] is None)
    if undated:
        print("%d zettel without a valid creation date (their ID follows the previous zettel)" % undated)
    images.report("images", "_fehlende-bilder.txt")
    attachments.report("attachments", "_fehlende-anhaenge.txt")
    if UNKNOWN:
        print("unhandled markup (left as-is):", dict(UNKNOWN))
    not_migrated = ["%d %s" % (n, what) for what, n in skipped.items() if n]
    if not_migrated:
        print("not migrated (present in the archive): " + ", ".join(not_migrated))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (2, 3):
        sys.exit("usage: zkn3_to_zettlr.py file.zkn3 output_dir [zettelkasten_dir]\n"
                 "  zettelkasten_dir: folder containing img/ and attachments/ (default: folder of the .zkn3)")
    convert(argv[0], argv[1], argv[2] if len(argv) == 3 else None)


if __name__ == "__main__":
    main()
