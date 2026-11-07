#!/usr/bin/env python3
"""Tagesseiten für die Sprachen-App.

Erzeugt jeden Tag
  - einen italienischen Text (B1–B2) zu aktuellen Schlagzeilen, mit Glossar und Satz des Tages
  - japanische Texte auf N5, N4 und N3 mit Wort-für-Wort-Erklärungen und Kanji-Infos

Läuft über GitHub Actions. Braucht das Repository-Secret GEMINI_API_KEY
(kostenlose Stufe von Google AI Studio, ohne Zahlungskonto).
Nur Python-Standardbibliothek, nichts zu installieren.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]
NOW = datetime.now(ZoneInfo("Europe/Berlin"))
TODAY = NOW.strftime("%Y-%m-%d")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0 (Sprachen-Lernapp; GitHub Actions)"}

IT_FEEDS = [
    "https://www.ansa.it/sito/ansait_rss.xml",
    "https://www.ilpost.it/feed/",
    "https://www.rainews.it/rss/tutti",
]
JA_FEEDS = ["https://www3.nhk.or.jp/rss/news/cat0.xml"]

N5_TOPICS = [
    "Mein Morgen vor der Uni", "Im Café", "Einkaufen im Supermarkt", "Wochenende im Park",
    "Mit dem Zug fahren", "Das Wetter heute", "Meine Familie", "Ein Tag an der Universität",
    "Ein Geburtstag", "Im Restaurant bestellen", "Eine Nachricht an eine Freundin", "Mein Zimmer",
    "Sport am Abend", "Ein Ausflug in die Berge", "Kochen zu Hause", "In der Bibliothek",
    "Neue Schuhe kaufen", "Ein Tag in Tokio", "Meine Hobbys", "Japanisch lernen", "Musik hören",
    "Ein Spaziergang am Fluss", "Fotos machen", "Telefonieren mit der Mutter", "Am Bahnhof",
    "Jahreszeiten in Japan", "Ein Picknick", "Im Kino", "Eine kleine Party", "Mit dem Fahrrad",
    "Am Wochenende früh aufstehen", "Ein Brief aus Japan",
]

JA_RULES = {
    "N5": "4–6 sehr kurze Sätze. Nur N5-Wortschatz und -Grammatik (です/ます, は/が/を/に/で/へ/と/も/の, "
          "～たい, ～ています, ～ましょう). Nur N5-Kanji, alles andere in Hiragana oder Katakana.",
    "N4": "5–7 kurze Sätze. Wortschatz und Grammatik bis N4 (einfache Form, ～と思います, ～たり～たり, "
          "～ことができる, ～から/ので, ～ても). Kanji bis N4, seltenere Wörter in Kana.",
    "N3": "6–8 Sätze in einfachem Nachrichtenstil. Wortschatz, Grammatik und Kanji bis N3.",
}

IT_PROMPT = """Du bist Italienischlehrer:in für eine deutschsprachige Lernende auf Niveau B1–B2.
Heute ist {date}. Hier sind aktuelle Schlagzeilen italienischer Nachrichtenseiten (JSON):
{news}

Aufgabe:
1. Wähle EIN interessantes Thema daraus (bevorzugt Gesellschaft, Kultur, Wissenschaft, Wirtschaft, Umwelt, Sport; keine grausamen Details).
2. Schreibe darüber einen eigenen, neuen italienischen Text mit 150–220 Wörtern in 3 Absätzen. Übernimm keine Sätze aus der Quelle. Niveau B1–B2: klare Sätze, einige nützliche Wendungen. Erfinde keine Fakten, die nicht in Schlagzeile oder Beschreibung stehen; bleib allgemein, wo Details fehlen, und erkläre Hintergründe einfach.
3. Füge als "frase" {tipo} hinzu, mit deutscher Übersetzung und einer kurzen Erklärung auf Deutsch, wann man das sagt.
4. Gib ein Glossar für JEDE Wortform, die im Titel, im Text und in der frase vorkommt. Schlüssel = Wortform in Kleinbuchstaben genau wie im Text; Formen mit Apostroph inklusive Apostroph (z. B. "l'", "dell'", "c'", "un'"). Werte: "de" = deutsche Übersetzung passend zum Kontext, "lemma" = Grundform (Infinitiv, Singular maskulin), "info" = sehr kurze Grammatikinfo auf Deutsch (z. B. "Verb, passato prossimo, 3. Pers. Sg.") oder "".

Antworte NUR mit JSON in genau diesem Format:
{{"titolo":"...","testo":["Absatz 1","Absatz 2","Absatz 3"],"fonte":{{"titolo":"Originalschlagzeile","link":"URL aus der Liste"}},"frase":{{"tipo":"Sprichwort oder Alltagssatz","it":"...","de":"...","spiegazione":"..."}},"glossario":{{"wortform":{{"de":"...","lemma":"...","info":"..."}}}}}}"""

IT_FILL = """Italienischer Text:
{text}

Gib für jede dieser Wortformen aus dem Text einen Glossar-Eintrag für eine deutschsprachige Lernende (Übersetzung passend zum Kontext):
{words}

