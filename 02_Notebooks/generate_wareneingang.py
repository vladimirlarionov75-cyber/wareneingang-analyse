# -*- coding: utf-8 -*-
"""
generate_wareneingang.py
Erzeugt synthetische (erfundene) Prozessdaten für den Wareneingang der MainLogistik GmbH.
Ergebnis: wareneingang_roh.csv (Semikolon als Trennzeichen, UTF-8)

Die Daten enthalten keine personenbezogenen Angaben.
Der Zufallsgenerator hat einen festen Startwert (42). Darum entstehen bei jedem Lauf dieselben Daten.
"""
import numpy as np
import pandas as pd
from pathlib import Path



rng = np.random.default_rng(42)

# Lieferanten: Anteil an allen Lieferungen, Faktor für Verzögerungen, Anteil der angekündigten Lieferungen
lief = pd.DataFrame(
    {"anteil":   [0.22, 0.18, 0.15, 0.12, 0.10, 0.09, 0.08, 0.06],
     "faktor":   [1.00, 1.00, 1.25, 0.95, 1.00, 1.10, 1.30, 0.90],
     "avisiert": [0.95, 0.90, 0.55, 0.90, 0.85, 0.80, 0.60, 0.95]},
    index=["LF01", "LF02", "LF03", "LF04", "LF05", "LF06", "LF07", "LF08"])

# Warenarten: Anteil, mittlere Palettenzahl, typische Kontrollzeit in Minuten
waren = pd.DataFrame(
    {"anteil":    [0.45, 0.20, 0.15, 0.08, 0.12],
     "paletten":  [7, 5, 4, 3, 2],
     "kontrolle": [10, 18, 20, 30, 12]},
    index=["Trockenware", "Kühlware", "Elektronik", "Gefahrgut", "Sperrgut"])

# ---------------------------------------------------------------
# 1. Ankunftszeiten erzeugen (eine Zeile = eine Lieferung)
# ---------------------------------------------------------------
tage = pd.bdate_range("2027-01-04", "2027-03-31")                    # nur Montag bis Freitag
tage = tage[~tage.isin(pd.to_datetime(["2027-01-06", "2027-03-26"]))]  # ohne Feiertage (Bayern)

ankuenfte = []
for tag in tage:
    # Montag hat die meisten Lieferungen, Mittwoch und Freitag die wenigsten
    mittel = 35 * [1.10, 1.00, 0.95, 1.00, 0.95][tag.weekday()]
    n_tag = int(max(20, round(rng.normal(mittel, 4))))
    # Ankunftsstunde 6 bis 16 Uhr, Spitze am Vormittag
    stunden = rng.choice(np.arange(6, 17), size=n_tag,
                         p=[0.05, 0.12, 0.16, 0.16, 0.14, 0.10, 0.05, 0.08, 0.08, 0.05, 0.01])
    minuten = rng.integers(0, 60, n_tag)
    sekunden = rng.integers(0, 60, n_tag)
    ankuenfte.extend(tag + pd.to_timedelta(stunden, unit="h")
                         + pd.to_timedelta(minuten, unit="m")
                         + pd.to_timedelta(sekunden, unit="s"))

df = pd.DataFrame({"ts_ankunft": ankuenfte}).sort_values("ts_ankunft").reset_index(drop=True)
n = len(df)
df["lieferung_id"] = [f"L-2027-{i:05d}" for i in range(1, n + 1)]

# ---------------------------------------------------------------
# 2. Merkmale der Lieferungen
# ---------------------------------------------------------------
df["lieferant_id"] = rng.choice(lief.index, size=n, p=lief["anteil"])
df["warenart"] = rng.choice(waren.index, size=n, p=waren["anteil"])
df["anzahl_paletten"] = np.clip(1 + rng.poisson(df["warenart"].map(waren["paletten"])), 1, 25)
df["anzahl_positionen"] = np.clip(1 + rng.poisson(0.9 * df["anzahl_paletten"]), 1, 40)
df["avisiert"] = np.where(rng.random(n) < df["lieferant_id"].map(lief["avisiert"]), "ja", "nein")

# ---------------------------------------------------------------
# 3. Dauer der Prozessschritte (in Minuten) und Zeitstempel
# ---------------------------------------------------------------
def lognorm(median, sigma):
    """Zufallszeiten mit schiefer Verteilung: viele kurze, wenige sehr lange Zeiten."""
    return rng.lognormal(np.log(median), sigma, n)

def plus(zeit, minuten):
    """Addiert Minuten zu einem Zeitstempel."""
    return zeit + pd.to_timedelta(np.round(minuten * 60), unit="s")

