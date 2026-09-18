# Добавить в конец файла backend/routes/auth.py
# (только новый route — остальное не трогать)

import requests as http_requests

@auth_bp.route('/google/callback')
def google_callback():
    """Обработка OAuth redirect от Google (для мобильных устройств)"""
    from flask import redirect, url_for
    import os

    code = request.args.get('code')
    error = request.args.get('error')

    if error or not code:
        return redirect('/?error=cancelled')

    # Обмениваем code на токен
    token_url = 'https://oauth2.googleapis.com/token'
    token_data = {
        'code': code,
        'client_id': os.getenv('GOOGLE_CLIENT_ID'),
        'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
        'redirect_uri': request.host_url.rstrip('/') + '/api/auth/google/callback',
        'grant_type': 'authorization_code',
    }

    try:
        token_res = http_requests.post(token_url, data=token_data, timeout=10)
        token_json = token_res.json()
        id_token = token_json.get('id_token')

        if not id_token:
            return redirect('/?error=no_token')

        # Декодируем JWT (без проверки подписи — Google уже проверил)
        import base64, json
        payload_b64 = id_token.split('.')[1]
        # Добавляем padding если нужно
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64).decode())

        google_id = payload.get('sub')
        email = payload.get('email')
        name = payload.get('name')
        avatar = payload.get('picture')

        if not google_id:
            return redirect('/?error=no_user')

        # Сохраняем/находим пользователя в БД
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

        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['user_email'] = user['email']
        session['user_avatar'] = user.get('avatar')
        cur.close()
        conn.close()

        return redirect('/dashboard.html')

    except Exception as e:
        print(f"OAuth callback error: {e}")
        return redirect('/?error=server_error')