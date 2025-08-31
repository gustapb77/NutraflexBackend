# NutraFlex Backend - Configuração de Produção

## 🚀 Deploy Rápido

### 1. Variáveis de Ambiente (Railway)

Configure estas variáveis no painel do Railway:

```bash
# Webhook Cakto
CAKTO_WEBHOOK_SECRET=sua_chave_secreta_da_cakto

# Firebase
FIREBASE_CREDENTIALS_PATH=./firebase_credentials.json

# Flask
SECRET_KEY=sua_chave_secreta_flask_segura
FLASK_ENV=production
```

### 2. Arquivo de Credenciais Firebase

1. Baixe as credenciais do Firebase Console
2. Renomeie para `firebase_credentials.json`
3. Coloque na raiz do projeto
4. Faça deploy

### 3. Verificar Configuração

Acesse: `https://seu-app.railway.app/config/check` (apenas em desenvolvimento)

## 🔧 Desenvolvimento Local

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com suas configurações

# 3. Configurar Firebase
cp firebase_credentials.json.example firebase_credentials.json
# Editar com suas credenciais reais

# 4. Executar
python src/main.py
```

## 📋 Checklist de Deploy

- [ ] Chave secreta do webhook configurada
- [ ] Credenciais do Firebase adicionadas
- [ ] Variáveis de ambiente configuradas
- [ ] URL do webhook configurada na Cakto
- [ ] Teste de webhook realizado

## 🆘 Troubleshooting

### Erro: "Firebase não inicializado"
- Verifique se o arquivo `firebase_credentials.json` existe
- Confirme se o caminho está correto
- Valide se o JSON está bem formado

### Erro: "Assinatura do webhook inválida"
- Confirme se `CAKTO_WEBHOOK_SECRET` está configurada
- Verifique se a chave está correta na Cakto
- Teste com webhook de desenvolvimento primeiro

### Servidor não inicia
- Verifique se todas as dependências estão instaladas
- Confirme se o diretório `database/` existe
- Veja os logs para erros específicos

