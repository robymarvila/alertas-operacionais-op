import os
import sys

# Adiciona o diretório raiz ao sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from app import app
except Exception as e:
    import traceback
    err_trace = traceback.format_exc()
    from flask import Flask, jsonify
    app = Flask(__name__)
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def catch_all(path):
        return jsonify({
            "status": "error",
            "message": f"Erro na inicialização da aplicação: {str(e)}",
            "traceback": err_trace.splitlines()
        }), 500
