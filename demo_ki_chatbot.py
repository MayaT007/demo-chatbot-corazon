import requests
import spacy
from flask import Flask, request, jsonify, send_file, render_template_string
from datetime import datetime, timedelta
import os
from fpdf import FPDF
import re
from fuzzywuzzy import fuzz
import csv 

# Lade spaCy Modell
nlp = spacy.load("./modell_maya")

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

def erstelle_pdf_rechnung(rechnungsnummer, betrag, status):
    dateiname = f"pdf_rechnungen/Rechnung_{rechnungsnummer}.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)
    pdf.cell(200, 10, txt=f"Rechnung Nr. {rechnungsnummer}", ln=True, align="C")
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"Betrag: {betrag} Euro", ln=True, align="C")
    pdf.cell(200, 10, txt=f"Status: {status}", ln=True, align="C")
    pdf.output(dateiname)
    return dateiname

def verstehe_absicht(text):
    doc = nlp(text)
    absichten = doc.cats
    beste_absicht = max(absichten, key=absichten.get)
    return beste_absicht

def speichere_chat(user_text, bot_text):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"chat_logs/chatverlauf_{timestamp}.txt"
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"User: {user_text}\n")
        f.write(f"Maya: {bot_text}\n\n")

def erkenne_entity(text):
    betraege = re.findall(r"\d+[.,]?\d*\s*€?", text)
    rechnungsnummern = re.findall(r"\b\d{5,10}\b", text)
    return {"betrag": betraege, "rechnungsnummer": rechnungsnummern}

def finde_aehnliche_frage(benutzertext):
    benutzertext = benutzertext.strip().lower()
    for frage, antwort in faq_daten.items():
        score = fuzz.partial_ratio(benutzertext, frage.lower())
        if score > 90:
            return antwort
    return None

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


@app.route("/download/<filename>")
def download_pdf(filename):
    pfad = os.path.join("pdf_rechnungen", filename)
    return send_file(pfad, as_attachment=True)

@app.route("/chat", methods=["POST"])
def chat():
    daten = request.get_json()
    benutzertext = daten.get("nachricht", "").lower()
    user_id = daten.get("user_id", "default")

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
                api_url = f"http://127.0.0.1:5001/api/rechnung/{rechnungsnummer}"
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
            api_url = f"http://127.0.0.1:5001/api/rechnung/{rechnungsnummer}"
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

    return send_response(benutzertext, antwort)

def send_response(benutzertext, antwort):
    speichere_chat(benutzertext, antwort)
    return jsonify({"antwort": antwort})



@app.route("/download/<path:filename>")
def download_file(filename):
    return send_file(filename, as_attachment=True)

