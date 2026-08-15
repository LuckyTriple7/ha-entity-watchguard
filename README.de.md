# Entity Watchguard

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/github/v/release/LuckyTriple7/ha-entity-watchguard)](https://github.com/LuckyTriple7/ha-entity-watchguard/releases)

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/luckytriple7)

[English](README.md) · **Deutsch**

Home-Assistant-Integration, die Entities auf den Zustand `unavailable` überwacht, sie pro Domain meldet und versucht, sie zurückzuholen — der über die Oberfläche konfigurierbare Ersatz für einen Stapel handgeschriebener `unavailable`-Template-Sensoren.

## Funktionen

- Ein `problem`-Binärsensor pro überwachter Domain (`light`, `switch`, `sensor`, `binary_sensor`, …), der die betroffenen Entities in seinen Attributen auflistet, dazu ein Gesamt-Problemsensor
- Überwachte Domains in der Oberfläche auswählen — die Auswahl bietet jede Domain an, die es in deiner Instanz gibt
- Ausnahmen per **Label**, **Entity**, **Gerät**, **Bereich**, **Integration** und **Regex-Muster** auf die Entity-ID
- Eskalierende Wiederherstellung: Stufe 1 fragt die Entity erneut ab (`homeassistant.update_entity`), Stufe 2 lädt den Config-Entry der zugehörigen Integration neu. Stufe 2 wiederholt sich in großem Abstand und gibt nach einer einstellbaren Zahl von Versuchen auf
- Stufe 1 wird bei Push-Integrationen (MQTT, ZHA, ESPHome …) automatisch übersprungen — erneutes Abfragen kann dort nichts bewirken
- Startkarenz: Nach einem Neustart von Home Assistant bleibt die Integration eine einstellbare Zeit still, weil Entities einige Minuten brauchen, bis sie da sind
- Drei Meldewege, jeder einzeln abschaltbar: **persistente Benachrichtigungen** (eine pro Domain, aktualisiert sich selbst, verschwindet automatisch, Entities pro Gerät gruppiert), **Reparatur-Hinweise** (pro Domain ignorierbar) und ein optionaler **Notify-Dienst** für Push aufs Handy
- Buttons **Jetzt prüfen** / **Wiederherstellen** für alles, worauf du nicht warten willst
- Mitgelieferte **Dashboard-Karte** mit Zeilen pro Domain, Ausfall-Details pro Entity und einer Ein-Klick-Aktion „diese Entity ignorieren"
- Schonend für die CPU: ein Scan im Arbeitsspeicher pro Intervall (Standard 60 s), kein Template-Rendering und keine State-Change-Listener. Lange Entity-Listen bleiben aus dem Recorder heraus

## Funktionsweise

In jedem Prüfintervall geht die Integration die Zustände der überwachten Domains durch und behält die, die `unavailable` und nicht ausgenommen sind. Jede solche Entity bekommt einen „Ausfall"-Eintrag mit dem Startzeitpunkt. Ab da:

```
unavailable erkannt
   ├─ Karenzzeit ........... kurzes Flattern wird ignoriert
   ├─ Stufe 1 .............. homeassistant.update_entity (bei Push-Integrationen übersprungen)
   ├─ Stufe 2 .............. Config-Entry neu laden — nur wenn genug davon
   │                         betroffen ist, wiederholt im Wiederholungsintervall
   ├─ Melde-Verzögerung .... Benachrichtigung / Reparatur-Hinweis / Notify-Dienst
   └─ aufgeben ............. keine Versuche mehr, Meldung bleibt
```

Der Eintrag verschwindet in dem Moment, in dem die Entity wieder verfügbar ist — jeder Timer startet beim nächsten Ausfall also von vorn.

## Dashboard-Karte

Eine Lovelace-Karte kommt mit der Integration und registriert sich selbst — es muss keine Ressource eingerichtet werden. Karte hinzufügen, nach **Entity Watchguard** suchen, oder per YAML:

```yaml
type: custom:entity-watchguard-card
title: Entity Watchguard      # optional
show_ok_domains: true         # auch Domains ohne Problem auflisten
show_buttons: true            # Jetzt prüfen / Wiederherstellen
allow_ignore: true            # Ignorieren-Aktion pro Entity
ignore_label: offline         # Label, das diese Aktion setzt
language: auto                # auto | de | en
```

