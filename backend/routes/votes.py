from flask import Blueprint, request, jsonify, session
from database import get_db
from utils.crypto import hash_voter, generate_token

votes_bp = Blueprint('votes', __name__)

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Не авторизован'}), 401
        return f(*args, **kwargs)
    return decorated

@votes_bp.route('/submit', methods=['POST'])
@require_auth
def submit_vote():
    data = request.json
    poll_id = data.get('poll_id')
    option_id = data.get('option_id')

    if not poll_id or not option_id:
        return jsonify({'error': 'Неверные данные'}), 400

    conn = get_db()
    cur = conn.cursor()

    # Проверяем голосование
    cur.execute('SELECT * FROM polls WHERE id = %s', (poll_id,))
    poll = cur.fetchone()

    if not poll:
        return jsonify({'error': 'Голосование не найдено'}), 404
    if poll['closed']:
        return jsonify({'error': 'Голосование закрыто'}), 403

    # SHA-256 хэш — анонимность!
    voter_hash = hash_voter(session['user_id'], poll_id)

    # Проверяем уже голосовал ли
    cur.execute('SELECT id FROM votes WHERE poll_id = %s AND voter_hash = %s', (poll_id, voter_hash))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'error': 'Ты уже голосовал'}), 409

    # Проверяем вариант принадлежит этому голосованию
    cur.execute('SELECT * FROM options WHERE id = %s AND poll_id = %s', (option_id, poll_id))
    if not cur.fetchone():
        return jsonify({'error': 'Неверный вариант'}), 400

    # Генерируем токен для верификации
    token = generate_token()

    # Сохраняем голос — только хэш, не ID пользователя!
    cur.execute('''
        INSERT INTO votes (poll_id, voter_hash, option_id, token)
        VALUES (%s, %s, %s, %s)
    ''', (poll_id, voter_hash, option_id, token))

    # Обновляем счётчик
    cur.execute('UPDATE options SET vote_count = vote_count + 1 WHERE id = %s', (option_id,))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'token': token,
        'message': 'Твой голос анонимно записан!'
    })

@votes_bp.route('/results/<int:poll_id>')
@require_auth
def get_results(poll_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute('SELECT * FROM polls WHERE id = %s', (poll_id,))
    poll = cur.fetchone()

    if not poll:
        return jsonify({'error': 'Не найдено'}), 404

    cur.execute('SELECT * FROM options WHERE poll_id = %s', (poll_id,))
    options = cur.fetchall()

    total = sum(o['vote_count'] for o in options)

    # Проверяем голосовал ли текущий пользователь
    voter_hash = hash_voter(session['user_id'], poll_id)
    cur.execute('SELECT token FROM votes WHERE poll_id = %s AND voter_hash = %s', (poll_id, voter_hash))
    my_vote = cur.fetchone()

    cur.close()
    conn.close()

    return jsonify({
        'poll': {
            'id': poll['id'],
            'code': poll['code'],
            'question': poll['question'],
            'closed': poll['closed'],
            'is_creator': poll['created_by'] == session['user_id'],
        },
        'options': [{
            'id': o['id'],
            'text': o['text'],
            'votes': o['vote_count'],
            'percent': round((o['vote_count'] / total * 100)) if total > 0 else 0,
        } for o in options],
        'total': total,
        'has_voted': my_vote is not None,
        'my_token': my_vote['token'] if my_vote else None,
    })

@votes_bp.route('/verify/<token>')
def verify_vote(token):
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        SELECT v.token, p.question, o.text as option_text, v.created_at
        FROM votes v
        JOIN polls p ON p.id = v.poll_id
        JOIN options o ON o.id = v.option_id
        WHERE v.token = %s
    ''', (token,))
    vote = cur.fetchone()

    cur.close()
    conn.close()

    if not vote:
        return jsonify({'error': 'Токен не найден'}), 404

    return jsonify({
        'valid': True,
        'question': vote['question'],
        'option': vote['option_text'],
        'voted_at': str(vote['created_at']),
    })