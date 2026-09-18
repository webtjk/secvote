from flask import Blueprint, request, jsonify, session, redirect
from database import get_db
import requests as http_requests
import os

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/me')
def me():
    if 'user_id' not in session:
        return jsonify({'error': 'Не авторизован'}), 401
    return jsonify({
        'id': session['user_id'],
        'name': session['user_name'],
        'email': session['user_email'],
        'avatar': session.get('user_avatar')
    })


@auth_bp.route('/logout')
def logout():
    session.clear()
    return jsonify({'message': 'Выход выполнен'})


@auth_bp.route('/google/login', methods=['POST'])
def google_login():
    """Для десктопного popup входа"""
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
        cur.execute(
            'INSERT INTO users (google_id, email, name, avatar) VALUES (%s, %s, %s, %s) RETURNING *',
            (google_id, email, name, avatar)
        )
        user = cur.fetchone()
        conn.commit()

    session.permanent = True
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
            'avatar': user.get('avatar')
        }
    })


@auth_bp.route('/google/callback')
def google_callback():
    """OAuth redirect от Google — для мобильных браузеров"""
    code = request.args.get('code')
    error = request.args.get('error')

    if error or not code:
        return redirect('/?error=cancelled')

    token_url = 'https://oauth2.googleapis.com/token'
    # Важно: redirect_uri должен совпадать с тем что отправили Google
    redirect_uri = request.host_url.rstrip('/') + '/api/auth/google/callback'

    token_data = {
        'code': code,
        'client_id': os.getenv('GOOGLE_CLIENT_ID'),
        'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }

    try:
        token_res = http_requests.post(token_url, data=token_data, timeout=10)
        token_json = token_res.json()
        id_token = token_json.get('id_token')

        if not id_token:
            print(f"Token error: {token_json}")
            return redirect('/?error=no_token')

        import base64, json as json_lib
        payload_b64 = id_token.split('.')[1]
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json_lib.loads(base64.b64decode(payload_b64).decode())

        google_id = payload.get('sub')
        email = payload.get('email')
        name = payload.get('name')
        avatar = payload.get('picture')

        if not google_id:
            return redirect('/?error=no_user')

        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE google_id = %s', (google_id,))
        user = cur.fetchone()
        if not user:
            cur.execute(
                'INSERT INTO users (google_id, email, name, avatar) VALUES (%s, %s, %s, %s) RETURNING *',
                (google_id, email, name, avatar)
            )
            user = cur.fetchone()
            conn.commit()

        session.permanent = True
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['user_email'] = user['email']
        session['user_avatar'] = user.get('avatar')
        cur.close()
        conn.close()

        # ?logged_in=1 — сигнал для index.html что вход прошёл успешно
        # index.html сразу перенаправит на dashboard без лишнего /api/auth/me запроса
        return redirect('/dashboard.html?logged_in=1')

    except Exception as e:
        print(f"OAuth callback error: {e}")
        return redirect('/?error=server_error')