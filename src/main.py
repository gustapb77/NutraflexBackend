import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, jsonify
from flask_cors import CORS
from src.models.user import db
from src.routes.user import user_bp
from src.routes.webhook import webhook_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = 'asdf#FGSgvasgf$5$WGT'

# Habilitar CORS para todas as rotas
CORS(app)

app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(webhook_bp, url_prefix='/api/webhook')

# uncomment if you need to use database
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'database', 'app.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
with app.app_context():
    db.create_all()

@app.route('/')
def health_check():
    return jsonify({"status": "ok", "message": "Nutraflex Backend API is running"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "nutraflex-backend"})


if __name__ == '__main__':
   port = int(os.environ.get('PORT', 5001))
app.run(host='0.0.0.0', port=port, debug=False)


