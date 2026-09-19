from flask import Blueprint, request, jsonify, session, redirect, make_response
from database import get_db, release_db
import requests as http_requests
import secrets
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


@auth_bp.route('/google/state')
def google_state():
    """State хранится в отдельной cookie — работает на любом воркере gunicorn."""
    state = secrets.token_urlsafe(32)
    resp = make_response(jsonify({'state': state}))
    resp.set_cookie(
        'oauth_state', state,
        max_age=300,
        secure=True,
        httponly=True,
        samesite='Lax'
    )
    return resp


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
    try:
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

        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email'],
                'avatar': user.get('avatar')
            }
        })
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        release_db(conn)


@auth_bp.route('/google/callback')
def google_callback():
    code = request.args.get('code')
    error = request.args.get('error')
    state_received = request.args.get('state')

    if error or not code:
        return redirect('/?error=cancelled')

    # State из cookie — работает независимо от воркера
    state_expected = request.cookies.get('oauth_state')
    if not state_expected or state_received != state_expected:
        return redirect('/?error=invalid_state')

    token_url = 'https://oauth2.googleapis.com/token'
    redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'https://securevote-l5rf.onrender.com/api/auth/google/callback')

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

        if payload.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
            return redirect('/?error=invalid_issuer')
        if payload.get('aud') != os.getenv('GOOGLE_CLIENT_ID'):
            return redirect('/?error=invalid_audience')

        google_id = payload.get('sub')
        email = payload.get('email')
        name = payload.get('name')
        avatar = payload.get('picture')

        if not google_id:
            return redirect('/?error=no_user')

        conn = get_db()
        cur = conn.cursor()
        try:
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
            release_db(conn)

        except Exception as e:
            conn.rollback()
            cur.close()
            release_db(conn)
            raise e

        # Удаляем oauth_state cookie после успешного логина
        resp = make_response(redirect('/dashboard.html?logged_in=1'))
        resp.delete_cookie('oauth_state')
        return resp

    except Exception as e:
        print(f"OAuth callback error: {e}")
        return redirect('/?error=server_error')