import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app

class VercelPathMiddleware(object):
    """
    Middleware WSGI para normalizar o PATH_INFO no ambiente Serverless da Vercel.
    Garante que rotas como /api/index ou /api/index.py sejam mapeadas para /
    e /api/index/api/data sejam mapeadas para /api/data.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path.startswith('/api/index.py'):
            environ['PATH_INFO'] = path[13:] if len(path) > 13 else '/'
        elif path.startswith('/api/index'):
            environ['PATH_INFO'] = path[10:] if len(path) > 10 else '/'
        
        if not environ.get('PATH_INFO'):
            environ['PATH_INFO'] = '/'
            
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
