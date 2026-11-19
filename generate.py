#!/usr/bin/env python3
"""Tagesseiten für die Sprachen-App.

Erzeugt jeden Tag
  - einen italienischen Text (B1–B2) zu aktuellen Schlagzeilen, mit Glossar und Satz des Tages
  - japanische Texte auf N5, N4 und N3 mit Wort-für-Wort-Erklärungen und Kanji-Infos

Läuft über GitHub Actions. Braucht das Repository-Secret GEMINI_API_KEY
(kostenlose Stufe von Google AI Studio, ohne Zahlungskonto).
Nur Python-Standardbibliothek, nichts zu installieren.
"""
import difflib
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
DEADLINE = time.time() + 35 * 60  # nach 35 Minuten aufhören und speichern, was fertig ist;
# Fehlendes wird beim nächsten Lauf nachgeholt
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
    "N5": "10–12 kurze Sätze in 2–3 Absätzen, eine kleine zusammenhängende Geschichte. Nur N5-Wortschatz und -Grammatik "
          "(です/ます, は/が/を/に/で/へ/と/も/の, ～たい, ～ています, ～ましょう). "
          "KANJI: Schreibe JEDES Wort, das ein N5-Kanji hat, mit Kanji, nicht in Hiragana, z. B. 今日, 私, 朝, 毎日, 学校, "
          "大学, 先生, 友達, 時間, 天気, 雨, 山, 川, 駅, 電車, 食べます, 飲みます, 行きます, 来ます, 見ます, 読みます, "
          "書きます, 買います, 話します, 休みます, 大きい, 小さい, 新しい, 高い, 安い, 白い, 一つ, 二人, 何, 上, 下, 中, 前, 後. "
          "Uhrzeiten und Daten mit Kanji (七時, 月曜日). Verwende mindestens 20 verschiedene Kanji. "
          "Nur Wörter ohne N5-Kanji in Hiragana oder Katakana.",
    "N4": "12–15 Sätze in 3 Absätzen. Wortschatz und Grammatik bis N4 (einfache Form, ～と思います, ～たり～たり, "
          "～ことができる, ～から/ので, ～ても). KANJI: Schreibe jedes Wort mit Kanji bis N4 auch in Kanji "
          "(z. B. 会社, 仕事, 家族, 料理, 旅行, 運動, 始めます, 使います, 思います). Mindestens 35 verschiedene Kanji.",
    "N3": "14–18 Sätze in 3–4 Absätzen in einfachem Nachrichtenstil. Wortschatz, Grammatik und Kanji bis N3, "
          "Wörter mit Kanji immer in Kanji. Mindestens 50 verschiedene Kanji.",
}
JA_MIN = {"N5": (9, 15), "N4": (11, 28), "N3": (12, 40)}  # (Sätze, verschiedene Kanji) mindestens
JA_VERSION = 2

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

JA_TEXT_PROMPT = """Du bist Japanischlehrer:in für eine deutschsprachige Lernende. Schreibe einen längeren japanischen Lesetext auf JLPT-Niveau {level}.
Thema: {topic}
Vorgaben für das Niveau: {rules}

Gib jeden Satz einzeln an, mit deutscher Übersetzung.
Antworte NUR mit JSON in genau diesem Format:
{{"titel":"...","titel_de":"...","saetze":[{{"jp":"...","de":"..."}}]}}"""