@app.route("/")
def index():
    begruessungstext = "Willkommen! Ich bin Maya, Ihre KI-Assistentin. Ich helfe Ihnen bei Rechnungen, Inkasso und Mahnungen."
    return render_template_string("""
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>KI Assist - Maya</title>

<link rel="icon" type="image/png" href="{{ url_for('static', filename='IMG_7829.png') }}">
<link href="https://fonts.googleapis.com/css2?family=Roboto&display=swap" rel="stylesheet">

<style>
body {
    font-family: 'Roboto', sans-serif;
    background: #ecf0f1;
    margin: 0;
    padding: 0;
    height: 100vh;
    overflow: hidden;
    display: flex;
    justify-content: center;
    align-items: center;
    transition: background 0.5s, color 0.5s;
}
body.dark-mode {
    background: #2c3e50;
    color: white;
}

/* Popup */
#popup {
    display: flex;
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background: rgba(0,0,0,0.5);
    justify-content: center;
    align-items: center;
    z-index: 2000;
    animation: fadeIn 1s ease-in-out;
}
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
#popup-content {
    background: white;
    padding: 40px 30px;
    border-radius: 20px;
    width: 400px;
    text-align: center;
    box-shadow: 0 8px 30px rgba(0,0,0,0.2);
}
#popup-content img {
    width: 120px;
    margin-bottom: 20px;
}
#popup-content h2 {
    margin: 10px 0;
}
#popup-content button {
    background: #A3B9D2;
    color: white;
    padding: 10px 20px;
    border-radius: 20px;
    border: none;
    margin-top: 10px;
    cursor: pointer;
    font-size: 16px;
    transition: background 0.3s ease;
}
#popup-content button:hover {
    background: #869bb5;
}
#popup-content select {
    margin-top: 10px;
    padding: 8px 16px;
    border-radius: 15px;
    border: 1px solid #ccc;
}

/* Chat */
.chat-container {
    display: none;
    flex-direction: column;
    width: 420px;
    height: 650px;
    background: white;
    border-radius: 20px;
    box-shadow: 0 8px 20px rgba(0,0,0,0.2);
    overflow: hidden;
}
.chat-header, .chat-footer, .chat-body {
    padding: 10px;
}
.chat-header {
    background: #A3B9D2;
    color: white;
    display: flex;
    align-items: center;
    gap: 10px;
}
.chat-header img {
    width: 60px;
    height: 60px;
    border-radius: 50%;
}
.chat-body {
    flex: 1;
    background: #f7f9fa;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
}
.chat-footer {
    background: #ecf0f1;
    display: flex;
}
.chat-input {
    flex: 1;
    border-radius: 25px;
    border: 1px solid #ccc;
    padding: 10px;
}
.send-btn {
    background: url('https://cdn-icons-png.flaticon.com/512/60/60525.png') no-repeat center;
    background-size: cover;
    width: 40px;
    height: 40px;
    border: none;
    margin-left: 10px;
    cursor: pointer;
}
.bot-message, .user-message {
    margin: 8px 0;
    padding: 10px 14px;
    border-radius: 20px;
    max-width: 70%;
    display: flex;
    align-items: center;
    font-size: 14px;
}
.bot-message {
    background-color: #e6f9e6;
}
.user-message {
    background-color: #d0e6ff;
    margin-left: auto;
}
.bot-message img, .user-message img {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    margin-right: 8px;
}
.user-message img {
    margin-left: 8px;
    margin-right: 0;
}
.quick-buttons {
    text-align: center;
    padding: 10px;
}
.quick-buttons button {
    margin: 5px;
    padding: 8px 18px;
    border: none;
    border-radius: 20px;
    background: #A3B9D2;
    color: white;
    cursor: pointer;
    font-size: 14px;
    box-shadow: 0 4px 6px rgba(93,173,226,0.3);
    transition: background 0.3s;
}
.quick-buttons button:hover {
    background: #869bb5;
}
</style>
</head>

<body>

<!-- 🌟 Popup - Willkommen -->
<div id="popup" style="display: flex;">
    <div id="popup-content">
        <img src="{{ url_for('static', filename='IMG_7829.png') }}" alt="Logo">
        <h2>Willkommen bei Maya!</h2>
        <p>Bitte akzeptieren Sie die <a href="#" onclick="openTerms()">Nutzungsbedingungen</a>:</p>
        <label><input type="checkbox" id="agb-check"> Ich akzeptiere</label><br><br>
        <select id="language-select">
            <option value="de">Deutsch</option>
            <option value="en">English</option>
        </select><br><br>
        <button id="start-chat">Chat starten</button><br><br>
        <button onclick="toggleDarkMode()">🌙 / ☀️</button>
    </div>
</div>

<!-- 🌟 Chat-Container -->
<div class="chat-container" id="chat-container" style="display: none;">
    <div class="chat-header">
        <img src="{{ url_for('static', filename='IMG_7829.png') }}" alt="Logo">
        <div class="text-container">
            <h2>KI Assist - Maya</h2>
            <p>{{ begruessungstext }}</p>
        </div>
    </div>

    <div class="chat-body" id="chatBody">
        <div class="bot-message">
            <img src="{{ url_for('static', filename='avatarmya.jpg') }}" alt="Bot Avatar">
            Hallo, wie kann ich Ihnen helfen?
        </div>
    </div>

    <div class="chat-footer">
        <input type="text" id="userInput" class="chat-input" placeholder="Ihre Nachricht..." onkeypress="checkEnter(event)">
        <button class="send-btn" onclick="sendMessage()"></button>
    </div>

    <div class="quick-buttons">
        <button onclick="quickAsk('Wie lautet meine Rechnungsnummer?')">Rechnungsnummer</button>
        <button onclick="quickAsk('Ich möchte wissen, ob meine Zahlung eingegangen ist.')">Zahlung prüfen</button>
        <button onclick="quickAsk('Wann bekomme ich eine Mahnung?')">Mahnung</button>
        <button onclick="quickAsk('Ich habe einen Inkassofall, was soll ich tun?')">Inkasso</button>
        <button onclick="quickAsk('Ich möchte eine Teilzahlung vereinbaren.')">Teilzahlung</button>
    </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const startButton = document.getElementById('start-chat');

    startButton.addEventListener('click', function() {
        const agbCheck = document.getElementById('agb-check');
        if (!agbCheck.checked) {
            alert('Bitte akzeptieren Sie die Nutzungsbedingungen.');
            return;
        }

        document.getElementById('popup').style.display = 'none';
        document.getElementById('chat-container').style.display = 'flex';
    });

    const userSound = new Audio('https://actions.google.com/sounds/v1/cartoon/wood_plank_flicks.ogg');
    const botSound = new Audio('https://actions.google.com/sounds/v1/cartoon/pop.ogg');

    function sendMessage() {
        const input = document.getElementById('userInput');
        const message = input.value.trim();
        if (message === '') return;

        const chatBody = document.getElementById('chatBody');
        chatBody.innerHTML += `<div class="user-message"><div>${message}</div><img src="/static/avatarmya.jpg" alt="User Avatar"></div>`;
        userSound.play();
        input.value = '';

        chatBody.scrollTop = chatBody.scrollHeight;

        setTimeout(() => {
            fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nachricht: message })
            })
            .then(response => response.json())
            .then(data => {
    botSound.play();
    let botAntwort = data.antwort;

    // Links automatisch anklickbar machen
    botAntwort = botAntwort.replace(/\\[([^\\]]+)\\]\\(([^\\)]+)\\)/g, '<a href="$2" target="_blank">$1</a>');

    chatBody.innerHTML += `<div class="bot-message"><img src="/static/avatarmya.jpg" alt="Bot Avatar"><div>${botAntwort}</div></div>`;
    chatBody.scrollTop = chatBody.scrollHeight;
            })
            .catch(error => {
                chatBody.innerHTML += `<div class="bot-message"><div>❗ Fehler bei der Antwort. Bitte versuchen Sie es erneut.</div></div>`;
            });
        }, 1200);
    }

    const inputField = document.getElementById('userInput');
    inputField.addEventListener('keypress', function(event) {
        if (event.key === 'Enter') {
            sendMessage();
        }
    });

    window.quickAsk = function(text) {
        inputField.value = text;
        sendMessage();
    }
});
</script>

</body>
</html>
""", begruessungstext=begruessungstext)

if __name__ == "__main__":
    app.run(debug=True)
