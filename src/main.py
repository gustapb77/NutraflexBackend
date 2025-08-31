import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, jsonify
from flask_cors import CORS
from src.models.user import db
from src.routes.user import user_bp
from src.routes.webhook import webhook_bp
from src.config import get_config

app = Flask(__name__)

# Carregar configurações
config = get_config()
app.config.from_object(config)

# Habilitar CORS para todas as rotas
CORS(app)

app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(webhook_bp, url_prefix='/api/webhook')

# Inicializar banco de dados
db.init_app(app)
with app.app_context():
    db.create_all()

@app.route('/')
def health_check():
    return jsonify({"status": "ok", "message": "Nutraflex Backend API is running"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "nutraflex-backend"})

@app.route('/config/check')
def config_check():
    """Endpoint para verificar configurações (apenas em desenvolvimento)"""
    if app.config.get('FLASK_ENV') == 'development':
        webhook_ok = config.validate_webhook_secret()
        firebase_ok = config.validate_firebase_credentials()
        
        return jsonify({
            "webhook_configured": webhook_ok,
            "firebase_configured": firebase_ok,
            "all_configured": webhook_ok and firebase_ok,
            "webhook_secret_is_default": config.CAKTO_WEBHOOK_SECRET == 'nutraflex_webhook_secret_2025',
            "firebase_path": config.FIREBASE_CREDENTIALS_PATH
        })
    else:
        return jsonify({"error": "Endpoint disponível apenas em desenvolvimento"}), 403

if __name__ == '__main__':
    # Validar configurações na inicialização
    print("🔧 Verificando configurações...")
    config.validate_all()
    
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)


