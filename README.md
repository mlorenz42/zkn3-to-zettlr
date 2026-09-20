# zkn3-to-zettlr

Wandelt Archive des Programms **Zettelkasten** von Daniel Lüdecke (Dateiendung `.zkn3`) in einen Ordner mit Markdown-Notizen um, die so aussehen, als hätte man sie in [Zettlr](https://www.zettlr.com) selbst geschrieben.

Das Skript ist ein einzelnes Python-Programm ohne Abhängigkeiten. Es läuft lokal und macht keine Netzwerkzugriffe. Die Originaldateien werden nur gelesen, nie verändert.

> **Inoffiziell.** Das Projekt hat keine Verbindung zu Zettelkasten oder Zettlr. Das Archivformat ist nicht offiziell dokumentiert; es wurde aus dem Quellcode und den Testdateien von Zettelkasten 3 abgeleitet. Lies bitte den Abschnitt [Grenzen](#grenzen--was-das-tool-nicht-kann), bevor du dich auf das Ergebnis verlässt.

## Was dabei herauskommt

| Im Zettelkasten | In der Ausgabe |
|---|---|
| Zettel | eine Datei `<ID>.md`. Die ID ist das Erstelldatum als 14-stellige Zahl (`JJJJMMTThhmmss`), also Zettlrs Standard-Schema `%Y%M%D%h%m%s`. |
| Titel | erste Überschrift `# Titel`, **kein** Frontmatter (wie bei einer in Zettlr selbst angelegten Notiz) |
| Schlagwörter | `#hashtags` in der letzten Zeile |
| Verknüpfungen | `[[ID\|Titel]]`, also Zettlrs Standardformat `link\|title` |
| Folgezettel (Luhmann-Struktur) | Abschnitte „Übergeordnet" und „Folgezettel" |
| manuelle Verweise | Abschnitt „Verweise" |
| Quellen | Abschnitt „Quellen" (als Text) |
| Anhänge, Bemerkungen | Abschnitte „Anhänge" und „Bemerkungen" |
| Bilder und Anhänge | werden nach `img/` und `attachments/` im Ausgabeordner kopiert |
| altes Erstelldatum | ID **und** Dateidatum, damit „Nach Zeit sortieren" in Zettlr die Entstehungsreihenfolge zeigt |
| alte Zettelnummern | Datei `_zuordnung.csv` (alte Nummer, ID, Titel) |

Ein Beispiel (frei erfunden):

```markdown
# Zeitabhängiger Musikgeschmack

Klassische Musik gefällt mir besonders, wenn ich viel um die Ohren habe.

## Übergeordnet
- [[20130624190100|Musik und Stimmung]]

#musik #psychologie
```

## Benutzung

Voraussetzung ist Python 3 (getestet mit 3.9), sonst nichts.

```sh
python3 zkn3_to_zettlr.py MeinArchiv.zkn3 ~/Zettelkasten-neu
```

- Der **Ausgabeordner sollte neu oder leer sein.** Das Skript löscht nichts, überschreibt aber Notizen mit gleicher ID.
- Bilder und Anhänge liegen nicht im Archiv, sondern daneben. Das Skript sucht sie im Ordner aus `metaInformation.xml` (`imagepath`, `attachmentpath`), sonst in `img/` und `attachments/` neben der `.zkn3`-Datei. Liegen sie woanders, gib als dritten Parameter den Ordner an, der `img/` und `attachments/` enthält:

  ```sh
  python3 zkn3_to_zettlr.py MeinArchiv.zkn3 ~/Zettelkasten-neu ~/Pfad/zum/Zettelkasten-Ordner
  ```

Am Ende druckt das Skript nur Zahlen, keine Inhalte. Dateinamen fehlender Dateien stehen in `_fehlende-bilder.txt` und `_fehlende-anhaenge.txt` im Ausgabeordner.

```
833 zettel in file, 833 written, 0 empty slots skipped, 159 keywords, 28 sources
images: 347 referenced, 347 copied to img/, 0 not found
attachments: 44 referenced, 44 copied to attachments/, 0 not found
not migrated (present in the archive): 2 desktops (outlines), 833 edit dates
```

Lies diese Zeilen. Wenn viele Bilder oder Anhänge „not found" sind, sucht das Skript am falschen Ort. Die Zeile „not migrated" nennt, was das Archiv enthält und was nicht übernommen wurde (siehe unten).

## Grenzen – was das Tool nicht kann

Das Skript wurde an einem einzigen realen Archiv entwickelt. Wer ein anderes oder komplizierteres Setup hat, sollte das Ergebnis genau prüfen.

### Wie weit es getestet ist

- **Nur mit Archiven im Format 3.8** (`<version id="3.8"/>` in `metaInformation.xml`). Ältere Programmversionen, das ältere `.zkn`-Format und neuere Versionen sind ungetestet.
- **Nur unter macOS** mit Python 3.9 und Zettlr 4.8.0. Windows und Linux sind ungetestet, auch die Behandlung von Windows-Pfaden (`C:\…`) in Anhängen.
- Die automatischen Tests (`tests/`) laufen mit selbst erzeugten Kleinstarchiven. Sie beweisen nicht, dass jedes echte Archiv sauber durchläuft.
- Was das Skript für Sonderfälle annimmt (etwa den Aufbau von Lesezeichen oder Synonymen), stammt aus dem Quellcode des Programms, nicht aus Praxis.

### Was nicht übernommen wird

Das Skript meldet am Ende, ob diese Dinge im Archiv vorhanden sind. Übernommen wird davon nichts:

- **Schreibtische** (die Gliederungen, `desktop.xml` samt Notizen)
- **Lesezeichen**
- **gespeicherte Suchen**
- **Synonyme**
- **Bewertungen** der Zettel (Sterne, `rating`)
- **Änderungsdaten.** Erhalten bleibt nur das Erstelldatum.
- **Tabellen und Formulare** (`[form]`, `[tc]`) und die zugehörigen Formularbilder (`forms/`). Das Markup bleibt als Text stehen, das Skript meldet „unhandled markup".
- Programm-Einstellungen (`.zks3`) und alles andere, was nicht im `.zkn3`-Archiv steht.

### Was verändert wird oder verloren geht

- **Formatierung ohne Markdown-Entsprechung** entfällt: Schriftart, Farbe, Ausrichtung. Unterstrichen wird `<u>`, hoch- und tiefgestellt werden `<sup>` und `<sub>` (HTML).
- **Einzelne Zeilenumbrüche** werden einfache Umbrüche. In der Zettlr-Vorschau und im Export fließen sie zu einer Zeile zusammen. Zwei Umbrüche ergeben einen Absatz.
- **Quellen und Fußnoten:** Literaturangaben stehen als Text im Abschnitt „Quellen", Fußnoten im Text werden zu `[Quelle: …, S. 42]`. BibTeX-Schlüssel werden nicht als Pandoc-Zitate (`[@schlüssel]`) umgesetzt. Eine vorhandene `references.bib` wird nur mitkopiert.
- **Schlagwörter werden umgeschrieben.** Zettlr-Hashtags erlauben nur Buchstaben, Ziffern, `_` und `-`. Das Skript schreibt deshalb alles klein und macht aus Leerzeichen und Sonderzeichen ein `-` („Niklas Luhmann /p" wird `niklas-luhmann-p`). Verschiedene Schlagwörter können dadurch zusammenfallen (etwa „C++" und „C#" zu `c`), und Schlagwörter nur aus Sonderzeichen entfallen.
- **Zettelnummern** stehen nicht mehr im Dateinamen. Verweise im Fließtext („siehe Zettel 42") werden nicht angepasst. Dafür gibt es `_zuordnung.csv`.
- **Mehrere Elternzettel:** Ist ein Zettel Folgezettel von mehreren Zetteln, steht bei ihm nur einer als „Übergeordnet" (der Elternzettel mit der höchsten Nummer). In der Folgezettel-Liste jedes Elternzettels steht er dagegen.
- **Verweise auf gelöschte Zettel** entfallen still. Im Text bleibt nur der Linktext stehen.
- **Die Sekunden in den IDs sind nicht echt.** Das alte Datum hat nur Minutengenauigkeit. Zettel derselben Minute bekommen fortlaufende Sekunden, Zettel ohne Datum die ID direkt nach ihrem Vorgänger. Zweistellige Jahre werden als 1969 bis 2068 gelesen.
- **Die Überschriften der Abschnitte** („Übergeordnet", „Folgezettel", …) sind deutsch und fest eingebaut.

### Annahmen über das Setup

- **Ein Archiv pro Lauf und pro Ausgabeordner.** Schreibst du mehrere Archive in denselben Ordner, können IDs kollidieren, und Notizen werden überschrieben.
- **Einmalige Migration, keine Synchronisation.** Ein zweiter Lauf in denselben Ordner überschreibt Notizen mit gleicher ID, also auch deine Änderungen in Zettlr. Löschen tut er nichts. Die Sekunden der Zettel einer Minute hängen von der Reihenfolge im Archiv ab und können sich nach Änderungen dort verschieben.
- **Bilder und Anhänge müssen auffindbar sein** (siehe oben). Absolute Pfade werden so genommen, wie sie stehen. Pfade eines anderen Rechners werden zusätzlich anhand des Dateinamens in den bekannten Ordnern gesucht. Wird nichts gefunden, steht der Link trotzdem im Zettel, und die Datei erscheint in der Liste der fehlenden. Zwei verschiedene Dateien mit gleichem Namen bekommen ein `-2`.
- **Das Dateidatum trägt die Sortierung nach Zeit.** Das Skript setzt Änderungs- und (unter macOS auch) Erstellzeit auf das alte Erstelldatum. Unter Linux und Windows ist nur die Änderungszeit gesetzt. Beim Kopieren, Zippen oder Synchronisieren des Ordners kann das Datum verloren gehen, dann ändert sich die Reihenfolge in Zettlr.

## Hinweise für Zettlr

Beobachtet mit Zettlr 4.8.0 (aus dem Quellcode und in der Praxis):

- **Links folgen** geht mit Cmd + Klick (unter Windows und Linux Strg + Klick). Ist die Option zum automatischen Suchen beim Folgen von Links eingeschaltet (`zkn.autoSearch`), öffnet sich zusätzlich die Suche.
- **Die Suche nach `#tag`** (und damit die Tag-Wolke) findet nur Hashtags, die als Text im Zettel stehen, nicht Tags, die nur im Frontmatter stehen. Deshalb schreibt das Skript die Schlagwörter als Hashtags an das Ende. Die Suche arbeitet mit Teilstrings: `#bier` findet auch `#bierbrauen`.
- **Nach Zeit sortieren** nutzt das Dateidatum. **Nach Name sortieren** ordnet in der Standardeinstellung („title+heading") nach dem Titel, nicht nach der ID.
- **Bildendungen** schreibt das Skript klein (`.JPG` wird `.jpg`). Bei großgeschriebenen Endungen zeigte Zettlr 4.8.0 das Bild nicht an.
- Damit neue Bilder im selben Ordner landen wie die migrierten, stellst du in Zettlr den „Default image folder" auf `img`.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Die Tests bauen ihre Archive selbst. Es liegen weder Testdaten noch persönliche Zettel im Repository.

## Herkunft und Lizenz

MIT, siehe [LICENSE](LICENSE).

Das Archivformat wurde aus Quellcode und Testdateien von [Zettelkasten](https://github.com/Zettelkasten-Team/Zettelkasten) (Daniel Lüdecke, GPLv3) abgeleitet. Dieser Konverter ist eine eigene Implementierung und enthält weder Code noch Testdaten aus diesem Projekt.
