import sys
import os

# Adiciona o diretório raiz ao path para importação dos módulos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app

# Vercel serverless function entrypoint
# app é o objeto Flask WSGI
