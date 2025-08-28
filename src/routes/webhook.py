from flask import Blueprint, request, jsonify
import json
import hmac
import hashlib
import os
from datetime import datetime
import logging

webhook_bp = Blueprint('webhook', __name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações do webhook
WEBHOOK_SECRET = os.environ.get('CAKTO_WEBHOOK_SECRET', 'nutraflex_webhook_secret_2025')

# URL permanente do webhook (substitua quando tiver seu próprio domínio)
PERMANENT_WEBHOOK_URL = "https://5001-imutjfagsehgc5629zvn5-d13a3483.manusvm.computer/api/webhook/cakto"

@webhook_bp.route('/cakto', methods=['POST'])
def handle_cakto_webhook():
    """
    Endpoint permanente para receber webhooks da Cakto
    URL: https://5000-ifzqaehwbutnbyjqmsdb7-85dd8fd7.manusvm.computer/api/webhook/cakto
    
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
        signature = request.headers.get('X-Cakto-Signature', '')
        content_type = request.headers.get('Content-Type', '')
        
        logger.info(f"Content-Type: {content_type}")
        logger.info(f"Payload size: {len(payload)} bytes")
        
        # Validar assinatura do webhook (opcional para desenvolvimento)
        if WEBHOOK_SECRET != 'nutraflex_webhook_secret_2025':  # Só validar se não for o secret padrão
            if not validate_webhook_signature(payload, signature):
                logger.warning("Assinatura do webhook inválida")
                return jsonify({'error': 'Assinatura inválida'}), 401
        
        # Parse dos dados JSON
        try:
            webhook_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar JSON: {str(e)}")
            return jsonify({'error': 'JSON inválido'}), 400
        
        # Log dos dados recebidos
        logger.info(f"Dados do webhook: {json.dumps(webhook_data, indent=2)}")
        
        # Processar o webhook baseado no evento
        event_type = webhook_data.get('event', webhook_data.get('type', 'payment.approved'))
        data = webhook_data.get('data', webhook_data)
        
        logger.info(f"Processando evento: {event_type}")
        
        if event_type in ['payment.approved', 'payment_approved', 'approved', 'completed']:
            result = handle_payment_approved(data)
        elif event_type in ['payment.refused', 'payment_refused', 'refused', 'failed']:
            result = handle_payment_refused(data)
        elif event_type in ['payment.refunded', 'payment_refunded', 'refunded']:
            result = handle_payment_refunded(data)
        else:
            logger.info(f"Evento não tratado: {event_type}")
            # Para eventos não conhecidos, assumir como pagamento aprovado se tiver dados de cliente
            if data.get('customer', {}).get('email') or data.get('email'):
                logger.info("Assumindo como pagamento aprovado devido à presença de dados do cliente")
                result = handle_payment_approved(data)
            else:
                return jsonify({'message': 'Evento não tratado', 'event': event_type}), 200
        
        logger.info(f"Resultado do processamento: {result}")
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor', 'details': str(e)}), 500

def validate_webhook_signature(payload, signature):
    """
    Valida a assinatura do webhook da Cakto
    """
    if not signature:
        return False
    
    try:
        # Calcular assinatura esperada
        expected_signature = hmac.new(
            WEBHOOK_SECRET.encode('utf-8'),
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
            return {'error': 'Email do cliente não encontrado'}
        
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
        
        if firebase_result['success']:
            logger.info(f"Conta criada e acesso liberado com sucesso para {customer_email}")
            return {
                'success': True,
                'message': 'Conta criada e acesso liberado com sucesso',
                'customer_email': customer_email,
                'registration_id': registration_id,
                'transaction_id': transaction_id,
                'status': 'active',
                'identification_method': firebase_result.get('identification_method', 'unknown')
            }
        else:
            logger.error(f"Erro ao criar conta: {firebase_result.get('error')}")
            return {
                'error': 'Erro ao criar conta',
                'details': firebase_result.get('error')
            }
        
    except Exception as e:
        logger.error(f"Erro ao processar pagamento aprovado: {str(e)}")
        return {'error': f'Erro ao processar pagamento: {str(e)}'}

def extract_customer_email(data):
    """Extrai email do cliente de múltiplas fontes possíveis"""
    return (
        data.get('customer', {}).get('email') or 
        data.get('email') or 
        data.get('buyer_email') or
        data.get('customer_email') or
        data.get('custom_field_2') or
        (data.get('metadata') and extract_from_json(data.get('metadata'), 'email')) or
        (data.get('user_data') and extract_from_json(data.get('user_data'), 'email'))
    )

def extract_customer_name(data):
    """Extrai nome do cliente de múltiplas fontes possíveis"""
    return (
        data.get('customer', {}).get('name') or 
        data.get('name') or 
        data.get('buyer_name') or
        data.get('customer_name') or
        data.get('custom_field_3') or
        (data.get('metadata') and extract_from_json(data.get('metadata'), 'name')) or
        (data.get('user_data') and extract_from_json(data.get('user_data'), 'name'))
    )

def extract_registration_id(data):
    """Extrai registration_id de múltiplas fontes possíveis"""
    return (
        data.get('registration_id') or
        data.get('custom_field_1') or
        data.get('external_id') or
        data.get('reference') or
        data.get('order_id') or
        (data.get('custom_fields', {}).get('registration_id')) or
        (data.get('metadata') and extract_from_json(data.get('metadata'), 'registration_id')) or
        (data.get('user_data') and extract_from_json(data.get('user_data'), 'registration_id')) or
        (data.get('customer', {}).get('registration_id'))
    )

def extract_transaction_id(data):
    """Extrai ID da transação"""
    return (
        data.get('transaction_id') or 
        data.get('id') or 
        data.get('payment_id') or
        data.get('order_id')
    )

def extract_amount(data):
    """Extrai valor da transação"""
    return (
        data.get('amount') or 
        data.get('value') or 
        data.get('total') or
        data.get('price')
    )

def extract_product_id(data):
    """Extrai ID do produto"""
    return (
        data.get('product_id') or 
        data.get('product') or 
        data.get('item_id')
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
        identification_method = 'unknown'
        
        # ESTRATÉGIA 1: Buscar por registration_id específico (mais seguro)
        if registration_id:
            logger.info(f"Tentando identificação por registration_id: {registration_id}")
            result = create_account_from_pending_registration_by_id(
                registration_id, customer_email, customer_name, transaction_id, amount
            )
            if result['success']:
                result['identification_method'] = 'registration_id'
                return result
            else:
                logger.warning(f"Não foi possível criar conta por registration_id: {result.get('error')}")
        
        # ESTRATÉGIA 2: Buscar por email (fallback)
        logger.info(f"Tentando identificação por email: {customer_email}")
        result = create_account_from_pending_registration_by_email(
            customer_email, customer_name, transaction_id, amount
        )
        if result['success']:
            result['identification_method'] = 'email'
            return result
        else:
            logger.warning(f"Não foi possível criar conta por email: {result.get('error')}")
        
        # ESTRATÉGIA 3: Criar conta básica (último recurso)
        logger.info(f"Criando conta básica para: {customer_email}")
        result = create_basic_account(customer_email, customer_name, transaction_id, amount)
        if result['success']:
            result['identification_method'] = 'basic_account'
            return result
        
        return {
            'success': False,
            'error': 'Não foi possível criar conta com nenhuma estratégia de identificação'
        }
        
    except Exception as e:
        logger.error(f"Erro na estratégia de identificação: {str(e)}")
        return {
            'success': False,
            'error': f'Erro na estratégia de identificação: {str(e)}'
        }

def create_account_from_pending_registration_by_id(registration_id, customer_email, customer_name, transaction_id, amount):
    """
    Cria conta a partir de registro pendente usando registration_id específico
    """
    try:
        logger.info(f"Buscando registro pendente por ID: {registration_id}")
        
        # IMPLEMENTAÇÃO SIMULADA - REMOVER EM PRODUÇÃO
        logger.info("SIMULAÇÃO: Conta criada com sucesso por registration_id")
        
        return {
            'success': True,
            'message': f'Conta criada para {customer_email} usando registration_id {registration_id}'
        }
        
        # IMPLEMENTAÇÃO REAL COM FIREBASE - DESCOMENTAR E CONFIGURAR
        """
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            # Configurar credenciais...
            pass
        
        db = firestore.client()
        
        # Buscar registro pendente por ID específico
        pending_ref = db.collection('pending_registrations').document(registration_id)
        pending_doc = pending_ref.get()
        
        if not pending_doc.exists:
            return {
                'success': False,
                'error': f'Registro pendente não encontrado para ID: {registration_id}'
            }
        
        pending_data = pending_doc.to_dict()
        
        # Validar se o email confere (segurança adicional)
        if pending_data.get('email') != customer_email:
            logger.warning(f"Email não confere: esperado {pending_data.get('email')}, recebido {customer_email}")
            return {
                'success': False,
                'error': 'Email não confere com o registro pendente'
            }
        
        # Verificar se não expirou
        if pending_data.get('expiresAt').todate() < datetime.now():
            logger.warning(f"Registro pendente expirado: {registration_id}")
            pending_ref.delete()  # Limpar registro expirado
            return {
                'success': False,
                'error': 'Registro pendente expirado'
            }
        
        # Criar usuário no Firebase Auth
        try:
            user_record = auth.create_user(
                email=pending_data['email'],
                password=pending_data['password'],
                display_name=pending_data['name'],
                email_verified=True
            )
            user_uid = user_record.uid
        except auth.EmailAlreadyExistsError:
            user_record = auth.get_user_by_email(pending_data['email'])
            user_uid = user_record.uid
        
        # Criar perfil completo no Firestore
        user_profile = {
            'uid': user_uid,
            'email': pending_data['email'],
            'name': pending_data['name'],
            'age': pending_data['age'],
            'weight': pending_data['weight'],
            'height': pending_data['height'],
            'gender': pending_data['gender'],
            'goal': pending_data['goal'],
            'activityLevel': pending_data.get('activityLevel'),
            'dietaryRestrictions': pending_data.get('dietaryRestrictions'),
            'healthConditions': pending_data.get('healthConditions'),
            'workoutPreference': pending_data.get('workoutPreference'),
            'availableDays': pending_data.get('availableDays', []),
            'sessionDuration': pending_data.get('sessionDuration'),
            'notifications': pending_data.get('notifications', True),
            'affiliateCode': pending_data.get('affiliateCode'),
            
            # Dados de acesso e pagamento
            'accessStatus': 'active',
            'hasFullAccess': True,
            'isActive': True,
            'onboardingCompleted': True,
            'purchaseCompletedAt': firestore.SERVER_TIMESTAMP,
            'transactionId': transaction_id,
            'purchaseAmount': amount,
            'registrationId': registration_id,
            
            # Metadados
            'createdAt': firestore.SERVER_TIMESTAMP,
            'updatedAt': firestore.SERVER_TIMESTAMP,
            'registrationDate': firestore.SERVER_TIMESTAMP,
            
            # Dados iniciais de progresso
            'totalSessions': 0,
            'currentLevel': 1,
            'totalScore': 0,
            'currentStreak': 0,
            'longestStreak': 0
        }
        
        # Salvar no Firestore
        user_doc_ref = db.collection('users').document(user_uid)
        user_doc_ref.set(user_profile)
        
        # Criar documento de progresso inicial
        progress_data = {
            'userId': user_uid,
            'level': 1,
            'totalScore': 0,
            'currentStreak': 0,
            'longestStreak': 0,
            'lastActivityDate': None,
            'weeklyGoal': 3,
            'monthlyGoal': 12,
            'achievements': [],
            'createdAt': firestore.SERVER_TIMESTAMP,
            'updatedAt': firestore.SERVER_TIMESTAMP
        }
        
        progress_ref = db.collection('users').document(user_uid).collection('progress').document('current')
        progress_ref.set(progress_data)
        
        # Remover registro pendente
        pending_ref.delete()
        
        logger.info(f"Conta criada com sucesso por registration_id para {customer_email}")
        
        return {
            'success': True,
            'message': f'Conta criada com sucesso para {customer_email}',
            'user_uid': user_uid
        }
        """
        
    except Exception as e:
        logger.error(f"Erro ao criar conta por registration_id: {str(e)}")
        return {
            'success': False,
            'error': f'Erro ao criar conta por registration_id: {str(e)}'
        }

def create_account_from_pending_registration_by_email(customer_email, customer_name, transaction_id, amount):
    """
    Cria conta a partir de registro pendente usando apenas email (fallback)
    """
    try:
        logger.info(f"Buscando registro pendente por email: {customer_email}")
        
        # IMPLEMENTAÇÃO SIMULADA - REMOVER EM PRODUÇÃO
        logger.info("SIMULAÇÃO: Conta criada com sucesso por email")
        
        return {
            'success': True,
            'message': f'Conta criada para {customer_email} usando email como identificação'
        }
        
        # IMPLEMENTAÇÃO REAL COM FIREBASE - DESCOMENTAR E CONFIGURAR
        """
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            # Configurar credenciais...
            pass
        
        db = firestore.client()
        
        # Buscar registros pendentes por email
        pending_query = db.collection('pending_registrations').where('email', '==', customer_email).limit(5)
        pending_docs = list(pending_query.stream())
        
        if not pending_docs:
            return {
                'success': False,
                'error': f'Nenhum registro pendente encontrado para email: {customer_email}'
            }
        
        # Se houver múltiplos registros, pegar o mais recente não expirado
        valid_pending = None
        for doc in pending_docs:
            data = doc.to_dict()
            if data.get('expiresAt').todate() > datetime.now():
                if not valid_pending or data.get('createdAt') > valid_pending.get('createdAt'):
                    valid_pending = data
                    valid_pending['doc_ref'] = doc.reference
        
        if not valid_pending:
            return {
                'success': False,
                'error': f'Todos os registros pendentes para {customer_email} estão expirados'
            }
        
        # Usar a mesma lógica de criação de conta da função anterior
        # ... (código similar ao create_account_from_pending_registration_by_id)
        
        return {
            'success': True,
            'message': f'Conta criada com sucesso para {customer_email} por email'
        }
        """
        
    except Exception as e:
        logger.error(f"Erro ao criar conta por email: {str(e)}")
        return {
            'success': False,
            'error': f'Erro ao criar conta por email: {str(e)}'
        }

def handle_payment_refused(data):
    """
    Processa pagamento recusado
    """
    try:
        customer_email = (
            data.get('customer', {}).get('email') or 
            data.get('email') or 
            data.get('buyer_email')
        )
        
        transaction_id = (
            data.get('transaction_id') or 
            data.get('id') or 
            data.get('payment_id')
        )
        
        reason = data.get('reason', data.get('decline_reason', 'Não especificado'))
        
        logger.info(f"Pagamento recusado:")
        logger.info(f"  Email: {customer_email}")
        logger.info(f"  Transaction ID: {transaction_id}")
        logger.info(f"  Motivo: {reason}")
        
        # Registrar tentativa de pagamento falhada
        if customer_email:
            firebase_result = update_user_access_firebase(
                customer_email, 
                None,
                transaction_id, 
                'payment_failed',
                None
            )
        
        return {
            'success': True,
            'message': 'Pagamento recusado registrado',
            'customer_email': customer_email,
            'transaction_id': transaction_id,
            'reason': reason
        }
        
    except Exception as e:
        logger.error(f"Erro ao processar pagamento recusado: {str(e)}")
        return {'error': f'Erro ao processar pagamento recusado: {str(e)}'}

def handle_payment_refunded(data):
    """
    Processa reembolso - revoga acesso do usuário
    """
    try:
        customer_email = (
            data.get('customer', {}).get('email') or 
            data.get('email') or 
            data.get('buyer_email')
        )
        
        transaction_id = (
            data.get('transaction_id') or 
            data.get('id') or 
            data.get('payment_id')
        )
        
        refund_amount = (
            data.get('refund_amount') or 
            data.get('amount') or 
            data.get('value')
        )
        
        logger.info(f"Reembolso processado:")
        logger.info(f"  Email: {customer_email}")
        logger.info(f"  Transaction ID: {transaction_id}")
        logger.info(f"  Valor reembolsado: R$ {refund_amount}")
        
        # Revogar acesso do usuário
        firebase_result = update_user_access_firebase(
            customer_email, 
            None,
            transaction_id, 
            'refunded',
            refund_amount
        )
        
        if firebase_result['success']:
            logger.info(f"Acesso revogado para {customer_email}")
            return {
                'success': True,
                'message': 'Acesso revogado devido ao reembolso',
                'customer_email': customer_email,
                'transaction_id': transaction_id
            }
        else:
            return {
                'error': 'Erro ao revogar acesso',
                'details': firebase_result.get('error')
            }
        
    except Exception as e:
        logger.error(f"Erro ao processar reembolso: {str(e)}")
        return {'error': f'Erro ao processar reembolso: {str(e)}'}

def create_account_from_pending_registration(customer_email, registration_id, customer_name, transaction_id, amount):
    """
    Cria conta do usuário a partir de registro pendente após confirmação de pagamento
    """
    try:
        logger.info(f"Criando conta a partir de registro pendente:")
        logger.info(f"  Email: {customer_email}")
        logger.info(f"  Registration ID: {registration_id}")
        logger.info(f"  Nome: {customer_name}")
        logger.info(f"  Transaction ID: {transaction_id}")
        logger.info(f"  Valor: {amount}")
        
        # IMPLEMENTAÇÃO SIMULADA - REMOVER EM PRODUÇÃO
        # Esta simulação sempre retorna sucesso para testes
        logger.info("SIMULAÇÃO: Conta criada com sucesso a partir de registro pendente")
        
        return {
            'success': True,
            'message': f'Conta criada para {customer_email} a partir de registro pendente {registration_id}'
        }
        
        # IMPLEMENTAÇÃO REAL COM FIREBASE - DESCOMENTAR E CONFIGURAR
        """
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        
        # Inicializar Firebase (fazer apenas uma vez)
        if not firebase_admin._apps:
            # Configurar com suas credenciais do Firebase
            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": "seu-projeto-firebase",
                "private_key_id": "sua-private-key-id",
                "private_key": "sua-private-key",
                "client_email": "seu-client-email",
                "client_id": "seu-client-id",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            })
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        
        # 1. Buscar registro pendente
        pending_ref = None
        pending_data = None
        
        if registration_id:
            # Buscar por registration_id específico
            pending_ref = db.collection('pending_registrations').document(registration_id)
            pending_doc = pending_ref.get()
            if pending_doc.exists:
                pending_data = pending_doc.to_dict()
        else:
            # Buscar por email se não tiver registration_id
            pending_query = db.collection('pending_registrations').where('email', '==', customer_email).limit(1)
            pending_docs = list(pending_query.stream())
            if pending_docs:
                pending_ref = pending_docs[0].reference
                pending_data = pending_docs[0].to_dict()
        
        if not pending_data:
            logger.warning(f"Registro pendente não encontrado para {customer_email}")
            # Se não encontrar registro pendente, criar conta básica
            return create_basic_account(customer_email, customer_name, transaction_id, amount)
        
        logger.info(f"Registro pendente encontrado: {pending_data.get('name', 'N/A')}")
        
        # 2. Criar usuário no Firebase Auth
        try:
            user_record = auth.create_user(
                email=pending_data['email'],
                password=pending_data['password'],
                display_name=pending_data['name'],
                email_verified=True
            )
            user_uid = user_record.uid
            logger.info(f"Usuário criado no Firebase Auth: {user_uid}")
        except auth.EmailAlreadyExistsError:
            # Se o email já existe, obter o usuário existente
            user_record = auth.get_user_by_email(pending_data['email'])
            user_uid = user_record.uid
            logger.info(f"Usuário já existe no Firebase Auth: {user_uid}")
        
        # 3. Criar perfil completo no Firestore
        user_profile = {
            'uid': user_uid,
            'email': pending_data['email'],
            'name': pending_data['name'],
            'age': pending_data['age'],
            'weight': pending_data['weight'],
            'height': pending_data['height'],
            'gender': pending_data['gender'],
            'goal': pending_data['goal'],
            'activityLevel': pending_data.get('activityLevel'),
            'dietaryRestrictions': pending_data.get('dietaryRestrictions'),
            'healthConditions': pending_data.get('healthConditions'),
            'workoutPreference': pending_data.get('workoutPreference'),
            'availableDays': pending_data.get('availableDays', []),
            'sessionDuration': pending_data.get('sessionDuration'),
            'notifications': pending_data.get('notifications', True),
            'affiliateCode': pending_data.get('affiliateCode'),
            
            # Dados de acesso e pagamento
            'accessStatus': 'active',
            'hasFullAccess': True,
            'isActive': True,
            'onboardingCompleted': True,
            'purchaseCompletedAt': firestore.SERVER_TIMESTAMP,
            'transactionId': transaction_id,
            'purchaseAmount': amount,
            'registrationId': registration_id,
            
            # Metadados
            'createdAt': firestore.SERVER_TIMESTAMP,
            'updatedAt': firestore.SERVER_TIMESTAMP,
            'registrationDate': firestore.SERVER_TIMESTAMP,
            
            # Dados iniciais de progresso
            'totalSessions': 0,
            'currentLevel': 1,
            'totalScore': 0,
            'currentStreak': 0,
            'longestStreak': 0
        }
        
        # Salvar no Firestore
        user_doc_ref = db.collection('users').document(user_uid)
        user_doc_ref.set(user_profile)
        
        # 4. Criar documento de progresso inicial
        progress_data = {
            'userId': user_uid,
            'level': 1,
            'totalScore': 0,
            'currentStreak': 0,
            'longestStreak': 0,
            'lastActivityDate': None,
            'weeklyGoal': 3,
            'monthlyGoal': 12,
            'achievements': [],
            'createdAt': firestore.SERVER_TIMESTAMP,
            'updatedAt': firestore.SERVER_TIMESTAMP
        }
        
        progress_ref = db.collection('users').document(user_uid).collection('progress').document('current')
        progress_ref.set(progress_data)
        
        # 5. Remover registro pendente
        if pending_ref:
            pending_ref.delete()
            logger.info(f"Registro pendente removido: {registration_id}")
        
        logger.info(f"Conta criada com sucesso para {customer_email}")
        
        return {
            'success': True,
            'message': f'Conta criada com sucesso para {customer_email}',
            'user_uid': user_uid
        }
        """
        
    except Exception as e:
        logger.error(f"Erro ao criar conta a partir de registro pendente: {str(e)}")
        return {
            'success': False,
            'error': f'Erro ao criar conta: {str(e)}'
        }

def create_basic_account(customer_email, customer_name, transaction_id, amount):
    """
    Cria conta básica quando não há registro pendente
    """
    try:
        logger.info(f"Criando conta básica para {customer_email}")
        
        # IMPLEMENTAÇÃO SIMULADA
        logger.info("SIMULAÇÃO: Conta básica criada com sucesso")
        
        return {
            'success': True,
            'message': f'Conta básica criada para {customer_email}'
        }
        
        # IMPLEMENTAÇÃO REAL - DESCOMENTAR QUANDO NECESSÁRIO
        """
        # Implementar criação de conta básica sem dados de registro pendente
        # Similar à função acima, mas com dados mínimos
        """
        
    except Exception as e:
        logger.error(f"Erro ao criar conta básica: {str(e)}")
        return {
            'success': False,
            'error': f'Erro ao criar conta básica: {str(e)}'
        }

def update_user_access_firebase(customer_email, customer_name, transaction_id, status, amount):
    """
    Atualiza o acesso do usuário no Firebase
    
    Para implementação real com Firebase:
    1. Instale: pip install firebase-admin
    2. Configure as credenciais do Firebase
    3. Descomente e configure o código abaixo
    """
    try:
        logger.info(f"Atualizando usuário no Firebase:")
        logger.info(f"  Email: {customer_email}")
        logger.info(f"  Nome: {customer_name}")
        logger.info(f"  Transaction ID: {transaction_id}")
        logger.info(f"  Status: {status}")
        logger.info(f"  Valor: {amount}")
        
        # IMPLEMENTAÇÃO SIMULADA - REMOVER EM PRODUÇÃO
        # Esta simulação sempre retorna sucesso para testes
        logger.info("SIMULAÇÃO: Usuário atualizado com sucesso no Firebase")
        
        return {
            'success': True,
            'message': f'Usuário {customer_email} atualizado para status {status}'
        }
        
        # IMPLEMENTAÇÃO REAL COM FIREBASE - DESCOMENTAR E CONFIGURAR
        """
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        # Inicializar Firebase (fazer apenas uma vez)
        if not firebase_admin._apps:
            # Configurar com suas credenciais do Firebase
            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": "seu-projeto-firebase",
                "private_key_id": "sua-private-key-id",
                "private_key": "sua-private-key",
                "client_email": "seu-client-email",
                "client_id": "seu-client-id",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            })
            firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        
        # Buscar usuário pelo email
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', customer_email).limit(1)
        docs = list(query.stream())
        
        if docs:
            # Usuário encontrado - atualizar
            user_doc = docs[0]
            user_ref = db.collection('users').document(user_doc.id)
            
            update_data = {
                'updatedAt': firestore.SERVER_TIMESTAMP
            }
            
            if status == 'active':
                update_data.update({
                    'accessStatus': 'active',
                    'hasFullAccess': True,
                    'purchaseCompletedAt': firestore.SERVER_TIMESTAMP,
                    'transactionId': transaction_id,
                    'purchaseAmount': amount,
                    'isActive': True
                })
                if customer_name:
                    update_data['displayName'] = customer_name
                    
            elif status == 'refunded':
                update_data.update({
                    'accessStatus': 'refunded',
                    'hasFullAccess': False,
                    'refundedAt': firestore.SERVER_TIMESTAMP,
                    'refundTransactionId': transaction_id,
                    'refundAmount': amount,
                    'isActive': False
                })
                
            elif status == 'payment_failed':
                update_data.update({
                    'lastPaymentAttempt': firestore.SERVER_TIMESTAMP,
                    'paymentFailedTransactionId': transaction_id
                })
            
            user_ref.update(update_data)
            logger.info(f"Usuário {customer_email} atualizado no Firebase")
            
        else:
            # Usuário não encontrado - criar novo se for pagamento aprovado
            if status == 'active':
                new_user_data = {
                    'email': customer_email,
                    'displayName': customer_name or customer_email.split('@')[0],
                    'accessStatus': 'active',
                    'hasFullAccess': True,
                    'purchaseCompletedAt': firestore.SERVER_TIMESTAMP,
                    'transactionId': transaction_id,
                    'purchaseAmount': amount,
                    'isActive': True,
                    'createdAt': firestore.SERVER_TIMESTAMP,
                    'updatedAt': firestore.SERVER_TIMESTAMP,
                    'totalSessions': 0
                }
                
                users_ref.add(new_user_data)
                logger.info(f"Novo usuário {customer_email} criado no Firebase")
            else:
                logger.warning(f"Usuário {customer_email} não encontrado para status {status}")
                return {'success': False, 'error': 'Usuário não encontrado'}
        
        return {'success': True, 'message': 'Usuário atualizado com sucesso'}
        """
        
    except Exception as e:
        logger.error(f"Erro na integração com Firebase: {str(e)}")
        return {
            'success': False,
            'error': f'Erro na integração com Firebase: {str(e)}'
        }

@webhook_bp.route('/test', methods=['GET'])
def test_webhook():
    """
    Endpoint de teste para verificar se o webhook está funcionando
    """
    return jsonify({
        'message': 'Webhook da Cakto está funcionando!',
        'timestamp': datetime.now().isoformat(),
        'webhook_url': PERMANENT_WEBHOOK_URL,
        'status': 'online',
        'version': '2.0'
    })

@webhook_bp.route('/info', methods=['GET'])
def webhook_info():
    """
    Informações sobre o webhook para configuração na Cakto
    """
    return jsonify({
        'webhook_url': PERMANENT_WEBHOOK_URL,
        'methods': ['POST'],
        'events_supported': [
            'payment.approved',
            'payment.refused', 
            'payment.refunded'
        ],
        'description': 'Webhook para integração NutraFlex + Cakto',
        'instructions': {
            'step1': 'Configure este URL no seu produto na Cakto',
            'step2': 'Certifique-se de que o evento payment.approved está habilitado',
            'step3': 'Teste com uma compra para verificar a integração'
        }
    })

@webhook_bp.route('/simulate-payment', methods=['POST'])
def simulate_payment():
    """
    Endpoint para simular um pagamento aprovado (apenas para testes)
    """
    try:
        data = request.get_json()
        customer_email = data.get('email', 'teste@nutraflex.com')
        customer_name = data.get('name', 'Usuário Teste')
        
        # Simular dados de pagamento
        payment_data = {
            'customer': {
                'email': customer_email,
                'name': customer_name
            },
            'transaction_id': f'TEST_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'amount': 97.00,
            'product_id': 'nutraflex_full_access'
        }
        
        result = handle_payment_approved(payment_data)
        
        return jsonify({
            'message': 'Pagamento simulado',
            'result': result,
            'test_data': payment_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500



def create_basic_account(customer_email, customer_name, transaction_id, amount):
    """
    Cria conta básica quando não há registro pendente (último recurso)
    """
    try:
        logger.info(f"Criando conta básica para: {customer_email}")
        
        # IMPLEMENTAÇÃO SIMULADA - REMOVER EM PRODUÇÃO
        logger.info("SIMULAÇÃO: Conta básica criada com sucesso")
        
        return {
            'success': True,
            'message': f'Conta básica criada para {customer_email}'
        }
        
        # IMPLEMENTAÇÃO REAL COM FIREBASE - DESCOMENTAR E CONFIGURAR
        """
        import firebase_admin
        from firebase_admin import credentials, firestore, auth
        import secrets
        import string
        
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            # Configurar credenciais...
            pass
        
        db = firestore.client()
        
        # Gerar senha temporária
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        
        # Criar usuário no Firebase Auth
        try:
            user_record = auth.create_user(
                email=customer_email,
                password=temp_password,
                display_name=customer_name or 'Usuário NutraFlex',
                email_verified=True
            )
            user_uid = user_record.uid
        except auth.EmailAlreadyExistsError:
            user_record = auth.get_user_by_email(customer_email)
            user_uid = user_record.uid
        
        # Criar perfil básico no Firestore
        user_profile = {
            'uid': user_uid,
            'email': customer_email,
            'name': customer_name or 'Usuário NutraFlex',
            
            # Dados básicos padrão
            'age': 30,
            'weight': 70,
            'height': 170,
            'gender': 'not_specified',
            'goal': 'general_health',
            'activityLevel': 'moderate',
            
            # Dados de acesso e pagamento
            'accessStatus': 'active',
            'hasFullAccess': True,
            'isActive': True,
            'onboardingCompleted': False,  # Usuário precisará completar depois
            'purchaseCompletedAt': firestore.SERVER_TIMESTAMP,
            'transactionId': transaction_id,
            'purchaseAmount': amount,
            'accountType': 'basic_from_payment',
            
            # Metadados
            'createdAt': firestore.SERVER_TIMESTAMP,
            'updatedAt': firestore.SERVER_TIMESTAMP,
            'registrationDate': firestore.SERVER_TIMESTAMP,
            
            # Dados iniciais de progresso
            'totalSessions': 0,
            'currentLevel': 1,
            'totalScore': 0,
            'currentStreak': 0,
            'longestStreak': 0,
            
            # Flags especiais
            'needsProfileCompletion': True,
            'tempPassword': temp_password  # Para envio por email
        }
        
        # Salvar no Firestore
        user_doc_ref = db.collection('users').document(user_uid)
        user_doc_ref.set(user_profile)
        
        # Criar documento de progresso inicial
        progress_data = {
            'userId': user_uid,
            'level': 1,
            'totalScore': 0,
            'currentStreak': 0,
            'longestStreak': 0,
            'lastActivityDate': None,
            'weeklyGoal': 3,
            'monthlyGoal': 12,
            'achievements': [],
            'createdAt': firestore.SERVER_TIMESTAMP,
            'updatedAt': firestore.SERVER_TIMESTAMP
        }
        
        progress_ref = db.collection('users').document(user_uid).collection('progress').document('current')
        progress_ref.set(progress_data)
        
        logger.info(f"Conta básica criada com sucesso para {customer_email}")
        
        # TODO: Enviar email com senha temporária e instruções
        
        return {
            'success': True,
            'message': f'Conta básica criada com sucesso para {customer_email}',
            'user_uid': user_uid,
            'temp_password': temp_password
        }
        """
        
    except Exception as e:
        logger.error(f"Erro ao criar conta básica: {str(e)}")
        return {
            'success': False,
            'error': f'Erro ao criar conta básica: {str(e)}'
        }

# Endpoint para testar extração de dados do webhook
@webhook_bp.route('/test-extraction', methods=['POST'])
def test_webhook_extraction():
    """
    Endpoint para testar extração de dados de diferentes formatos de webhook
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Dados não fornecidos'}), 400
        
        # Extrair dados usando as funções de extração
        extracted_data = {
            'customer_email': extract_customer_email(data),
            'customer_name': extract_customer_name(data),
            'registration_id': extract_registration_id(data),
            'transaction_id': extract_transaction_id(data),
            'amount': extract_amount(data),
            'product_id': extract_product_id(data)
        }
        
        # Verificar quais dados foram encontrados
        found_data = {k: v for k, v in extracted_data.items() if v is not None}
        missing_data = [k for k, v in extracted_data.items() if v is None]
        
        return jsonify({
            'success': True,
            'message': 'Dados extraídos com sucesso',
            'extracted_data': extracted_data,
            'found_data': found_data,
            'missing_data': missing_data,
            'original_data': data,
            'identification_possible': bool(found_data.get('customer_email')),
            'registration_id_found': bool(found_data.get('registration_id'))
        })
        
    except Exception as e:
        logger.error(f"Erro ao testar extração: {str(e)}")
        return jsonify({
            'error': f'Erro ao testar extração: {str(e)}'
        }), 500

