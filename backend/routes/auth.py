from flask import Blueprint, request, jsonify, session, redirect
from database import get_db
from dotenv import load_dotenv
import os

load_dotenv()

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/me')
def me():
    if 'user_id' not in session:
        return jsonify({'error': 'Не авторизован'}), 401
    return jsonify({
        'id': session['user_id'],
        'name': session['user_name'],
        'email': session['user_email'],
        'avatar': session.get('user_avatar'),
    })

@auth_bp.route('/logout')
def logout():
    session.clear()
    return jsonify({'message': 'Выход выполнен'})

@auth_bp.route('/google/callback')
def google_callback():
    # Получаем данные от Google
    google_id = request.args.get('sub') or request.json.get('google_id') if request.is_json else None
    email = request.args.get('email')
    name = request.args.get('name')
    avatar = request.args.get('picture')

    if not google_id:
        return jsonify({'error': 'Нет данных от Google'}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute('SELECT * FROM users WHERE google_id = %s', (google_id,))
    user = cur.fetchone()

    if not user:
        cur.execute('''
            INSERT INTO users (google_id, email, name, avatar)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        ''', (google_id, email, name, avatar))
        user = cur.fetchone()
        conn.commit()

    session['user_id'] = user['id']
    session['user_name'] = user['name']
    session['user_email'] = user['email']
    session['user_avatar'] = user.get('avatar')

    cur.close()
    conn.close()

    return jsonify({'success': True, 'user': dict(user)})

@auth_bp.route('/google/login', methods=['POST'])
def google_login():
    data = request.json
    google_id = data.get('google_id')
    email = data.get('email')
    name = data.get('name')
    avatar = data.get('avatar')

    if not google_id:
        return jsonify({'error': 'Нет данных'}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute('SELECT * FROM users WHERE google_id = %s', (google_id,))
    user = cur.fetchone()

    if not user:
        cur.execute('''
            INSERT INTO users (google_id, email, name, avatar)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        ''', (google_id, email, name, avatar))
        user = cur.fetchone()
        conn.commit()

    session['user_id'] = user['id']
    session['user_name'] = user['name']
    session['user_email'] = user['email']
    session['user_avatar'] = user.get('avatar')

    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'avatar': user.get('avatar'),
        }
    })