JA_TOKEN_PROMPT = """Du bist Japanischlehrer:in für eine deutschsprachige Lernende (Niveau {level}).
Hier sind japanische Sätze (JSON-Liste):
{sents}

Zerlege jeden Satz in Tokens: Wörter, Partikeln und Verbendungen als sinnvolle Lerneinheiten, Satzzeichen als eigene Tokens. Die Tokens eines Satzes ergeben hintereinander GENAU den Satz, ohne etwas zu ändern.
Für jedes Token außer Satzzeichen:
- "s": Schreibung wie im Satz
- "r": Lesung in Hiragana (auch bei reinen Kana-Wörtern)
- "de": deutsche Bedeutung im Kontext
- "art": Wortart auf Deutsch, z. B. "Nomen", "Verb (te-Form)", "Partikel", "i-Adjektiv"
- "erkl": 1–2 Sätze auf Deutsch, WARUM dieses Wort bzw. dieser Wortteil genau hier steht und welche grammatische Funktion es hat. Bei Partikeln und Verbformen besonders genau.
- "bsp": ein anderer einfacher Beispielsatz mit diesem Wort: {{"jp":"...","r":"ganzer Satz in Hiragana","de":"..."}}
Satzzeichen so: {{"s":"。","p":true}}

Antworte NUR mit JSON, ein Eintrag pro Satz in derselben Reihenfolge:
{{"saetze":[{{"tokens":[{{"s":"...","r":"...","de":"...","art":"...","erkl":"...","bsp":{{"jp":"...","r":"...","de":"..."}}}},{{"s":"。","p":true}}]}}]}}"""

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
    """Fragt Gemini. Bei Überlastung wird sofort das nächste Modell probiert,
    gewartet wird erst, wenn alle Modelle gerade nicht können."""
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": temperature,
                             "maxOutputTokens": 65536},
    }).encode()
    models = list(MODELS)
    last = None
    for rnd in range(4):
        if time.time() > DEADLINE:
            raise RuntimeError("Zeitlimit erreicht")
        for model in list(models):
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    res = json.loads(r.read())
                parts = res["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
                time.sleep(8)  # Gratis-Stufe: nur wenige Anfragen pro Minute
                return json.loads(text)
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:300]
                last = f"{model}: HTTP {e.code} {msg}"
                log(f"{model}: HTTP {e.code}")
                if e.code in (401, 403):
                    raise RuntimeError("API-Schlüssel ungültig oder nicht freigeschaltet: " + last)
                if e.code in (400, 404):
                    # Modell gibt es nicht (mehr): streichen, genannten Nachfolger mitprobieren
                    models.remove(model)
                    for m in re.findall(r"models/([\w.\-]+)", msg):
                        if m != model and m not in models:
                            models.append(m)
            except Exception as e:
                last = f"{model}: {e}"
                log(last)
        if not models:
            break
        wait = 30 * (rnd + 1)
        log(f"Alle Modelle gerade ausgelastet, warte {wait} s")
        time.sleep(wait)
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


def is_placeholder(sent):
    t = sent.get("tokens") or []
    return len(t) <= 1 and (not t or t[0].get("art") == "Satz")


def sent_text(sent):
    return "".join(str(t.get("s", "")) for t in sent.get("tokens") or [] if isinstance(t, dict))


def ask_tokens(level, texts):
    res = gemini(JA_TOKEN_PROMPT.format(level=level, sents=json.dumps(texts, ensure_ascii=False)))
    got = res.get("saetze", []) if isinstance(res, dict) else []
    if len(got) != len(texts):
        raise RuntimeError(f"{len(got)} statt {len(texts)} Sätze zurück")
    out = []
    for g, txt in zip(got, texts):
        toks = g.get("tokens") if isinstance(g, dict) else None
        toks = [t for t in toks or [] if isinstance(t, dict) and t.get("s")]
        # Tokens müssen den Satz ergeben (Leerzeichen egal), sonst gilt der Satz als nicht erklärt
        a, b = re.sub(r"\s", "", "".join(t["s"] for t in toks)), re.sub(r"\s", "", txt)
        ok = toks and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9
        out.append(toks if ok else None)
    return out


def complete(level, obj):
    """Ergänzt fehlende Wort- und Kanji-Erklärungen. Gibt True zurück, wenn sich etwas geändert hat."""
    changed = False
    sents = obj.get("saetze") or []
    todo = [i for i, x in enumerate(sents) if is_placeholder(x)]
    size = 3
    while todo and time.time() < DEADLINE:
        part = todo[:size]
        try:
            res = ask_tokens(level, [sent_text(sents[i]) for i in part])
        except Exception as e:
            log(level, "Wort-Erklärungen fehlgeschlagen:", e)
            res = [None] * len(part)
        done = [i for i, t in zip(part, res) if t]
        for i, t in zip(part, res):
            if t:
                sents[i]["tokens"] = t
                changed = True
        if done:
            todo = [i for i in todo if i not in done]
            size = 3
        elif size > 1:
            size = 1  # einzeln nochmal probieren
        else:
            log(level, "Satz", part[0] + 1, "bleibt ohne Wort-Erklärung")
            todo = todo[1:]
    kanji = obj.get("kanji") if isinstance(obj.get("kanji"), dict) else {}
    used = {c for x in sents for c in KANJI_RE.findall(sent_text(x))} | set(KANJI_RE.findall(str(obj.get("titel", ""))))
    miss = sorted(used - set(kanji))
    for k in range(0, len(miss), 20):
        if time.time() > DEADLINE:
            break
        try:
            extra = gemini(JA_KANJI_FILL.format(chars="".join(miss[k:k + 20])))
            new = {c: v for c, v in extra.items() if isinstance(v, dict) and c in used}
            if new:
                kanji.update(new)
                changed = True
        except Exception as e:
            log(level, "Kanji-Erklärung fehlgeschlagen:", e)
    obj["kanji"] = kanji
    left = sum(is_placeholder(x) for x in sents), len(used - set(kanji))
    log(level, f"noch offen: {left[0]} Sätze ohne Wort-Erklärung, {left[1]} Kanji ohne Erklärung")
    return changed


