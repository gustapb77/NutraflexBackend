
from flask import Blueprint, request, jsonify
import json
import hmac
import hashlib
import os
from datetime import datetime
import logging

webhook_bp = Blueprint("webhook", __name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações do webhook
WEBHOOK_SECRET = os.environ.get("CAKTO_WEBHOOK_SECRET", "nutraflex_webhook_secret_2025")

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
        signature = request.headers.headers.get("X-Cakto-Signature", "")
        content_type = request.headers.get("Content-Type", "")
        
        logger.info(f"Content-Type: {content_type}")
        logger.info(f"Payload size: {len(payload)} bytes")
        
        # Validar assinatura do webhook (opcional para desenvolvimento)
        if WEBHOOK_SECRET != "nutraflex_webhook_secret_2025":  # Só validar se não for o secret padrão
            if not validate_webhook_signature(payload, signature):
                logger.warning("Assinatura do webhook inválida")
                return jsonify({"error": "Assinatura inválida"}), 401
        
        # Parse dos dados JSON
        try:
            webhook_data = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar JSON: {str(e)}")
            return jsonify({"error": "JSON inválido"}), 400
        
        # Log dos dados recebidos
        logger.info(f"Dados do webhook: {json.dumps(webhook_data, indent=2)}")
        
        # Processar o webhook baseado no evento
        event_type = webhook_data.get("event", webhook_data.get("type", "payment.approved"))
        data = webhook_data.get("data", webhook_data)
        
        logger.info(f"Processando evento: {event_type}")
        
        if event_type in ["payment.approved", "payment_approved", "approved", "completed"]:
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
    if not signature:
        return False
    
    try:
        # Calcular assinatura esperada
        expected_signature = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"),
            payload,
            hashlib.sha256
        ).hexdigest()
        
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
        
        # MÉTODO 1: Tentar extrair registration_id (mais seguro)
        registration_id = extract_registration_id(data)
        
        if not customer_email:
            logger.error("Email do cliente não encontrado nos dados do webhook")
            return {"error": "Email do cliente não encontrado"}
        
        logger.info(f"Processando pagamento aprovado:")
        logger.info(f"  Email: {customer_email}")
        logger.info(f"  Nome: {customer_name}")
        logger.info(f"  Registration ID: {registration_id}")
        logger.info(f"  Transaction ID: {transaction_id}")
        logger.info(f"  Valor: R$ {amount}")
        logger.info(f"  Produto: {product_id}")
        
        # Estratégia de identificação em ordem de prioridade:
        # 1. Por registration_id específico (mais seguro)
        # 2. Por email + validação temporal (fallback)
        # 3. Criar conta básica se não encontrar registro pendente
        
        firebase_result = create_account_with_identification_strategy(
            customer_email,
            registration_id,
            customer_name,
            transaction_id,
            amount
        )
        
        if firebase_result["success"]:
            logger.info(f"Conta criada e acesso liberado com sucesso para {customer_email}")
            return {
                "success": True,
                "message": "Conta criada e acesso liberado com sucesso",
                "customer_email": customer_email,
                "registration_id": registration_id,
                "transaction_id": transaction_id,
                "status": "active",
                "identification_method": firebase_result.get("identification_method", "unknown")
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
    """Extrai registration_id de múltiplas fontes possíveis"""
    return (
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

def create_account_with_identification_strategy(customer_email, registration_id, customer_name, transaction_id, amount):
    """
    Cria conta usando estratégia de identificação em múltiplas etapas
    """
    try:
        identification_method = "unknown"
        
        # ESTRATÉGIA 1: Buscar por registration_id específico (mais seguro)
        if registration_id:
            logger.info(f"Tentando identificação por registration_id: {registration_id}")
            result = create_account_from_pending_registration_by_id(
                registration_id, customer_email, customer_name, transaction_id, amount
            )
            if result["success"]:
                result["identification_method"] = "registration_id"
                return result
            else:
                logger.warning(f"Não foi possível criar conta por registration_id: {result.get("error")}")
        
        # ESTRATÉGIA 2: Buscar por email (fallback)
        logger.info(f"Tentando identificação por email: {customer_email}")
        result = create_account_from_pending_registration_by_email(
            customer_email, customer_name, transaction_id, amount
        )
        if result["success"]:
            result["identification_method"] = "email"
            return result
        else:
            logger.warning(f"Não foi possível criar conta por email: {result.get("error")}")
        
        # ESTRATÉGIA 3: Criar conta básica (último recurso)
        logger.info(f"Criando conta básica para: {customer_email}")
        result = create_basic_account(customer_email, customer_name, transaction_id, amount)
        if result["success"]:
            result["identification_method"] = "basic_account"
            return result
        
        return {
            "success": False,
            "error": "Não foi possível criar conta com nenhuma estratégia de identificação"
        }
        
    except Exception as e:
        logger.error(f"Erro na estratégia de identificação: {str(e)}")
        return {
            "success": False,
            "error": f"Erro na estratégia de identificação: {str(e)}"
        }

def create_account_from_pending_registration_by_id(registration_id, customer_email, customer_name, transaction_id, amount):
    """
    Cria conta a partir de registro pendente usando registration_id específico
    """
    try:
        logger.info(f"Buscando registro pendente por ID: {registration_id}")
        
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            cred = credentials.Certificate("/home/ubuntu/nutraflex/nutraflex-separado/nutraflex-backend/firebase_credentials.json")
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        
        # Buscar registro pendente por ID específico
        pending_ref = db.collection("pending_registrations").document(registration_id)
        pending_doc = pending_ref.get()
        
        if not pending_doc.exists:
            return {
                "success": False,
                "error": f"Registro pendente não encontrado para ID: {registration_id}"
            }
        
        pending_data = pending_doc.to_dict()
        
        # Validar se o email confere (segurança adicional)
        if pending_data.get("email") != customer_email:
            logger.warning(f"Email não confere: esperado {pending_data.get("email")}, recebido {customer_email}")
            return {
                "success": False,
                "error": "Email não confere com o registro pendente"
            }
        
        # Verificar se não expirou
        if pending_data.get("expiresAt").todate() < datetime.now():
            logger.warning(f"Registro pendente expirado: {registration_id}")
            pending_ref.delete()  # Limpar registro expirado
            return {
                "success": False,
                "error": "Registro pendente expirado"
            }
        
        # Criar usuário no Firebase Auth
        try:
            user_record = auth.create_user(
                email=pending_data["email"],
                password=pending_data["password"],
                display_name=pending_data["name"],
                email_verified=True
            )
            user_uid = user_record.uid
        except auth.EmailAlreadyExistsError:
            user_record = auth.get_user_by_email(pending_data["email"])
            user_uid = user_record.uid
        
        # Criar perfil completo no Firestore
        user_profile = {
            "uid": user_uid,
            "email": pending_data["email"],
            "name": pending_data["name"],
            "age": pending_data["age"],
            "weight": pending_data["weight"],
            "height": pending_data["height"],
            "gender": pending_data["gender"],
            "goal": pending_data["goal"],
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
            "onboardingCompleted": True,
            "purchaseCompletedAt": firestore.SERVER_TIMESTAMP,
            "transactionId": transaction_id,
            "purchaseAmount": amount,
            "registrationId": registration_id,
            
            # Metadados
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "registrationDate": firestore.SERVER_TIMESTAMP,
            
            # Dados iniciais de progresso
            "totalSessions": 0,
            "currentLevel": 1,
            "totalScore": 0,
            "currentStreak": 0,
            "longestStreak": 0
        }
        
        # Salvar no Firestore
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
        
        # Remover registro pendente
        if pending_ref:
            pending_ref.delete()
            logger.info(f"Registro pendente removido: {registration_id}")
        
        logger.info(f"Conta criada com sucesso para {customer_email}")
        
        return {
            "success": True,
            "message": f"Conta criada com sucesso para {customer_email}",
            "user_uid": user_uid
        }

    except Exception as e:
        logger.error(f"Erro ao criar conta por registration_id: {str(e)}")
        return {
            "success": False,
            "error": f"Erro ao criar conta por registration_id: {str(e)}"
        }

def create_account_from_pending_registration_by_email(customer_email, customer_name, transaction_id, amount):
    """
    Cria conta a partir de registro pendente usando apenas email (fallback)
    """
    try:
        logger.info(f"Buscando registro pendente por email: {customer_email}")
        

        
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            cred = credentials.Certificate("/home/ubuntu/nutraflex/nutraflex-separado/nutraflex-backend/firebase_credentials.json")
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        
        # Buscar registros pendentes por email
        pending_query = db.collection("pending_registrations").where("email", "==", customer_email).limit(5)
        pending_docs = list(pending_query.stream())
        
        if not pending_docs:
            return {
                "success": False,
                "error": f"Nenhum registro pendente encontrado para email: {customer_email}"
            }
        
        # Se houver múltiplos registros, pegar o mais recente não expirado
        valid_pending = None
        for doc in pending_docs:
            data = doc.to_dict()
            if data.get("expiresAt").todate() > datetime.now():
                if not valid_pending or data.get("createdAt") > valid_pending.get("createdAt"):
                    valid_pending = data
                    valid_pending["doc_ref"] = doc.reference
        
        if not valid_pending:
            return {
                "success": False,
                "error": f"Todos os registros pendentes para {customer_email} estão expirados"
            }
        
        # Criar usuário no Firebase Auth
        try:
            user_record = auth.create_user(
                email=valid_pending["email"],
                password=valid_pending["password"],
                display_name=valid_pending["name"],
                email_verified=True
            )
            user_uid = user_record.uid
        except auth.EmailAlreadyExistsError:
            user_record = auth.get_user_by_email(valid_pending["email"])
            user_uid = user_record.uid
        
        # Criar perfil completo no Firestore
        user_profile = {
            "uid": user_uid,
            "email": valid_pending["email"],
            "name": valid_pending["name"],
            "age": valid_pending["age"],
            "weight": valid_pending["weight"],
            "height": valid_pending["height"],
            "gender": valid_pending["gender"],
            "goal": valid_pending["goal"],
            "activityLevel": valid_pending.get("activityLevel"),
            "dietaryRestrictions": valid_pending.get("dietaryRestrictions"),
            "healthConditions": valid_pending.get("healthConditions"),
            "workoutPreference": valid_pending.get("workoutPreference"),
            "availableDays": valid_pending.get("availableDays", []),
            "sessionDuration": valid_pending.get("sessionDuration"),
            "notifications": valid_pending.get("notifications", True),
            "affiliateCode": valid_pending.get("affiliateCode"),
            
            # Dados de acesso e pagamento
            "accessStatus": "active",
            "hasFullAccess": True,
            "isActive": True,
            "onboardingCompleted": True,
            "purchaseCompletedAt": firestore.SERVER_TIMESTAMP,
            "transactionId": transaction_id,
            "purchaseAmount": amount,
            "registrationId": valid_pending.get("registrationId"),
            
            # Metadados
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "registrationDate": firestore.SERVER_TIMESTAMP,
            
            # Dados iniciais de progresso
            "totalSessions": 0,
            "currentLevel": 1,
            "totalScore": 0,
            "currentStreak": 0,
            "longestStreak": 0
        }
        
        # Salvar no Firestore
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
        
        # Remover registro pendente
        if valid_pending.get("doc_ref"):
            valid_pending["doc_ref"].delete()
            logger.info(f"Registro pendente removido: {valid_pending.get("registrationId")}")
        
        logger.info(f"Conta criada com sucesso para {customer_email}")
        
        return {
            "success": True,
            "message": f"Conta criada com sucesso para {customer_email}",
            "user_uid": user_uid
        }
        
    except Exception as e:
        logger.error(f"Erro ao criar conta por email: {str(e)}")
        return {
            "success": False,
            "error": f"Erro ao criar conta por email: {str(e)}"
        }

def create_basic_account(customer_email, customer_name, transaction_id, amount):
    """
    Cria uma conta básica quando não há registro pendente
    """
    try:
        logger.info(f"Criando conta básica para: {customer_email}")
        
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            cred = credentials.Certificate("/home/ubuntu/nutraflex/nutraflex-separado/nutraflex-backend/firebase_credentials.json")
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        
        # Verificar se o usuário já existe
        try:
            user_record = auth.get_user_by_email(customer_email)
            user_uid = user_record.uid
            logger.info(f"Usuário já existe: {customer_email}, UID: {user_uid}")
            
            # Atualizar status de acesso
            user_doc_ref = db.collection("users").document(user_uid)
            user_doc_ref.update({
                "accessStatus": "active",
                "hasFullAccess": True,
                "isActive": True,
                "onboardingCompleted": True, # Assumir que sim
                "purchaseCompletedAt": firestore.SERVER_TIMESTAMP,
                "transactionId": transaction_id,
                "purchaseAmount": amount,
                "updatedAt": firestore.SERVER_TIMESTAMP
            })
            
            logger.info(f"Acesso atualizado para usuário existente: {customer_email}")
            
            return {
                "success": True,
                "message": f"Acesso atualizado para usuário existente: {customer_email}",
                "user_uid": user_uid
            }
            
        except auth.UserNotFoundError:
            # Criar novo usuário se não existir
            logger.info(f"Criando novo usuário básico: {customer_email}")
            
            # Gerar senha aleatória segura
            import secrets
            password = secrets.token_urlsafe(16)
            
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
            
            # Dados de perfil a serem preenchidos
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
        
        # Salvar no Firestore
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
        
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            cred = credentials.Certificate("/home/ubuntu/nutraflex/nutraflex-separado/nutraflex-backend/firebase_credentials.json")
            firebase_admin.initialize_app(cred)
        
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
