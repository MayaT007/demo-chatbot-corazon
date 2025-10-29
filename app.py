from flask import Flask, jsonify
import sqlite3

app = Flask(__name__)

# Startseite
@app.route("/")
def index():
    return "Chatbot läuft! 🚀"

# API-Endpunkt zum Abrufen der Rechnungsinformationen
@app.route('/api/rechnung/<rechnungsnummer>', methods=['GET'])
def get_rechnung(rechnungsnummer):
    try:
        conn = sqlite3.connect('mock_db.db')
        c = conn.cursor()
        c.execute("SELECT * FROM rechnungen WHERE rechnungsnummer = ?", (rechnungsnummer,))
        result = c.fetchone()
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if result:
        rechnungsdaten = {
            "rechnungsnummer": result[1],
            "betrag": result[2],
            "status": result[3]
        }
        return jsonify(rechnungsdaten)
    else:
        return jsonify({"error": "Rechnung nicht gefunden"}), 404

# Nur für lokalen Start (Render nutzt Gunicorn)
if __name__ == '__main__':
    app.run(debug=True)