- Eine Zeile pro überwachter Domain mit Zähler; Klick klappt die betroffenen Entities auf
- Jede Entity zeigt, seit wann sie weg ist, wie viele Wiederherstellungsversuche liefen und ob Watchguard aufgegeben hat
- Klick auf eine Entity öffnet deren more-info-Dialog
- Der Label-Button setzt dein Ignorier-Label auf diese Entity — ab dem nächsten Scan ist sie ausgenommen, sofern dieses Label unter Konfigurieren → Ausnahmen eingetragen ist. Das Label wird bei der ersten Verwendung angelegt
- Deutsch und Englisch; folgt der Home-Assistant-Sprache des Benutzers, oder per `language: de` / `en` festlegen
- Mit grafischem Editor

> Nach einem HACS-Update einen vollen **Neustart** machen (kein bloßer Reload) und den Browser hart neu laden — die Karte wird zwar mit versionsgestempelter URL ausgeliefert, das Frontend cacht aber hartnäckig.

## Installation über HACS

1. HACS öffnen → **Integrationen** → Menü (⋮) → **Benutzerdefinierte Repositories**
2. URL eintragen: `https://github.com/LuckyTriple7/ha-entity-watchguard`
3. Kategorie: **Integration** → **Hinzufügen**
4. Nach **Entity Watchguard** suchen → **Herunterladen**
5. Home Assistant neu starten

## Konfiguration

**Einstellungen → Geräte & Dienste → Integration hinzufügen → Entity Watchguard**, dann die zu überwachenden Domains wählen. Alles Weitere nutzt Standardwerte und lässt sich später unter **Konfigurieren** ändern:

| Schritt | Einstellung | Standard | Hinweise |
|---|---|---|---|
| Zeiten | Startverzögerung | 300 s | Zählt ab dem Moment, in dem HA fertig gestartet ist |
| Zeiten | Prüfintervall | 60 s | Wie oft die Zustände gescannt werden |
| Zeiten | Karenzzeit | 120 s | So lange muss eine Entity durchgehend nicht verfügbar sein, bevor sie gemeldet wird |
| Wiederherstellung | Stufe 1 (Entity aktualisieren) | an, nach 300 s | `homeassistant.update_entity` — sanft. Bei Push-Integrationen (`iot_class: *_push`) automatisch übersprungen, dort wäre es wirkungslos |
| Wiederherstellung | Stufe 2 (Config-Entry neu laden) | aus, nach 900 s | Wirksamer, aber alle Entities dieser Integration sind kurz weg |
| Wiederherstellung | Nur neu laden ab | 50 % | Anteil der Entities des Config-Entry, der nicht verfügbar sein muss. Hub-Integrationen (MQTT, ZHA, Z-Wave) haben **einen** Config-Entry für hunderte Entities — ohne diese Schwelle würde ein einzelner toter Sensor den ganzen Broker neu starten. `0` schaltet die Prüfung ab |
| Wiederherstellung | Reload-Cooldown | 3600 s | Mindestabstand zwischen zwei Reloads desselben Config-Entry |
| Wiederherstellung | Maximale Reloads pro Prüflauf | 3 | Schutz vor einem Reload-Sturm |
| Wiederherstellung | Stufe 2 wiederholen alle | 3600 s | `0` = Stufe 2 nur einmal pro Ausfall versuchen |
| Wiederherstellung | Aufgeben nach | 3 Versuchen | `0` = nie aufgeben. Ein Gerät, das schlicht ausgeschaltet ist, lohnt kein ewiges Neuladen; es bleibt gemeldet, nur ohne weitere Versuche |
| Ausnahmen | Labels | – | An Entity, Gerät oder Bereich gesetzt; z. B. ein `offline`-Label für bewusst abgeschaltete Geräte |
| Ausnahmen | Entities / Geräte / Bereiche | – | Explizite Auswahl |
| Ausnahmen | Integrationen | – | Alles, was diese Integration liefert, z. B. `shelly`, `mqtt`, `hue` — praktisch für ein ganzes System, das bewusst offline ist |
| Ausnahmen | Muster | – | Regex auf die Entity-ID, z. B. `.*_internet_access$` |
| Benachrichtigungen | Persistente Benachrichtigungen | an | Eine pro Domain, aktualisiert sich selbst, verschwindet automatisch. Entities desselben Geräts werden zu einer Zeile zusammengefasst |
| Benachrichtigungen | Reparatur-Hinweise | an | Spiegelt dieselben Ausfälle nach Einstellungen → Reparaturen, wo sie pro Domain ignoriert werden können |
| Benachrichtigungen | Benachrichtigen nach | 900 s | Gedacht für *nach* den fehlgeschlagenen Wiederherstellungsversuchen |
| Benachrichtigungen | Notify-Dienst | – | Optional, z. B. `notify.mobile_app_handy`. Wird nur gerufen, wenn eine Domain ein Problem bekommt oder wieder loswird, nie bei jedem Prüflauf |

