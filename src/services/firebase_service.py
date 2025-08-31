"""
Serviço centralizado para integração com Firebase
"""
import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask import current_app

logger = logging.getLogger(__name__)

class FirebaseService:
    """Serviço para gerenciar operações do Firebase"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.db = None
            self._initialized = True
    
    def initialize(self, credentials_path: Optional[str] = None) -> bool:
        """
        Inicializa o Firebase Admin SDK
        
        Args:
            credentials_path: Caminho para o arquivo de credenciais JSON
            
        Returns:
            bool: True se inicializado com sucesso, False caso contrário
        """
        try:
            # Se já foi inicializado, não fazer novamente
            if firebase_admin._apps:
                logger.info("Firebase já inicializado")
                self.db = firestore.client()
                return True
            
            # Obter caminho das credenciais
            if not credentials_path:
                credentials_path = current_app.config.get('FIREBASE_CREDENTIALS_PATH', './firebase_credentials.json')
            
            # Verificar se arquivo existe
            cred_file = Path(credentials_path)
            if not cred_file.exists():
                logger.error(f"Arquivo de credenciais não encontrado: {cred_file}")
                return False
            
            # Validar se é um JSON válido
            try:
                with open(cred_file, 'r') as f:
                    cred_data = json.load(f)
                    
                # Verificar campos obrigatórios
                required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
                missing_fields = [field for field in required_fields if field not in cred_data]
                
                if missing_fields:
                    logger.error(f"Campos obrigatórios faltando no arquivo de credenciais: {missing_fields}")
                    return False
                    
            except json.JSONDecodeError as e:
                logger.error(f"Arquivo de credenciais não é um JSON válido: {e}")
                return False
            
            # Inicializar Firebase
            cred = credentials.Certificate(str(cred_file))
            firebase_admin.initialize_app(cred)
            
            # Inicializar Firestore
            self.db = firestore.client()
            
            logger.info("✅ Firebase inicializado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao inicializar Firebase: {str(e)}")
            return False
    
    def is_initialized(self) -> bool:
        """Verifica se o Firebase está inicializado"""
        return bool(firebase_admin._apps and self.db)
    
    def create_user(self, email: str, password: str, display_name: str = None) -> Optional[str]:
        """
        Cria um usuário no Firebase Auth
        
        Args:
            email: Email do usuário
            password: Senha do usuário
            display_name: Nome de exibição do usuário
            
        Returns:
            str: UID do usuário criado ou None se falhou
        """
        try:
            if not self.is_initialized():
                logger.error("Firebase não inicializado")
                return None
            
            user_record = auth.create_user(
                email=email,
                password=password,
                display_name=display_name,
                email_verified=True
            )
            
            logger.info(f"Usuário criado no Firebase Auth: {user_record.uid}")
            return user_record.uid
            
        except auth.EmailAlreadyExistsError:
            logger.warning(f"Email já existe no Firebase Auth: {email}")
            # Tentar obter o usuário existente
            try:
                user_record = auth.get_user_by_email(email)
                return user_record.uid
            except Exception as e:
                logger.error(f"Erro ao obter usuário existente: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao criar usuário no Firebase Auth: {e}")
            return None
    
    def save_user_profile(self, user_uid: str, profile_data: Dict[str, Any]) -> bool:
        """
        Salva perfil do usuário no Firestore
        
        Args:
            user_uid: UID do usuário
            profile_data: Dados do perfil
            
        Returns:
            bool: True se salvou com sucesso, False caso contrário
        """
        try:
            if not self.is_initialized():
                logger.error("Firebase não inicializado")
                return False
            
            # Adicionar timestamp
            profile_data['createdAt'] = firestore.SERVER_TIMESTAMP
            profile_data['updatedAt'] = firestore.SERVER_TIMESTAMP
            
            # Salvar no Firestore
            user_doc_ref = self.db.collection("users").document(user_uid)
            user_doc_ref.set(profile_data)
            
            logger.info(f"Perfil do usuário salvo no Firestore: {user_uid}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao salvar perfil no Firestore: {e}")
            return False
    
    def get_pending_registration(self, registration_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca registro pendente por ID
        
        Args:
            registration_id: ID do registro pendente
            
        Returns:
            Dict com dados do registro ou None se não encontrado
        """
        try:
            if not self.is_initialized():
                logger.error("Firebase não inicializado")
                return None
            
            pending_ref = self.db.collection("pending_registrations").document(registration_id)
            pending_doc = pending_ref.get()
            
            if not pending_doc.exists:
                logger.warning(f"Registro pendente não encontrado: {registration_id}")
                return None
            
            return pending_doc.to_dict()
            
        except Exception as e:
            logger.error(f"Erro ao buscar registro pendente: {e}")
            return None
    
    def delete_pending_registration(self, registration_id: str) -> bool:
        """
        Remove registro pendente
        
        Args:
            registration_id: ID do registro pendente
            
        Returns:
            bool: True se removido com sucesso, False caso contrário
        """
        try:
            if not self.is_initialized():
                logger.error("Firebase não inicializado")
                return False
            
            pending_ref = self.db.collection("pending_registrations").document(registration_id)
            pending_ref.delete()
            
            logger.info(f"Registro pendente removido: {registration_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao remover registro pendente: {e}")
            return False
    
    def create_progress_document(self, user_uid: str) -> bool:
        """
        Cria documento de progresso inicial para o usuário
        
        Args:
            user_uid: UID do usuário
            
        Returns:
            bool: True se criado com sucesso, False caso contrário
        """
        try:
            if not self.is_initialized():
                logger.error("Firebase não inicializado")
                return False
            
            progress_data = {
                "userId": user_uid,
                "level": 1,
                "totalScore": 0,
                "currentStreak": 0,
                "longestStreak": 0,
                "lastActivityDate": None,
                "totalWorkouts": 0,
                "totalNutritionLogs": 0,
                "achievements": [],
                "createdAt": firestore.SERVER_TIMESTAMP,
                "updatedAt": firestore.SERVER_TIMESTAMP
            }
            
            progress_ref = self.db.collection("user_progress").document(user_uid)
            progress_ref.set(progress_data)
            
            logger.info(f"Documento de progresso criado: {user_uid}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao criar documento de progresso: {e}")
            return False

# Instância global do serviço
firebase_service = FirebaseService()