# Einflussfaktoren (Hilfsspalten, am Ende der Datei werden sie entfernt)
df["f_lieferant"] = df["lieferant_id"].map(lief["faktor"])
df["f_tag"] = df["ts_ankunft"].dt.weekday.map({0: 1.20, 1: 1.00, 2: 0.95, 3: 1.00, 4: 1.10})   # Montag am langsamsten
# Auslastung: je mehr Lieferungen in derselben Stunde ankommen, desto länger dauert die Annahme
df["f_last"] = 1 + 0.03 * df.groupby([df["ts_ankunft"].dt.date, df["ts_ankunft"].dt.hour])["ts_ankunft"].transform("count")

df["ts_annahme"] = plus(df["ts_ankunft"],
    lognorm(10, 0.5) * df["f_last"] * df["f_tag"] * df["f_lieferant"] * np.where(df["avisiert"] == "ja", 1.0, 1.5)
    + 1.5 * df["anzahl_paletten"] * lognorm(1, 0.2))

df["ts_kontrolle"] = plus(df["ts_annahme"],
    lognorm(df["warenart"].map(waren["kontrolle"]), 0.3) * df["f_lieferant"]
    + 0.7 * df["anzahl_positionen"])

df["ts_erfassung"] = plus(df["ts_kontrolle"],
    lognorm(7, 0.35) * df["f_tag"] * np.where(df["warenart"] == "Elektronik", 1.5, 1.0)
    + 0.8 * df["anzahl_positionen"])

df["ts_einlagerung_bereit"] = plus(df["ts_erfassung"],
    lognorm(9, 0.3) + df["anzahl_paletten"] * lognorm(1, 0.2))

df = df[["lieferung_id", "lieferant_id", "warenart", "anzahl_paletten", "anzahl_positionen", "avisiert",
         "ts_ankunft", "ts_annahme", "ts_kontrolle", "ts_erfassung", "ts_einlagerung_bereit"]].copy()

# ---------------------------------------------------------------
# 4. Typische Datenfehler einbauen (für die Datenqualitätsprüfung)
#    Jede Zeile bekommt höchstens einen Fehler.
# ---------------------------------------------------------------
zufall = rng.permutation(n)                    # Zeilennummern in zufälliger Reihenfolge
a = round(n * 0.02)                            # 2 %   fehlende Zeitstempel
b = a + round(n * 0.01)                        # 1 %   Kontrolle vor Annahme
c = b + round(n * 0.02)                        # 2 %   falsche Schreibweise
d = c + round(n * 0.005)                       # 0,5 % Ausreißer
e = d + round(n * 0.003)                       # 0,3 % Tippfehler bei den Paletten
fehlend, unmoeglich, schreibweise, ausreisser, palette = \
    zufall[:a], zufall[a:b], zufall[b:c], zufall[c:d], zufall[d:e]

# 4.1 Fehlende Zeitstempel
for i in fehlend:
    spalte = rng.choice(["ts_annahme", "ts_kontrolle", "ts_erfassung", "ts_einlagerung_bereit"])
    df.loc[i, spalte] = pd.NaT

# 4.2 Unmögliche Zeiten: Kontrolle liegt VOR der Annahme
for i in unmoeglich:
    df.loc[i, "ts_kontrolle"] = df.loc[i, "ts_annahme"] - pd.Timedelta(minutes=int(rng.integers(5, 60)))

# 4.3 Uneinheitliche Schreibweisen bei der Warenart
varianten = {
    "Kühlware": ["kuehlware", "Kühlware ", " KÜHLWARE"],
    "Trockenware": ["trockenware", "Trockenware "],
    "Elektronik": ["elektronik", "Elektronik "],
    "Gefahrgut": ["gefahrgut", "Gefahrgut "],
    "Sperrgut": ["Sperrgut ", "sperrgut"],
}
for i in schreibweise:
    df.loc[i, "warenart"] = str(rng.choice(varianten[df.loc[i, "warenart"]]))

# 4.4 Ausreißer: "Bereit zur Einlagerung" wurde erst am nächsten Tag gebucht
for i in ausreisser:
    df.loc[i, "ts_einlagerung_bereit"] += pd.Timedelta(days=1)

# 4.5 Tippfehler bei der Palettenzahl (0 oder 99)
for i in palette:
    df.loc[i, "anzahl_paletten"] = int(rng.choice([0, 99]))

# 4.6 Doppelte Zeilen (dieselbe Lieferung wurde zweimal exportiert)
df = pd.concat([df, df.sample(n=round(n * 0.005), random_state=42)])
df = df.sort_values("lieferung_id", kind="stable").reset_index(drop=True)

# ---------------------------------------------------------------
# 5. Speichern
# ---------------------------------------------------------------

pfad = Path(__file__).parent.parent / "01_Rohdaten" / "wareneingang_roh.csv"

df.to_csv(pfad, sep=";", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S")

print("Datei gespeichert: wareneingang_roh.csv")
print("Zeilen:", len(df), "| Spalten:", df.shape[1])
print("Zeitraum:", df["ts_ankunft"].min(), "bis", df["ts_ankunft"].max())
print("Arbeitstage:", df["ts_ankunft"].dt.date.nunique())
