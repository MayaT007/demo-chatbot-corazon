import requests
import spacy
from flask import Flask, request, jsonify, send_file, render_template
from datetime import datetime, timedelta
import os
from fpdf import FPDF
import re
from rapidfuzz import fuzz
import csv 
import json

API_BASE = os.environ.get("INVOICE_API_URL", "").rstrip("/")

# Lade spaCy Modell
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_nlp():
    try:
        return spacy.load(os.path.join(BASE_DIR, "modell_maya"))  # dein Modell
    except Exception as e:
        print("[spaCy] modell_maya nicht geladen:", e)
        # Fallback (nur falls du willst):
        try:
            return spacy.load("de_core_news_sm")
        except Exception:
            import spacy.cli
            spacy.cli.download("de_core_news_sm")
            return spacy.load("de_core_news_sm")

nlp = load_nlp()

app = Flask(__name__)
app.secret_key = "geheimeschluessel"

if not os.path.exists('chat_logs'):
    os.makedirs('chat_logs')
if not os.path.exists('pdf_rechnungen'):
    os.makedirs('pdf_rechnungen')

benutzer_status = {}

faq_daten = {
    "wie kann ich bezahlen?": {
        "de": "Sie können per Banküberweisung oder Kreditkarte bezahlen.",
        "en": "You can pay via bank transfer or credit card."
    },
    "wie erreiche ich den support?": {
        "de": "Sie können uns unter support@firma.de erreichen.",
        "en": "You can reach us at support@company.com."
    },
    "wie kontaktiere ich den support?": {
        "de": "Sie können uns unter support@firma.de erreichen.",
        "en": "You can reach us at support@company.com."
    },
    "wie bekomme ich hilfe?": {
        "de": "Unser Support-Team ist unter support@firma.de erreichbar.",
        "en": "Our support team can be reached at support@company.com."
    },
    "wann kommt meine rechnung?": {
        "de": "Ihre Rechnung wird jeden Monat am 5. verschickt.",
        "en": "Your invoice is sent on the 5th of each month."
    },
    "wie hoch soll die rate sein?": {
        "de": "Bitte geben Sie den gewünschten Betrag für die Ratenzahlung an.",
        "en": "Please provide the desired amount for the installment payment."
    }
}

standard_antworten = {
    "rechnung_abfragen": "📄 Ich helfe Ihnen bei Ihrer Rechnung. Bitte geben Sie Ihre Rechnungsnummer an.",
    "zahlung_abfragen": "✅ Ihre Zahlung ist eingegangen. Vielen Dank!",
    "mahnen": "⚠️ Es scheint, dass eine Mahnung unterwegs ist. Ich leite Sie weiter.",
    "punkte_abfragen": "⭐ Ihr aktueller Punktestand beträgt 120 Punkte.",
    "zahlungsplan_angebot": "🧾 Sie können eine Ratenzahlung vereinbaren. Wie viel möchten Sie monatlich zahlen?",
    "adresse_aendern": "🏡 Um Ihre Adresse zu ändern, füllen Sie bitte unser Adressformular aus.",
    "zahlungsfrist_verlaengern": "🕒 Eine Verlängerung der Zahlungsfrist kann beantragt werden. Ich leite Sie gerne weiter.",
    "kontakt_mitarbeiter": "📞 Ich verbinde Sie mit einem Mitarbeiter. Bitte einen Moment Geduld.",
    "unbekannt": "❓ Ich habe Ihre Anfrage leider nicht verstanden. Können Sie es bitte anders formulieren?"
}

