from flask import Blueprint, request, jsonify
from src.models.user import User, db
from werkzeug.security import generate_password_hash # Adicione esta linha

user_bp = Blueprint(\'user\', __name__)

@user_bp.route(\'/users\', methods=[\'GET\'])
def get_users():
    users = User.query.all()
    return jsonify([user.to_dict() for user in users])

@user_bp.route(\'/users\', methods=[\'POST\'])
def create_user():
    
    data = request.json
    user = User(username=data[\'username\'], email=data[\'email\'])
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201

@user_bp.route(\'/users/<int:user_id>\', methods=[\'GET\'])
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())

@user_bp.route(\'/users/<int:user_id>\', methods=[\'PUT\'])
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.json
    user.username = data.get(\'username\', user.username)
    user.email = data.get(\'email\', user.email)
    db.session.commit()
    return jsonify(user.to_dict())

@user_bp.route(\'/users/<int:user_id>\', methods=[\'DELETE\'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return \'\', 204

# --- NOVA ROTA PARA CRIAR ADMIN (TEMPORÁRIA) ---
@user_bp.route("/create-admin", methods=["POST"])
def create_admin_user():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"message": "Email and password are required"}), 400

    # Verifica se o usuário já existe
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"message": "User with this email already exists"}), 409

    hashed_password = generate_password_hash(password)
    new_admin = User(
        email=email,
        password=hashed_password,
        is_admin=True,  # Define como admin
        is_active=True
    )

    db.session.add(new_admin)
    db.session.commit()

    return jsonify({"message": "Admin user created successfully", "user_id": new_admin.id}), 201
