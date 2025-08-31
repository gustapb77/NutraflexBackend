from flask import Blueprint, request, jsonify
import json
import hmac
import hashlib
import os
from datetime import datetime
import logging
import firebase_admin
from firebase_admin import credentials, firestore, auth

webhook_bp = Blueprint("webhook", __name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- INICIALIZAÇÃO SEGURA DO FIREBASE ---
# Carrega as credenciais do Firebase a partir de uma variável de ambiente.
# Isso é mais seguro e compatível com serviços como o Railway.
try:
    firebase_creds_json = os.environ.get("FIREBASE_CREDENTIALS")
    if not firebase_creds_json:
        raise ValueError("A variável de ambiente FIREBASE_CREDENTIALS não está definida.")
    
    cred_dict = json.loads(firebase_creds_json)
    cred = credentials.Certificate(cred_dict)
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    
    logger.info("Firebase inicializado com sucesso a partir da variável de ambiente.")

except Exception as e:
    logger.error(f"ERRO CRÍTICO AO INICIALIZAR FIREBASE: {e}")
    # O aplicativo não pode funcionar sem o Firebase, então registramos o erro.

# --- CONFIGURAÇÕES DO WEBHOOK ---
# Carrega a chave secreta do webhook da Cakto a partir de uma variável de ambiente.
WEBHOOK_SECRET = os.environ.get("CAKTO_WEBHOOK_SECRET")
if not WEBHOOK_SECRET:
    logger.warning("A variável de ambiente CAKTO_WEBHOOK_SECRET não está definida. A validação de assinatura será pulada.")

# URL permanente do webhook (substitua quando tiver seu próprio domínio)
PERMANENT_WEBHOOK_URL = "https://web-production-1af5.up.railway.app/api/webhook/cakto"

@webhook_bp.route("/cakto", methods=["POST"])
def handle_cakto_webhook():
    """
    Endpoint permanente para receber webhooks da Cakto
    URL:https://web-production-1af5.up.railway.app/api/webhook/cakto
    
    Fluxo de integração:
    1. Cliente realiza pagamento na Cakto
    2. Cakto processa pagamento e confirma transação
    3. Cakto envia webhook para este endpoint
    4. Sistema NutraFlex recebe e valida webhook
    5. Sistema libera automaticamente o acesso do cliente
    6. Cliente recebe acesso imediato a todas as funcionalidades
    """
    try:
        # Log da requisição recebida
        logger.info(f"Webhook recebido de {request.remote_addr} em {datetime.now()}")
        
        # Obter dados do webhook
        payload = request.get_data()
        signature = request.headers.get("X-Cakto-Signature", "")
        content_type = request.headers.get("Content-Type", "")
        
        logger.info(f"Content-Type: {content_type}")
        logger.info(f"Payload size: {len(payload)} bytes")
        
        # Validar assinatura do webhook se a chave secreta estiver configurada
        if WEBHOOK_SECRET:
            if not validate_webhook_signature(payload, signature):
                logger.warning("Assinatura do webhook inválida")
                return jsonify({"error": "Assinatura inválida"}), 401
            logger.info("Assinatura do webhook validada com sucesso.")
        else:
            logger.info("Pulando validação de assinatura do webhook (CAKTO_WEBHOOK_SECRET não configurada).")
        
        # Parse dos dados JSON
        try:
            webhook_data = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar JSON: {str(e)}")
            return jsonify({"error": "JSON inválido"}), 400
        
        # Log dos dados recebidos
        logger.info(f"Dados do webhook: {json.dumps(webhook_data, indent=2)}")
        
        # Processar o webhook baseado no evento
        # Prioriza o 'event' se existir, caso contrário, usa 'type' ou 'payment.approved' como fallback
        event_type = webhook_data.get("event", webhook_data.get("type", "payment.approved"))
        data = webhook_data.get("data", webhook_data) # 'data' pode estar aninhado ou ser o próprio webhook_data
        
        logger.info(f"Processando evento: {event_type}")
        
        # Adaptação para o evento 'purchase_approved' da Cakto
        if event_type == "purchase_approved":
            result = handle_payment_approved(data)
        elif event_type in ["payment.refused", "payment_refused", "refused", "failed"]:
            result = handle_payment_refused(data)
        elif event_type in ["payment.refunded", "payment_refunded", "refunded"]:
            result = handle_payment_refunded(data)
        else:
            logger.info(f"Evento não tratado: {event_type}")
            # Para eventos não conhecidos, assumir como pagamento aprovado se tiver dados de cliente
            if data.get("customer", {}).get("email") or data.get("email"):
                logger.info("Assumindo como pagamento aprovado devido à presença de dados do cliente")
                result = handle_payment_approved(data)
            else:
                return jsonify({"message": "Evento não tratado", "event": event_type}), 200
        
        logger.info(f"Resultado do processamento: {result}")
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {str(e)}")
        return jsonify({"error": "Erro interno do servidor", "details": str(e)}), 500

def validate_webhook_signature(payload, signature):
    """
    Valida a assinatura do webhook da Cakto
    """
    if not signature or not WEBHOOK_SECRET:
        return False
    
    try:
        # Calcular assinatura esperada
        expected_signature = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # A assinatura da Cakto vem no formato "sha256=..."
        # Comparar assinaturas
        return hmac.compare_digest(f"sha256={expected_signature}", signature)
    except Exception as e:
        logger.error(f"Erro ao validar assinatura: {str(e)}")
        return False

def handle_payment_approved(data):
    """
    Processa pagamento aprovado - cria conta a partir de registro pendente
    Usa múltiplos métodos de identificação para associar pagamento ao registro correto
    """
    try:
        # Extrair informações básicas do pagamento
        customer_email = extract_customer_email(data)
        customer_name = extract_customer_name(data)
        transaction_id = extract_transaction_id(data)
        amount = extract_amount(data)
        product_id = extract_product_id(data)
        
        # O registration_id da Cakto (refId) não será o mesmo do Firebase UID
        # Portanto, a estratégia principal será por email.
        registration_id_cakto = extract_registration_id(data) # Este é o refId da Cakto
        
        if not customer_email:
            logger.error("Email do cliente não encontrado nos dados do webhook")
            return {"error": "Email do cliente não encontrado"}
        
        logger.info(f"Processando pagamento aprovado:")
        logger.info(f"  Email: {customer_email}")
        logger.info(f"  Nome: {customer_name}")
        logger.info(f"  Cakto refId: {registration_id_cakto}")
        logger.info(f"  Transaction ID: {transaction_id}")
        logger.info(f"  Valor: R$ {amount}")
        logger.info(f"  Produto: {product_id}")
        
        # Estratégia de identificação: buscar por email
        firebase_result = create_account_from_pending_registration_by_email(
            customer_email,
            customer_name,
            transaction_id,
            amount # Passar o valor para o perfil do usuário
        )
        
        if firebase_result["success"]:
            logger.info(f"Conta criada e acesso liberado com sucesso para {customer_email}")
            return {
                "success": True,
                "message": "Conta criada e acesso liberado com sucesso",
                "customer_email": customer_email,
                "transaction_id": transaction_id,
                "status": "active",
                "identification_method": firebase_result.get("identification_method", "email_fallback")
            }
        else:
            logger.error(f"Erro ao criar conta: {firebase_result.get("error")}")
            return {
                "error": "Erro ao criar conta",
                "details": firebase_result.get("error")
            }
        
    except Exception as e:
        logger.error(f"Erro ao processar pagamento aprovado: {str(e)}")
        return {"error": f"Erro ao processar pagamento: {str(e)}"}

def extract_customer_email(data):
    """Extrai email do cliente de múltiplas fontes possíveis"""
    return (
        data.get("customer", {}).get("email") or 
        data.get("email") or 
        data.get("buyer_email") or
        data.get("customer_email") or
        data.get("custom_field_2") or
        (data.get("metadata") and extract_from_json(data.get("metadata"), "email")) or
        (data.get("user_data") and extract_from_json(data.get("user_data"), "email"))
    )

def extract_customer_name(data):
    """Extrai nome do cliente de múltiplas fontes possíveis"""
    return (
        data.get("customer", {}).get("name") or 
        data.get("name") or 
        data.get("buyer_name") or
        data.get("customer_name") or
        data.get("custom_field_3") or
        (data.get("metadata") and extract_from_json(data.get("metadata"), "name")) or
        (data.get("user_data") and extract_from_json(data.get("user_data"), "name"))
    )

def extract_registration_id(data):
    """Extrai registration_id de múltiplas fontes possíveis (incluindo refId da Cakto)"""
    return (
        data.get("refId") or  # Adicionado para compatibilidade com Cakto
        data.get("registration_id") or
        data.get("custom_field_1") or
        data.get("external_id") or
        data.get("reference") or
        data.get("order_id") or
        (data.get("custom_fields", {}).get("registration_id")) or
        (data.get("metadata") and extract_from_json(data.get("metadata"), "registration_id")) or
        (data.get("user_data") and extract_from_json(data.get("user_data"), "registration_id")) or
        (data.get("customer", {}).get("registration_id"))
    )

def extract_transaction_id(data):
    """Extrai ID da transação"""
    return (
        data.get("transaction_id") or 
        data.get("id") or 
        data.get("payment_id") or
        data.get("order_id")
    )

def extract_amount(data):
    """Extrai valor da transação"""
    return (
        data.get("amount") or 
        data.get("value") or 
        data.get("total") or
        data.get("price")
    )

def extract_product_id(data):
    """Extrai ID do produto"""
    return (
        data.get("product_id") or 
        data.get("product") or 
        data.get("item_id")
    )

def extract_from_json(json_string, key):
    """Extrai valor de uma string JSON de forma segura"""
    try:
        if json_string:
            parsed = json.loads(json_string)
            return parsed.get(key)
    except (json.JSONDecodeError, TypeError):
        pass
    return None

def create_account_from_pending_registration_by_email(customer_email, customer_name, transaction_id, amount):
    """
    Cria conta a partir de registro pendente usando o email como identificador.
    Esta é a estratégia principal, já que o refId da Cakto não corresponde ao UID do Firebase.
    """
    try:
        db = firestore.client()
        
        # Buscar o registro pendente mais recente para este email
        # Ordena por createdAt para pegar o mais recente, caso haja múltiplos
        query = db.collection("pending_registrations").where("email", "==", customer_email).order_by("createdAt", direction=firestore.Query.DESCENDING).limit(1)
        docs = query.stream()
        
        pending_doc = next(docs, None)
        if not pending_doc:
            # Se não encontrar registro pendente, tenta criar uma conta básica
            logger.warning(f"Nenhum registro pendente encontrado para o email: {customer_email}. Tentando criar conta básica.")
            return create_basic_account(customer_email, customer_name, transaction_id, amount)

        pending_data = pending_doc.to_dict()
        user_uid = pending_doc.id # O ID do documento é o UID do usuário do Firebase

        logger.info(f"Registro pendente encontrado para {customer_email} com ID {user_uid}.")

        # Verificar se o usuário já existe no Firebase Auth (pode ter sido criado pelo frontend)
        try:
            auth.get_user(user_uid)
            logger.info(f"Usuário {user_uid} já existe no Firebase Auth.")
        except auth.UserNotFoundError:
            # Se o usuário não existe no Auth, algo deu errado no frontend. Criar um básico.
            logger.warning(f"Usuário {user_uid} não encontrado no Firebase Auth, mas registro pendente existe. Criando usuário básico no Auth.")
            # Gerar senha aleatória segura
            import secrets
            password = secrets.token_urlsafe(16)
            auth.create_user(
                uid=user_uid, # Usar o UID do registro pendente
                email=pending_data["email"],
                password=password,
                display_name=pending_data["name"],
                email_verified=True
            )

        # Atualizar o perfil do usuário no Firestore para ativar o acesso
        user_profile = {
            "uid": user_uid,
            "email": pending_data["email"],
            "name": pending_data["name"],
            "age": pending_data.get("age"),
            "weight": pending_data.get("weight"),
            "height": pending_data.get("height"),
            "gender": pending_data.get("gender"),
            "goal": pending_data.get("goal"),
            "activityLevel": pending_data.get("activityLevel"),
            "dietaryRestrictions": pending_data.get("dietaryRestrictions"),
            "healthConditions": pending_data.get("healthConditions"),
            "workoutPreference": pending_data.get("workoutPreference"),
            "availableDays": pending_data.get("availableDays", []),
            "sessionDuration": pending_data.get("sessionDuration"),
            "notifications": pending_data.get("notifications", True),
            "affiliateCode": pending_data.get("affiliateCode"),
            
            # Dados de acesso e pagamento
            "accessStatus": "active",
            "hasFullAccess": True,
            "isActive": True,
            "onboardingCompleted": True, # Assumimos que o onboarding foi feito via formulário
            "purchaseCompletedAt": firestore.SERVER_TIMESTAMP,
            "transactionId": transaction_id,
            "purchaseAmount": amount,
            "registrationId": user_uid, # O registrationId é o UID do Firebase
            
            # Metadados
            "createdAt": pending_data.get("createdAt", firestore.SERVER_TIMESTAMP),
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "registrationDate": pending_data.get("createdAt", firestore.SERVER_TIMESTAMP),
            
            # Dados iniciais de progresso (se não existirem)
            "totalSessions": pending_data.get("totalSessions", 0),
            "currentLevel": pending_data.get("currentLevel", 1),
            "totalScore": pending_data.get("totalScore", 0),
            "currentStreak": pending_data.get("currentStreak", 0),
            "longestStreak": pending_data.get("longestStreak", 0)
        }
        
        user_doc_ref = db.collection("users").document(user_uid)
        user_doc_ref.set(user_profile, merge=True) # Usar merge=True para não sobrescrever dados existentes

        # Criar documento de progresso inicial se não existir
        progress_ref = db.collection("users").document(user_uid).collection("progress").document("current")
        progress_data = {
            "userId": user_uid,
            "level": 1,
            "totalScore": 0,
            "currentStreak": 0,
            "longestStreak": 0,
            "lastActivityDate": None,
            "weeklyGoal": 3,
            "monthlyGoal": 12,
            "achievements": [],
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }
        progress_ref.set(progress_data, merge=True)
        
        # Remover o registro pendente
        pending_doc.reference.delete()
        logger.info(f"Registro pendente {pending_doc.id} removido após ativação.")

        return {"success": True, "user_uid": user_uid, "identification_method": "email_fallback"}

    except Exception as e:
        logger.error(f"Erro em create_account_from_pending_registration_by_email: {str(e)}")
        return {"success": False, "error": str(e)}


def create_basic_account(customer_email, customer_name, transaction_id, amount):
    """
    Cria uma conta básica quando não há registro pendente correspondente.
    Isso pode acontecer se o usuário não completou o formulário ou se houve algum erro.
    """
    try:
        db = firestore.client()
        
        # Verificar se o usuário já existe no Auth
        try:
            user_record = auth.get_user_by_email(customer_email)
            user_uid = user_record.uid
            logger.info(f"Usuário já existe no Auth: {customer_email}, UID: {user_uid}. Ativando acesso.")
            
            # Atualizar status de acesso para usuário existente
            user_doc_ref = db.collection("users").document(user_uid)
            user_doc_ref.set({
                "accessStatus": "active",
                "hasFullAccess": True,
                "isActive": True,
                "purchaseCompletedAt": firestore.SERVER_TIMESTAMP,
                "transactionId": transaction_id,
                "purchaseAmount": amount,
                "updatedAt": firestore.SERVER_TIMESTAMP
            }, merge=True)
            
            return {"success": True, "user_uid": user_uid, "message": "Acesso ativado para usuário existente (conta básica)."}
            
        except auth.UserNotFoundError:
            # Criar novo usuário no Auth se não existir
            logger.info(f"Criando novo usuário básico no Auth para: {customer_email}")
            import secrets
            password = secrets.token_urlsafe(16) # Senha aleatória para o usuário básico
            
            user_record = auth.create_user(
                email=customer_email,
                password=password,
                display_name=customer_name,
                email_verified=True
            )
            user_uid = user_record.uid

        # Criar perfil básico no Firestore
        user_profile = {
            "uid": user_uid,
            "email": customer_email,
            "name": customer_name,
            
            # Dados de acesso e pagamento
            "accessStatus": "active",
            "hasFullAccess": True,
            "isActive": True,
            "onboardingCompleted": False, # Precisa completar o onboarding
            "purchaseCompletedAt": firestore.SERVER_TIMESTAMP,
            "transactionId": transaction_id,
            "purchaseAmount": amount,
            
            # Metadados
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "registrationDate": firestore.SERVER_TIMESTAMP,
            
            # Dados de perfil a serem preenchidos (inicialmente nulos)
            "age": None,
            "weight": None,
            "height": None,
            "gender": None,
            "goal": None,
            "activityLevel": None,
            "dietaryRestrictions": None,
            "healthConditions": None,
            "workoutPreference": None,
            "availableDays": [],
            "sessionDuration": None,
            "notifications": True,
            "affiliateCode": None,
            
            # Dados de progresso
            "totalSessions": 0,
            "currentLevel": 1,
            "totalScore": 0,
            "currentStreak": 0,
            "longestStreak": 0
        }
        
        user_doc_ref = db.collection("users").document(user_uid)
        user_doc_ref.set(user_profile)
        
        # Criar documento de progresso inicial
        progress_data = {
            "userId": user_uid,
            "level": 1,
            "totalScore": 0,
            "currentStreak": 0,
            "longestStreak": 0,
            "lastActivityDate": None,
            "weeklyGoal": 3,
            "monthlyGoal": 12,
            "achievements": [],
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }
        
        progress_ref = db.collection("users").document(user_uid).collection("progress").document("current")
        progress_ref.set(progress_data)
        
        logger.info(f"Conta básica criada com sucesso para {customer_email}")
        
        # TODO: Enviar email de boas-vindas com senha temporária
        
        return {
            "success": True,
            "message": f"Conta básica criada com sucesso para {customer_email}",
            "user_uid": user_uid
        }

    except Exception as e:
        logger.error(f"Erro ao criar conta básica: {str(e)}")
        return {
            "success": False,
            "error": f"Erro ao criar conta básica: {str(e)}"
        }

def handle_payment_refused(data):
    """
    Processa pagamento recusado
    """
    customer_email = extract_customer_email(data)
    logger.warning(f"Pagamento recusado para: {customer_email}")
    # TODO: Enviar notificação para o usuário
    return {
        "success": True,
        "message": "Pagamento recusado processado",
        "customer_email": customer_email
    }

def handle_payment_refunded(data):
    """
    Processa pagamento estornado - remove acesso do usuário
    """
    try:
        customer_email = extract_customer_email(data)
        logger.warning(f"Pagamento estornado para: {customer_email}")
        
        # Inicializar Firebase se necessário (já inicializado globalmente, mas mantido para segurança)
        # Esta parte é redundante se a inicialização global funcionar, mas serve como fallback
        if not firebase_admin._apps:
            logger.error("Firebase não inicializado globalmente no handle_payment_refunded. Tentando inicializar localmente.")
            # Tenta inicializar localmente se não estiver globalmente
            try:
                firebase_creds_json = os.environ.get("FIREBASE_CREDENTIALS")
                if not firebase_creds_json:
                    raise ValueError("FIREBASE_CREDENTIALS não definida para fallback.")
                cred_dict = json.loads(firebase_creds_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase inicializado localmente no handle_payment_refunded.")
            except Exception as init_e:
                logger.error(f"Falha na inicialização local do Firebase em handle_payment_refunded: {init_e}")
                return {"success": False, "error": "Firebase não inicializado."}
        
        db = firestore.client()
        
        try:
            user_record = auth.get_user_by_email(customer_email)
            user_uid = user_record.uid
            
            # Desativar conta no Auth
            auth.update_user(user_uid, disabled=True)
            
            # Atualizar status no Firestore
            user_doc_ref = db.collection("users").document(user_uid)
            user_doc_ref.update({
                "accessStatus": "refunded",
                "hasFullAccess": False,
                "isActive": False,
                "updatedAt": firestore.SERVER_TIMESTAMP
            })
            
            logger.info(f"Acesso removido para: {customer_email}")
            
            return {
                "success": True,
                "message": f"Acesso removido para {customer_email}",
                "customer_email": customer_email
            }
            
        except auth.UserNotFoundError:
            logger.error(f"Usuário não encontrado para estorno: {customer_email}")
            return {
                "success": False,
                "error": f"Usuário não encontrado para estorno: {customer_email}"
            }

    except Exception as e:
        logger.error(f"Erro ao processar estorno: {str(e)}")
        return {
            "success": False,
            "error": f"Erro ao processar estorno: {str(e)}"
        }