Antworte NUR mit JSON: {{"wortform":{{"de":"...","lemma":"...","info":"kurze Grammatikinfo auf Deutsch oder leer"}}}}"""

JA_PROMPT = """Du bist Japanischlehrer:in für eine deutschsprachige Lernende. Schreibe einen kurzen japanischen Lesetext auf JLPT-Niveau {level}.
Thema: {topic}
Vorgaben für das Niveau: {rules}

Zerlege den Text in Sätze und jeden Satz in Tokens: Wörter, Partikeln und Verbendungen als sinnvolle Lerneinheiten, Satzzeichen als eigene Tokens. Die Tokens eines Satzes ergeben hintereinander genau den Satz.
Für jedes Token außer Satzzeichen:
- "s": Schreibung wie im Text
- "r": Lesung in Hiragana (auch bei reinen Kana-Wörtern)
- "de": deutsche Bedeutung im Kontext
- "art": Wortart auf Deutsch, z. B. "Nomen", "Verb (te-Form)", "Partikel", "i-Adjektiv"
- "erkl": 1–2 Sätze auf Deutsch, WARUM dieses Wort bzw. dieser Wortteil genau hier steht und welche grammatische Funktion es hat. Bei Partikeln und Verbformen besonders genau.
- "bsp": ein anderer einfacher Beispielsatz mit diesem Wort: {{"jp":"...","r":"ganzer Satz in Hiragana","de":"..."}}
Satzzeichen so: {{"s":"。","p":true}}
Zu jedem Satz eine deutsche Übersetzung "de".
Für JEDES Kanji im Text einen Eintrag in "kanji" mit Bedeutung auf Deutsch, On- und Kun-Lesungen und "verwendung": 1–2 Sätze auf Deutsch, in welchen Situationen und Wörtern man das Kanji typischerweise verwendet, mit einem Beispielwort.