def japanese():
    heads = []
    for f in JA_FEEDS:
        heads += read_feed(f, 10)
    day = NOW.toordinal()
    out = {"datum": TODAY, "v": JA_VERSION, "levels": {}}
    for i, lvl in enumerate(("N5", "N4", "N3")):
        head = None
        if lvl == "N5" or not heads:
            topic = f"{N5_TOPICS[(day + i * 7) % len(N5_TOPICS)]} (heute ist der {TODAY}, Jahreszeit passend)"
        else:
            head = heads[(day + i) % len(heads)]
            topic = ("Eine stark vereinfachte Nacherzählung dieser aktuellen japanischen Nachricht in eigenen Worten "
                     f"(keine Sätze übernehmen, keine Fakten erfinden): {head['titolo']} – {head['descrizione']}")
        try:
            # 1. Nur den Text schreiben (schnell); zu kurz oder zu wenig Kanji -> nochmal
            best = None
            for attempt in range(3):
                try:
                    cand = gemini(JA_TEXT_PROMPT.format(level=lvl, topic=topic, rules=JA_RULES[lvl]))
                except Exception as e:
                    log(lvl, "Versuch", attempt + 1, "fehlgeschlagen:", e)
                    continue
                cs = [x for x in cand.get("saetze", []) if isinstance(x, dict) and str(x.get("jp", "")).strip()]
                nk = len({c for x in cs for c in KANJI_RE.findall(x["jp"])})
                score = (len(cs) >= JA_MIN[lvl][0]) + (nk >= JA_MIN[lvl][1]), len(cs) + nk
                log(lvl, f"Versuch {attempt + 1}: {len(cs)} Sätze, {nk} Kanji")
                if cs and (best is None or score > best[0]):
                    best = (score, cand, cs)
                if score[0] == 2:
                    break
            if not best:
                raise RuntimeError("kein Text")
            _, obj, cs = best
            # 2. Wörter und Kanji erklären (Fehlendes holt der nächste Lauf nach)
            obj["saetze"] = [{"tokens": [{"s": x["jp"], "r": "", "de": x.get("de", ""), "art": "Satz"}],
                              "de": x.get("de", "")} for x in cs]
            obj["kanji"] = {}
            complete(lvl, obj)
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


def outdated(lang):
    """Japanische Tagesseite im alten Format (kurz, kaum Kanji)? Dann neu erzeugen."""
    if lang != "ja":
        return False
    try:
        with open(path_for(lang), encoding="utf-8") as f:
            return json.load(f).get("v", 1) < JA_VERSION
    except Exception:
        return True


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
        if os.path.exists(path_for(lang)) and not outdated(lang):
            log(lang, "für", TODAY, "gibt es schon")
            ok += 1
            continue
        try:
            save(lang, fn())
            ok += 1
            log(lang, "gespeichert")
        except Exception as e:
            log(lang, "Fehler:", e)
    # Fehlende Erklärungen der letzten Tage nachholen (heute zuerst)
    d = os.path.join(DATA, "ja")
    for f in sorted(os.listdir(d) if os.path.isdir(d) else [], reverse=True)[:4]:
        if time.time() > DEADLINE or not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f):
            continue
        fp = os.path.join(d, f)
        try:
            with open(fp, encoding="utf-8") as fh:
                day = json.load(fh)
            if day.get("v", 1) < JA_VERSION:
                continue
            changed = False
            for lvl, obj in (day.get("levels") or {}).items():
                changed |= complete(lvl, obj)
            if changed:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(day, fh, ensure_ascii=False, separators=(",", ":"))
                log(f, "ergänzt")
        except Exception as e:
            log(f, "Nachholen fehlgeschlagen:", e)
    rebuild_index()
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
