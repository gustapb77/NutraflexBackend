"""
Configurações centralizadas do NutraFlex Backend
"""
import os
from pathlib import Path

class Config:
    """Configurações base da aplicação"""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'asdf#FGSgvasgf$5$WGT')
    
    # Database
    BASE_DIR = Path(__file__).parent.parent
    DATABASE_URL = os.environ.get('DATABASE_URL', f"sqlite:///{BASE_DIR}/database/app.db")
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # CORS
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*')
    
    # Webhook Cakto
    CAKTO_WEBHOOK_SECRET = os.environ.get('CAKTO_WEBHOOK_SECRET', 'nutraflex_webhook_secret_2025')
    
    # Firebase
    FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH', './firebase_credentials.json')
    
    @classmethod
    def validate_webhook_secret(cls):
        """Valida se a chave do webhook está configurada corretamente"""
        if cls.CAKTO_WEBHOOK_SECRET == 'nutraflex_webhook_secret_2025':
            print("⚠️  AVISO: Usando chave de webhook padrão. Configure CAKTO_WEBHOOK_SECRET em produção!")
            return False
        return True
    
    @classmethod
    def validate_firebase_credentials(cls):
        """Valida se as credenciais do Firebase estão configuradas"""
        credentials_path = Path(cls.FIREBASE_CREDENTIALS_PATH)
        if not credentials_path.exists():
            print(f"❌ ERRO: Arquivo de credenciais do Firebase não encontrado: {credentials_path}")
            return False
        return True
    
    @classmethod
    def validate_all(cls):
        """Valida todas as configurações críticas"""
        webhook_ok = cls.validate_webhook_secret()
        firebase_ok = cls.validate_firebase_credentials()
        
        if webhook_ok and firebase_ok:
            print("✅ Todas as configurações estão válidas!")
            return True
        else:
            print("❌ Algumas configurações precisam ser ajustadas.")
            return False

class DevelopmentConfig(Config):
    """Configurações para desenvolvimento"""
    DEBUG = True
    FLASK_ENV = 'development'

class ProductionConfig(Config):
    """Configurações para produção"""
    DEBUG = False
    FLASK_ENV = 'production'

# Mapeamento de configurações por ambiente
config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

def get_config():
    """Retorna a configuração baseada na variável de ambiente FLASK_ENV"""
    env = os.environ.get('FLASK_ENV', 'default')
    return config_by_name.get(env, DevelopmentConfig)