Antworte NUR mit JSON in genau diesem Format:
{{"titel":"...","titel_de":"...","saetze":[{{"tokens":[{{"s":"...","r":"...","de":"...","art":"...","erkl":"...","bsp":{{"jp":"...","r":"...","de":"..."}}}},{{"s":"。","p":true}}],"de":"..."}}],"kanji":{{"日":{{"bed":"...","on":["ニチ"],"kun":["ひ"],"verwendung":"..."}}}}}}"""

JA_KANJI_FILL = """Erkläre diese Kanji für eine deutschsprachige Japanisch-Lernende: {chars}
Antworte NUR mit JSON: {{"日":{{"bed":"Bedeutung auf Deutsch","on":["..."],"kun":["..."],"verwendung":"1–2 Sätze, in welchen Situationen und Wörtern man es verwendet, mit Beispielwort"}}}}"""

WORD_RE = re.compile(r"[^\W\d_]+['’]?")
KANJI_RE = re.compile(r"[\u4e00-\u9fff]")


def log(*a):
    print(*a, flush=True)


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def norm(w):
    return w.strip().lower().replace("’", "'")


def read_feed(url, n=12):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        log("Feed nicht erreichbar:", url, e)
        return []
    items = []
    for it in root.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        kids = {c.tag.split("}")[-1]: c for c in it}
        t, d, l = kids.get("title"), kids.get("description") or kids.get("summary"), kids.get("link")
        title = clean(t.text if t is not None else "")
        link = ""
        if l is not None:
            link = (l.text or l.get("href", "") or "").strip()
        if title:
            items.append({"titolo": title, "descrizione": clean(d.text if d is not None else "")[:300], "link": link})
        if len(items) >= n:
            break
    log(f"{len(items)} Schlagzeilen aus {url}")
    return items


def gemini(prompt, temperature=0.7):
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": temperature,
                             "maxOutputTokens": 32768},
    }).encode()
    last = None
    models = list(MODELS)
    for model in models:
        for attempt in range(3):
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
            try:
                with urllib.request.urlopen(req, timeout=240) as r:
                    res = json.loads(r.read())
                parts = res["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
                time.sleep(4)  # sanft mit dem Gratis-Limit umgehen
                return json.loads(text)
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:300]
                last = f"{model}: HTTP {e.code} {msg}"
                log(last)
                if e.code in (401, 403):
                    raise RuntimeError("API-Schlüssel ungültig oder nicht freigeschaltet: " + last)
                if e.code in (400, 404):
                    # Google nennt bei veralteten Modellen oft den Nachfolger: den automatisch mitprobieren
                    for m in re.findall(r"models/([\w.\-]+)", msg):
                        if m != model and m not in models:
                            models.append(m)
                    break  # nächstes Modell probieren
                time.sleep(30 * (attempt + 1))  # 429 oder 5xx: warten und nochmal
            except Exception as e:
                last = f"{model}: {e}"
                log(last)
                time.sleep(5)
    raise RuntimeError(last or "Gemini nicht erreichbar")


def italian():
    news = []
    for f in IT_FEEDS:
        news += read_feed(f)
    if not news:
        raise RuntimeError("Keine italienischen Schlagzeilen gefunden")
    tipo = ("ein bekanntes italienisches Sprichwort" if NOW.toordinal() % 2 == 0
            else "einen nützlichen Alltagssatz (z. B. aus Bar, Uni, Einkaufen oder Smalltalk)")
    obj = gemini(IT_PROMPT.format(date=TODAY, news=json.dumps(news[:24], ensure_ascii=False), tipo=tipo))
    for k in ("titolo", "testo", "frase", "glossario"):
        if k not in obj:
            raise RuntimeError("Antwort unvollständig, es fehlt: " + k)
    if isinstance(obj["testo"], str):
        obj["testo"] = [p for p in obj["testo"].split("\n") if p.strip()]
    if not isinstance(obj["frase"], dict):
        obj["frase"] = {}
    gl = {norm(k): v for k, v in (obj["glossario"] or {}).items() if isinstance(v, dict)}
    alltext = " ".join([obj["titolo"], *obj["testo"], obj["frase"].get("it", "")])
    missing = sorted({norm(w) for w in WORD_RE.findall(alltext)} - set(gl))
    missing = [w for w in missing if w.rstrip("'") not in gl]
    if missing:
        log("Ergänze Glossar für", len(missing), "Wörter")
        try:
            extra = gemini(IT_FILL.format(text=alltext, words=json.dumps(missing, ensure_ascii=False)))
            for k, v in extra.items():
                if isinstance(v, dict):
                    gl[norm(k)] = v
        except Exception as e:
            log("Glossar-Ergänzung fehlgeschlagen:", e)
    obj["glossario"] = gl
    obj["datum"] = TODAY
    return obj


def japanese():
    heads = []
    for f in JA_FEEDS:
        heads += read_feed(f, 10)
    day = NOW.toordinal()
    out = {"datum": TODAY, "levels": {}}
    for i, lvl in enumerate(("N5", "N4", "N3")):
        head = None
        if lvl == "N5" or not heads:
            topic = f"{N5_TOPICS[(day + i * 7) % len(N5_TOPICS)]} (heute ist der {TODAY}, Jahreszeit passend)"
        else:
            head = heads[(day + i) % len(heads)]
            topic = ("Eine stark vereinfachte Nacherzählung dieser aktuellen japanischen Nachricht in eigenen Worten "
                     f"(keine Sätze übernehmen, keine Fakten erfinden): {head['titolo']} – {head['descrizione']}")
        try:
            obj = gemini(JA_PROMPT.format(level=lvl, topic=topic, rules=JA_RULES[lvl]))
            sents = [s for s in obj.get("saetze", []) if isinstance(s, dict) and isinstance(s.get("tokens"), list)]
            if not sents:
                raise RuntimeError("keine Sätze in der Antwort")
            obj["saetze"] = sents
            kanji = obj.get("kanji") if isinstance(obj.get("kanji"), dict) else {}
            used = {c for s in sents for t in s["tokens"] if isinstance(t, dict) for c in KANJI_RE.findall(str(t.get("s", "")))}
            used |= set(KANJI_RE.findall(str(obj.get("titel", ""))))
            miss = sorted(used - set(kanji))
            if miss:
                log(lvl, "ergänze Kanji:", "".join(miss))
                try:
                    extra = gemini(JA_KANJI_FILL.format(chars="".join(miss)))
                    kanji.update({k: v for k, v in extra.items() if isinstance(v, dict)})
                except Exception as e:
                    log("Kanji-Ergänzung fehlgeschlagen:", e)
            obj["kanji"] = kanji
            if head:
                obj["quelle"] = {"titel": head["titolo"], "link": head["link"]}
            out["levels"][lvl] = obj
            log(lvl, "fertig:", obj.get("titel", ""))
        except Exception as e:
            log(lvl, "fehlgeschlagen:", e)
    if not out["levels"]:
        raise RuntimeError("kein japanischer Text erzeugt")
    return out


def path_for(lang):
    return os.path.join(DATA, lang, TODAY + ".json")


def save(lang, obj):
    os.makedirs(os.path.join(DATA, lang), exist_ok=True)
    with open(path_for(lang), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def rebuild_index():
    idx = {}
    for lang in ("it", "ja"):
        d = os.path.join(DATA, lang)
        files = os.listdir(d) if os.path.isdir(d) else []
        idx[lang] = sorted((f[:-5] for f in files if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f)), reverse=True)
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, separators=(",", ":"))


def main():
    if not KEY:
        log("GEMINI_API_KEY fehlt. Lege das Secret in den Repository-Einstellungen an.")
        sys.exit(1)
    ok = 0
    for lang, fn in (("it", italian), ("ja", japanese)):
        if os.path.exists(path_for(lang)):
            log(lang, "für", TODAY, "gibt es schon")
            ok += 1
            continue
        try:
            save(lang, fn())
            ok += 1
            log(lang, "gespeichert")
        except Exception as e:
            log(lang, "Fehler:", e)
    rebuild_index()
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
