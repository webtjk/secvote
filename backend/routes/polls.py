from flask import Blueprint, request, jsonify, session
from database import get_db
import random
import string

polls_bp = Blueprint('polls', __name__)

def generate_code():
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(chars, k=6))

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Не авторизован'}), 401
        return f(*args, **kwargs)
    return decorated

@polls_bp.route('/create', methods=['POST'])
@require_auth
def create_poll():
    data = request.json
    question = data.get('question', '').strip()
    options = data.get('options', [])

    if not question:
        return jsonify({'error': 'Введи вопрос'}), 400
    if len(question) > 300:
        return jsonify({'error': 'Вопрос слишком длинный'}), 400
    if len(options) < 2:
        return jsonify({'error': 'Минимум 2 варианта'}), 400
    if len(options) > 10:
        return jsonify({'error': 'Максимум 10 вариантов'}), 400

    conn = get_db()
    cur = conn.cursor()

    # Проверяем лимит голосований
    cur.execute('SELECT COUNT(*) as cnt FROM polls WHERE created_by = %s', (session['user_id'],))
    count = cur.fetchone()['cnt']
    if count >= 10:
        return jsonify({'error': 'Лимит 10 голосований'}), 400

    # Генерируем уникальный код
    code = generate_code()
    while True:
        cur.execute('SELECT id FROM polls WHERE code = %s', (code,))
        if not cur.fetchone():
            break
        code = generate_code()

    # Создаём голосование
    cur.execute('''
        INSERT INTO polls (code, question, created_by, access_type, allowed_domain)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, code
    ''', (code, question, session['user_id'], data.get('access_type', 'open'), data.get('allowed_domain')))
    poll = cur.fetchone()

    # Добавляем варианты
    for opt_text in options:
        if opt_text.strip():
            cur.execute('INSERT INTO options (poll_id, text) VALUES (%s, %s)', (poll['id'], opt_text.strip()))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'success': True, 'code': poll['code'], 'id': poll['id']})

@polls_bp.route('/join/<code>')
@require_auth
def join_poll(code):
    conn = get_db()
    cur = conn.cursor()

    cur.execute('SELECT * FROM polls WHERE code = %s', (code.upper(),))
    poll = cur.fetchone()

    if not poll:
        cur.close()
        conn.close()
        return jsonify({'error': 'Голосование не найдено'}), 404

    cur.execute('SELECT * FROM options WHERE poll_id = %s', (poll['id'],))
    options = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        'id': poll['id'],
        'code': poll['code'],
        'question': poll['question'],
        'closed': poll['closed'],
        'options': [{'id': o['id'], 'text': o['text'], 'vote_count': o['vote_count']} for o in options],
    })

@polls_bp.route('/my')
@require_auth
def my_polls():
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        SELECT p.*, 
               (SELECT COUNT(*) FROM votes v WHERE v.poll_id = p.id) as total_votes
        FROM polls p
        WHERE p.created_by = %s
        ORDER BY p.created_at DESC
    ''', (session['user_id'],))
    polls = cur.fetchall()

    result = []
    for poll in polls:
        cur.execute('SELECT * FROM options WHERE poll_id = %s', (poll['id'],))
        options = cur.fetchall()
        result.append({
            'id': poll['id'],
            'code': poll['code'],
            'question': poll['question'],
            'closed': poll['closed'],
            'total_votes': poll['total_votes'],
            'options': [{'id': o['id'], 'text': o['text'], 'vote_count': o['vote_count']} for o in options],
        })

    cur.close()
    conn.close()
    return jsonify(result)

@polls_bp.route('/<int:poll_id>/toggle', methods=['POST'])
@require_auth
def toggle_poll(poll_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute('SELECT * FROM polls WHERE id = %s AND created_by = %s', (poll_id, session['user_id']))
    poll = cur.fetchone()

    if not poll:
        return jsonify({'error': 'Нет доступа'}), 403

    cur.execute('UPDATE polls SET closed = NOT closed WHERE id = %s RETURNING closed', (poll_id,))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'closed': updated['closed']})

@polls_bp.route('/<int:poll_id>/delete', methods=['DELETE'])
@require_auth
def delete_poll(poll_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute('SELECT * FROM polls WHERE id = %s AND created_by = %s', (poll_id, session['user_id']))
    if not cur.fetchone():
        return jsonify({'error': 'Нет доступа'}), 403

    cur.execute('DELETE FROM polls WHERE id = %s', (poll_id,))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'success': True})