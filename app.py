from flask import Flask, jsonify
import sqlite3


app = Flask(__name__)

# API-Endpunkt zum Abrufen der Rechnungsinformationen
@app.route('/api/rechnung/<rechnungsnummer>', methods=['GET'])
def get_rechnung(rechnungsnummer):
    # Mit der SQLite-Datenbank verbinden
    conn = sqlite3.connect('mock_db.db')
    c = conn.cursor()
    
    # Führe eine SQL-Abfrage aus, um die Rechnungsdaten abzurufen
    c.execute("SELECT * FROM rechnungen WHERE rechnungsnummer = ?", (rechnungsnummer,))
    result = c.fetchone()
    
    # Wenn die Rechnung gefunden wird
    if result:
        rechnungsdaten = {
            "rechnungsnummer": result[1],
            "betrag": result[2],
            "status": result[3]
        }
        return jsonify(rechnungsdaten)
    else:
        return jsonify({"error": "Rechnung nicht gefunden"}), 404

# API starten
if __name__ == '__main__':
    app.run(port=5001)