Es wird nur eine Instanz unterstützt — sie überwacht die gesamte Home-Assistant-Instanz.

## Entities

| Entity | Typ | Beschreibung |
|---|---|---|
| `binary_sensor.entity_watchguard_<domain>` | problem | AN, wenn die Domain nicht verfügbare Entities hat. Attribute: `count`, `unavailable_entities`, `unavailable_names`, `unavailable_since`, `recovery_attempts`, `given_up_entities`, `details` (Zeilen pro Entity: `entity_id`, `name`, `since`, `attempts`, `given_up`), `status`, `truncated` |
| `binary_sensor.entity_watchguard_problem` | problem | AN, wenn irgendeine überwachte Domain ein Problem hat. Attribute: `affected_domains`, `unavailable_entities` |
| `sensor.entity_watchguard_unavailable_entities` | Anzahl | Summe über alle überwachten Domains, Aufschlüsselung `per_domain` in den Attributen |
| `sensor.entity_watchguard_last_recovery_attempt` | Zeitstempel | Diagnose |
| `button.entity_watchguard_check_now` | Button | Sofort scannen, statt auf das Prüfintervall zu warten — beendet außerdem die Startkarenz vorzeitig |
| `button.entity_watchguard_recover_now` | Button | Stufe 1 für alles gerade Nichtverfügbare, ohne die Wartezeiten |

Während der Startkarenz bleibt jeder Sensor `off` und meldet `status: warming_up`.

Die Entity-Listen sind bei 50 Einträgen gekappt (`truncated: true` zeigt, dass es mehr waren; `count` bleibt immer exakt) und aus dem Recorder ausgenommen — ein großer Ausfall schreibt so nicht bei jedem Scan dieselbe lange Liste in die Datenbank.

## Dienste

- `entity_watchguard.recover_now` — sofort wiederherstellen, unabhängig von den eingestellten Wartezeiten. Optional `domain`, `entity_id` und `escalate: true`, um auch Stufe 2 auszuführen.
- `entity_watchguard.clear_notifications` — verwirft alle Benachrichtigungen und Reparatur-Hinweise dieser Integration.

## Protokollierung

Alles landet im normalen Home-Assistant-Log unter `custom_components.entity_watchguard`:

| Stufe | Was |
|---|---|
| INFO | Entities, die nicht verfügbar werden und zurückkommen (inklusive Dauer und gelaufener Wiederherstellungsstufen), Versuche in Stufe 1 und 2 |
| WARNING | Ein Ausnahme-Muster, das kein gültiges Regex ist (es wird übersprungen) |
| ERROR | Ein fehlgeschlagener Config-Entry-Reload aus Stufe 2, mit Traceback |
| DEBUG | Wann die Startkarenz endet, übersprungene Reloads, abgeschlossene Reloads |

```yaml
logger:
  logs:
    custom_components.entity_watchguard: debug
```

## Entwicklung

```bash
pip install -r requirements_test.txt
pytest                    # Integrationstests
node tests/card/smoke.js  # rendert die Karte gegen DOM-Stubs, ohne Abhängigkeiten
```

Der Kartentest prüft das erzeugte HTML — dass keine frontend-internen Elemente verwendet werden, dass nichts als `undefined` gerendert wird und dass die Sprachumschaltung greift. Beide Testläufe laufen bei jedem Push in der CI, zusammen mit hassfest und der HACS-Prüfung.

## Hinweise

- Entities, die nicht in der Entity-Registry stehen (YAML-/Template-Entities), lassen sich nur über **Muster** oder die **Entity**-Auswahl ausnehmen; Label-, Geräte-, Bereichs- und Integrations-Ausnahmen brauchen einen Registry-Eintrag.
- Stufe 2 lädt nie den eigenen Config-Entry von Entity Watchguard neu, überspringt nicht geladene Entries und hält den Cooldown ein.
- Die Push-Erkennung liest `iot_class` aus dem Manifest der Integration. Was sich nicht auflösen lässt, gilt als abfragbar — ein harmloser Dienstaufruf ist billiger als eine verpasste Wiederherstellung.
- **Es wird nichts angezeigt?** Sieh dir das Attribut `status` eines Domain-Sensors an: `warming_up` heißt, die Startverzögerung läuft noch (mit **Jetzt prüfen** beenden), `ok` bei `count: 0` heißt, es hat nichts gepasst — prüfe, ob die Domain wirklich überwacht wird und ob die Entities `unavailable` sind und nicht `unknown`.
- Template-Sensoren ersetzen: `label_entities('offline')` entspricht den Label-Ausnahmen, `rejectattr('entity_id', 'match', '.*_internet_access$')` den Muster-Ausnahmen.