def erstelle_ratenplan_pdf(rechnungsnummer, gesamtschuld, monatsrate):
    dateiname = f"pdf_rechnungen/Ratenplan_{rechnungsnummer}.pdf"
    pdf = FPDF()
    pdf.add_page()

    # Dein Logo einfügen (Pfad anpassen!)
    logo_pfad = "static/IMG_7829.png"
    if os.path.exists(logo_pfad):
        pdf.image(logo_pfad, x=10, y=8, w=30)

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Ratenzahlungsvereinbarung", ln=True, align="C")
    pdf.ln(20)

    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Rechnungsnummer: {rechnungsnummer}", ln=True)
    pdf.cell(0, 10, f"Gesamtschulden: {gesamtschuld:.2f} Euro", ln=True)
    pdf.cell(0, 10, f"Vorgeschlagene Monatsrate: {monatsrate:.2f} Euro", ln=True)

    laufzeit = int(gesamtschuld // monatsrate)
    if gesamtschuld % monatsrate > 0:
        laufzeit += 1

    pdf.cell(0, 10, f"Voraussichtliche Laufzeit: {laufzeit} Monate", ln=True)

    pdf.ln(20)
    pdf.multi_cell(0, 10, "Bitte bestätigen Sie diesen Ratenzahlungsplan, indem Sie das folgende Dokument unterschreiben und zurücksenden.\n\n_____________________________\nUnterschrift")

    pdf.output(dateiname)
    return dateiname


def verstehe_absicht(text):
    t = text.lower()

    # Regelbasiert (deine bestehenden Schlüsselwörter – funktioniert schon gut)
    if any(w in t for w in ["ratenzahlung", "teilzahlung", "rate vereinbaren", "zahlungsplan", "in raten"]):
        return "zahlungsplan_angebot"
    if any(w in t for w in ["rechnung", "rechnungsnummer", "invoice", "bill"]):
        return "rechnung_abfragen"
    if any(w in t for w in ["zahlung eingegangen", "zahlung bestätigt", "zahlung erfolgt", "habe bezahlt"]):
        return "zahlung_abfragen"
    if any(w in t for w in ["mahnung", "mahnen", "zahlungserinnerung"]):
        return "mahnen"
    if any(w in t for w in ["punkte", "punktestand", "bonuspunkte"]):
        return "punkte_abfragen"
    if any(w in t for w in ["adresse ändern", "anschrift ändern", "neue adresse", "adressänderung"]):
        return "adresse_aendern"
    if any(w in t for w in ["mitarbeiter sprechen", "support kontaktieren", "callcenter", "mit mensch sprechen", "berater"]):
        return "kontakt_mitarbeiter"
    if any(w in t for w in ["frist", "verlängerung", "aufschub", "zahlung verschieben"]):
        return "zahlungsfrist_verlaengern"

      try:
        doc = nlp(t)
        absichten = getattr(doc, "cats", None) or {}
        if absichten:
            beste_absicht = max(absichten, key=absichten.get)
            if absichten[beste_absicht] >= 0.6:
                return beste_absicht
    except Exception:
        pass

    return "unbekannt"


def speichere_chat(user_text, bot_text):
    heute = datetime.now().strftime("%Y%m%d")  # z.B. 20240429
    dateiname = f"chat_logs/chat_{heute}.json"

    eintrag_user = {
        "zeit": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "sender": "Benutzer",
        "nachricht": user_text
    }

    eintrag_bot = {
        "zeit": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "sender": "Maya",
        "nachricht": bot_text
    }

    daten = []

    # Bestehende Datei laden (falls vorhanden)
    if os.path.exists(dateiname):
        with open(dateiname, "r", encoding="utf-8") as f:
            try:
                daten = json.load(f)
            except json.JSONDecodeError:
                daten = []

    # Neue Einträge hinzufügen
    daten.append(eintrag_user)
    daten.append(eintrag_bot)

    # Datei speichern
    with open(dateiname, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=4, ensure_ascii=False)

def erkenne_entity(text):
    betraege = re.findall(r"\d+[.,]?\d*\s*€?", text)
    rechnungsnummern = re.findall(r"\b\d{5,10}\b", text)
    return {"betrag": betraege, "rechnungsnummer": rechnungsnummern}

def finde_aehnliche_frage(benutzertext):
    benutzertext = benutzertext.strip().lower()
    for frage, antwort in faq_daten.items():
        score = fuzz.partial_ratio(benutzertext, frage.lower())
        if score > 75:
            return antwort
    return None

def erkenne_stimmung(text):
    text = text.lower()
    if any(wort in text for wort in ["schlimm", "verzweifelt", "hilfe", "weiß nicht weiter", "problem", "ängstlich"]):
        return "traurig"
    elif any(wort in text for wort in ["wütend", "unverschämtheit", "schon 5x", "beschwerde", "sauer", "genervt"]):
        return "frustriert"
    elif any(wort in text for wort in ["bitte", "guten tag", "hallo", "danke", "freundlich", "grüße"]):
        return "freundlich"
    else:
        return "neutral"

def stimmung_anpassen(antwort, stimmung):
    if stimmung == "frustriert":
        antwort += " 🙏 Ich verstehe Ihren Ärger. Ich kümmere mich sofort darum!"
    elif stimmung == "traurig":
        antwort += " 💬 Keine Sorge, wir finden gemeinsam eine Lösung!"
    elif stimmung == "freundlich":
        antwort += " 😊 Vielen Dank für Ihre freundliche Anfrage."
    return antwort


def ticket_erstellen(benutzertext, absicht):
    if not os.path.exists('tickets'):
        os.makedirs('tickets')

    ticket_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

    ticket_datei = "tickets/tickets.csv"
    ticket_daten = [ticket_id, timestamp, absicht, benutzertext, "Offen"]

    # Wenn Datei noch nicht existiert: Kopfzeile schreiben
    if not os.path.exists(ticket_datei):
        with open(ticket_datei, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["Ticket-ID", "Zeit", "Absicht", "Anfrage", "Status"])

    # Ticket-Daten hinzufügen
    with open(ticket_datei, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(ticket_daten)

@app.route("/chat", methods=["POST"])
def chat():
    daten = request.get_json()
    benutzertext = daten.get("nachricht", "").lower()
    
    user_id = daten.get("user_id", "default")
    stimmung = erkenne_stimmung(benutzertext)
    print(f"DEBUG: erkannte Stimmung: {stimmung}")
    entities = erkenne_entity(benutzertext)

    if user_id not in benutzer_status:
        benutzer_status[user_id] = {
            "status": "normal",
            "last_activity": datetime.now(),
            "rechnungsnummer": None,
            "monatsrate": None,
            "sprache": "de"
        }

    status = benutzer_status[user_id]
    jetzt = datetime.now()
    if jetzt - status["last_activity"] > timedelta(minutes=5):
        status["status"] = "normal"
    status["last_activity"] = jetzt

    if "sprache englisch" in benutzertext or "language english" in benutzertext:
        benutzer_status[user_id]["sprache"] = "en"
        return send_response(benutzertext, "✅ Language switched to English. How can I assist you?")

    if "sprache deutsch" in benutzertext or "language german" in benutzertext:
        benutzer_status[user_id]["sprache"] = "de"
        return send_response(benutzertext, "✅ Sprache auf Deutsch gewechselt. Wie kann ich Ihnen helfen?")

    antwort = finde_aehnliche_frage(benutzertext)
    if antwort:
        return send_response(benutzertext, antwort[benutzer_status[user_id]["sprache"]])

    if "herunterladen" in benutzertext and "rechnung" in benutzertext:
        if entities["rechnungsnummer"]:
            rechnungsnummer = entities["rechnungsnummer"][0]
            try:
                api_url = f"{API_BASE}/api/rechnung/{rechnungsnummer}"
                response = requests.get(api_url)
                if response.status_code == 200:
                    daten = response.json()
                    dateiname = erstelle_pdf_rechnung(daten['rechnungsnummer'], daten['betrag'], daten['status'])
                    antwort = {
                        "de": f"✅ Ihre PDF-Rechnung ist bereit: [Hier herunterladen](/download/{os.path.basename(dateiname)})",
                        "en": f"✅ Your PDF invoice is ready: [Download here](/download/{os.path.basename(dateiname)})"
                    }[benutzer_status[user_id]["sprache"]]
                else:
                    antwort = "❗ Die Rechnung wurde nicht gefunden."
            except Exception:
                antwort = "❗ Fehler beim Erstellen der PDF-Rechnung."
        else:
            antwort = {
                "de": "❗ Bitte geben Sie die Rechnungsnummer an, die Sie herunterladen möchten.",
                "en": "❗ Please provide the invoice number you want to download."
            }[benutzer_status[user_id]["sprache"]]
        return send_response(benutzertext, antwort)

    if entities["rechnungsnummer"]:
        rechnungsnummer = entities["rechnungsnummer"][0]
        try:
            api_url = f"{API_BASE}/api/rechnung/{rechnungsnummer}"
            response = requests.get(api_url)
            if response.status_code == 200:
                daten = response.json()
                antwort = {
                    "de": f"📄 Rechnung {daten.get('rechnungsnummer', 'N/A')}: Betrag: {daten.get('betrag', 'N/A')}€, Status: {daten.get('status', 'N/A')}",
                    "en": f"📄 Invoice {daten.get('rechnungsnummer', 'N/A')}: Amount: {daten.get('betrag', 'N/A')}€, Status: {daten.get('status', 'N/A')}"
                }[benutzer_status[user_id]["sprache"]]
            else:
                antwort = "❗ Die Rechnung wurde nicht gefunden."
        except Exception:
            antwort = "❗ Fehler beim Abrufen der Rechnungsdaten."
        return send_response(benutzertext, antwort)

    # ➔ Prüfe auf Monatsratenstatus
    if status["status"] == "warte_auf_monatsrate":
        

        entities = erkenne_entity(benutzertext)
        betraege = entities.get("betrag", [])

        if betraege:
            eingabe_betrag = betraege[0].replace("€", "").replace(",", ".").strip()
            try:
                monatliche_rate = float(eingabe_betrag)

                if monatliche_rate < 30:
                    status["status"] = "warte_auf_vorschlagsrate"
                    status["vorschlaege"] = [30, 40, 50]
                    antwort = {
                        "de": "❗ Die monatliche Rate ist zu niedrig.\n"
                              "💬 Vorschläge: 30€, 40€, 50€.\n"
                              "Bitte wählen Sie einen Betrag aus.",
                        "en": "❗ The monthly installment is too low.\n"
                              "💬 Suggestions: 30€, 40€, 50€.\n"
                              "Please choose an amount."
                    }[benutzer_status[user_id]["sprache"]]
                else:
                    gesamtschuld = 300.0

                    laufzeit_monate = int(gesamtschuld // monatliche_rate)
                    if gesamtschuld % monatliche_rate > 0:
                        laufzeit_monate += 1

                    rechnungsnummer = "RATENPLAN_" + datetime.now().strftime("%Y%m%d%H%M%S")
                    pdf_dateiname = erstelle_ratenplan_pdf(rechnungsnummer, gesamtschuld, monatliche_rate)

                    download_link = "/download/" + os.path.basename(pdf_dateiname)

                    antworten = {
                        "de": "✅ Ihr Zahlungsplan mit {:.2f}€/Monat wurde vorgemerkt.<br>"
                              "Voraussichtliche Laufzeit: {} Monate.<br><br>"
                              '<a href="{}" style="display:inline-block; background-color:#e74c3c; color:white; padding:8px 16px; text-align:center; text-decoration:none; font-size:14px; border-radius:12px;">📄 Ratenplan herunterladen</a>'.format(monatliche_rate, laufzeit_monate, download_link),
                        "en": "✅ Your installment plan with {:.2f}€/month has been noted.<br>"
                              "Expected duration: {} months.<br><br>"
                              '<a href="{}" style="display:inline-block; background-color:#e74c3c; color:white; padding:8px 16px; text-align:center; text-decoration:none; font-size:14px; border-radius:12px;">📄 Download Installment Plan</a>'.format(monatliche_rate, laufzeit_monate, download_link)
                    }

                    antwort = antworten[benutzer_status[user_id]["sprache"]]
                    status["status"] = "normal"

            except ValueError:
                antwort = {
                    "de": "❗ Ungültiger Betrag. Bitte geben Sie eine Zahl an (z.B. 50).",
                    "en": "❗ Invalid amount. Please enter a number (e.g., 50)."
                }[benutzer_status[user_id]["sprache"]]
        else:
            antwort = {
                "de": "❗ Bitte geben Sie eine gültige Monatsrate in Euro an.",
                "en": "❗ Please provide a valid monthly amount in Euros."
            }[benutzer_status[user_id]["sprache"]]

        return send_response(benutzertext, antwort)

    # ➔ Prüfe auf Vorschlagsrate
    if status["status"] == "warte_auf_vorschlagsrate":
        

        entities = erkenne_entity(benutzertext)
        betraege = entities.get("betrag", [])

        if betraege:
            eingabe_betrag = betraege[0].replace("€", "").replace(",", ".").strip()
            try:
                neue_rate = float(eingabe_betrag)
                print("DEBUG: Betrag erkannt:", neue_rate)

                if neue_rate in status.get("vorschlaege", []):
                    gesamtschuld = 300.0

                    laufzeit_monate = int(gesamtschuld // neue_rate)
                    if gesamtschuld % neue_rate > 0:
                        laufzeit_monate += 1

                    rechnungsnummer = "RATENPLAN_" + datetime.now().strftime("%Y%m%d%H%M%S")
                    pdf_dateiname = erstelle_ratenplan_pdf(rechnungsnummer, gesamtschuld, neue_rate)

                    download_link = "/download/" + os.path.basename(pdf_dateiname)

                    antworten = {
                        "de": "✅ Ihr Zahlungsplan mit {:.2f}€/Monat wurde erstellt.<br>"
                              "Voraussichtliche Laufzeit: {} Monate.<br><br>"
                              '<a href="{}" style="display:inline-block; background-color:#e74c3c; color:white; padding:8px 16px; text-align:center; text-decoration:none; font-size:14px; border-radius:12px;">📄 Ratenplan herunterladen</a>'.format(neue_rate, laufzeit_monate, download_link),
                        "en": "✅ Your installment plan with {:.2f}€/month has been created.<br>"
                              "Expected duration: {} months.<br><br>"
                              '<a href="{}" style="display:inline-block; background-color:#e74c3c; color:white; padding:8px 16px; text-align:center; text-decoration:none; font-size:14px; border-radius:12px;">📄 Download Installment Plan</a>'.format(neue_rate, laufzeit_monate, download_link)
                    }

                    antwort = antworten[benutzer_status[user_id]["sprache"]]
                    status["status"] = "normal"

                else:
                    antwort = {
                        "de": "❗ Bitte wählen Sie eine gültige vorgeschlagene Rate (30€, 40€, 50€).",
                        "en": "❗ Please choose one of the suggested rates (30€, 40€, or 50€)."
                    }[benutzer_status[user_id]["sprache"]]
            except ValueError:
                antwort = {
                    "de": "❗ Ungültige Eingabe. Bitte geben Sie eine gültige Zahl an.",
                    "en": "❗ Invalid input. Please enter a valid number."
                }[benutzer_status[user_id]["sprache"]]
        else:
            antwort = {
                "de": "❗ Bitte geben Sie eine gültige Zahl an (z.B. 30, 40, 50).",
                "en": "❗ Please enter a valid number (e.g., 30, 40, 50)."
            }[benutzer_status[user_id]["sprache"]]

        return send_response(benutzertext, antwort)

    # ➔ Standard: Normal weiter mit Intent-Handling
  
    absicht = verstehe_absicht(benutzertext)


    if absicht == "rechnung_abfragen":
        antwort = {
            "de": "📄 Bitte geben Sie Ihre Rechnungsnummer an.",
            "en": "📄 Please provide your invoice number."
        }[benutzer_status[user_id]["sprache"]]
        status["status"] = "warte_auf_rechnungsnummer"
    elif absicht == "zahlungsplan_angebot":
        antwort = {
            "de": "🧾 Wie hoch soll Ihre monatliche Rate sein? Bitte Betrag angeben.",
            "en": "🧾 How much would you like to pay per month? Please provide the amount."
        }[benutzer_status[user_id]["sprache"]]
        status["status"] = "warte_auf_monatsrate"
    elif absicht == "zahlung_abfragen":
        antwort = {
            "de": "✅ Ihre Zahlung ist eingegangen. Vielen Dank!",
            "en": "✅ Your payment has been received. Thank you!"
        }[benutzer_status[user_id]["sprache"]]
        antwort = stimmung_anpassen(antwort, stimmung)

    elif absicht in ["mahnen", "kontakt_mitarbeiter", "zahlungsfrist_verlaengern"]:
        antwort = {
            "de": "📞 Ihre Anfrage wird an unser Team weitergeleitet. Sie erhalten bald eine Rückmeldung.",
            "en": "📞 Your request has been forwarded to our team. You will receive a response soon."
        }[benutzer_status[user_id]["sprache"]]
        ticket_erstellen(benutzertext, absicht)

    elif absicht == "punkte_abfragen":
        antwort = {
            "de": "⭐ Ihr aktueller Punktestand beträgt 120 Punkte.",
            "en": "⭐ Your current point balance is 120 points."
        }[benutzer_status[user_id]["sprache"]]
    elif absicht == "adresse_aendern":
        antwort = {
            "de": "🏡 Bitte füllen Sie unser Adressformular zur Adressänderung aus.",
            "en": "🏡 Please fill out our address change form."
        }[benutzer_status[user_id]["sprache"]]
    
    else:
        antwort = {
            "de": "❓ Ich habe Ihre Anfrage leider nicht genau verstanden.",
            "en": "❓ I didn't quite understand your request."
        }[benutzer_status[user_id]["sprache"]]

    
    antwort = stimmung_anpassen(antwort, stimmung)
    return send_response(benutzertext, antwort)

def send_response(benutzertext, antwort):
    speichere_chat(benutzertext, antwort)
    return jsonify({"antwort": antwort})



@app.route("/download/<path:filename>")
def download_file(filename):
    pfad = os.path.join("pdf_rechnungen", filename)
    return send_file(pfad, as_attachment=True)

@app.route("/")
def index():
    begruessungstext = "Willkommen! Ich bin Maya, Ihre KI-Assistentin. Ich helfe Ihnen bei Rechnungen, Inkasso und Mahnungen."
    return render_template("index.html", begruessungstext=begruessungstext)


@app.route("/tickets")
def tickets_dashboard():
    ticket_datei = "tickets/tickets.csv"
    tickets = []

    if os.path.exists(ticket_datei):
        with open(ticket_datei, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for zeile in reader:
                tickets.append(zeile)

    return render_template("tickets.html", tickets=tickets)

from flask import request

@app.route("/update_ticket", methods=["POST"])
def update_ticket():
    daten = request.get_json()
    ticket_id = daten.get("ticket_id")

    if not ticket_id:
        return jsonify({"success": False, "message": "Ticket-ID fehlt."}), 400

    ticket_datei = "tickets/tickets.csv"
    tickets = []

    # Lade existierende Tickets
    if os.path.exists(ticket_datei):
        with open(ticket_datei, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            tickets = list(reader)

    # Ticket suchen und Status ändern
    updated = False
    for ticket in tickets:
        if ticket["Ticket-ID"] == ticket_id:
            ticket["Status"] = "Erledigt"
            updated = True
            break

    # Datei neu schreiben
    if updated:
        with open(ticket_datei, mode="w", newline="", encoding="utf-8") as file:
            fieldnames = ["Ticket-ID", "Zeit", "Absicht", "Anfrage", "Status"]
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(tickets)
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "Ticket nicht gefunden."}), 404

@app.route("/download_tickets")
def download_tickets():
    ticket_datei = "tickets/tickets.csv"
    if os.path.exists(ticket_datei):
        return send_file(ticket_datei, as_attachment=True)
    else:
        return "Keine Tickets vorhanden.", 404

@app.route("/chatlogs", methods=["GET", "POST"])
def chatlogs():
    chat_ordner = "chat_logs"
    chat_dateien = []
    suchbegriff = ""  # Initialize with a default value

    # List available chat files
    if os.path.exists(chat_ordner):
        chat_dateien = sorted(f for f in os.listdir(chat_ordner) if f.endswith(".json"))

    ergebnisse = []
    ausgewaehlte_datei = None

    # Handle POST (search/filter action)
    if request.method == "POST":
        ausgewaehlte_datei = request.form.get("datei")
        suchbegriff = request.form.get("suchbegriff", "").lower()  # Update from form

        # Load and filter selected chat file
        if ausgewaehlte_datei:
            dateipfad = os.path.join(chat_ordner, ausgewaehlte_datei)
            if os.path.exists(dateipfad):
                with open(dateipfad, "r", encoding="utf-8") as f:
                    daten = json.load(f)
                ergebnisse = [eintrag for eintrag in daten if suchbegriff in eintrag["nachricht"].lower()]

    # Always pass 'suchbegriff' to the template (now safely defined)
    return render_template(
        "chatlogs.html",
        chat_dateien=chat_dateien,
        ergebnisse=ergebnisse,
        ausgewaehlte_datei=ausgewaehlte_datei,
        suchbegriff=suchbegriff
    )


@app.route("/download_chatlog/<filename>")
def download_chatlog(filename):
    pfad = os.path.join("chat_logs", filename)
    if os.path.exists(pfad):
        return send_file(pfad, as_attachment=True)
    else:
        return "Datei nicht gefunden.", 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render gibt PORT vor
    app.run(host="0.0.0.0", port=port, debug=False)





