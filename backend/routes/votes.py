from flask import Blueprint, request, jsonify, session
from database import get_db
import hashlib
import secrets

votes_bp = Blueprint('votes', __name__)

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Не авторизован'}), 401
        return f(*args, **kwargs)
    return decorated

def make_vote_hash(user_id, poll_id):
    """SHA-256 анонимизация: никто не может связать голос с пользователем"""
    raw = f"{user_id}:{poll_id}:securevote_salt"
    return hashlib.sha256(raw.encode()).hexdigest()

@votes_bp.route('/submit', methods=['POST'])
@require_auth
def submit_vote():
    data = request.json
    poll_id = data.get('poll_id')
    option_id = data.get('option_id')
    comment_text = (data.get('comment_text') or '').strip() or None

    if not poll_id:
        return jsonify({'error': 'Не указан poll_id'}), 400

    conn = get_db()
    cur = conn.cursor()

    # Получаем опрос
    cur.execute('SELECT * FROM polls WHERE id = %s', (poll_id,))
    poll = cur.fetchone()

    if not poll:
        cur.close(); conn.close()
        return jsonify({'error': 'Голосование не найдено'}), 404

    if poll['closed']:
        cur.close(); conn.close()
        return jsonify({'error': 'Голосование закрыто'}), 400

    poll_type = poll.get('poll_type', 'choice')

    # Проверяем тип: для choice/choice_comment нужен option_id
    if poll_type in ('choice', 'choice_comment') and not option_id:
        cur.close(); conn.close()
        return jsonify({'error': 'Не выбран вариант'}), 400

    # Для open — нужен comment_text
    if poll_type == 'open' and not comment_text:
        cur.close(); conn.close()
        return jsonify({'error': 'Введите ваше мнение'}), 400

    # Если option_id указан — проверяем что он принадлежит этому опросу
    if option_id:
        cur.execute('SELECT * FROM options WHERE id = %s AND poll_id = %s', (option_id, poll_id))
        if not cur.fetchone():
            cur.close(); conn.close()
            return jsonify({'error': 'Неверный вариант'}), 400

    # Анонимный хеш — проверяем уже голосовал
    vote_hash = make_vote_hash(session['user_id'], poll_id)
    cur.execute('SELECT id FROM votes WHERE poll_id = %s AND voter_hash = %s', (poll_id, vote_hash))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({'error': 'Вы уже проголосовали'}), 400

    # Сохраняем голос
    cur.execute('''
        INSERT INTO votes (poll_id, voter_hash, option_id, comment_text)
        VALUES (%s, %s, %s, %s)
    ''', (poll_id, vote_hash, option_id, comment_text))

    # Увеличиваем счётчик варианта (если выбран)
    if option_id:
        cur.execute('UPDATE options SET vote_count = vote_count + 1 WHERE id = %s', (option_id,))

    conn.commit()
    cur.close()
    conn.close()

    # Верификационный токен для пользователя
    token = vote_hash[:16] + '...'

    return jsonify({'success': True, 'token': token})


@votes_bp.route('/results/<int:poll_id>')
@require_auth
def get_results(poll_id):
    conn = get_db()
    cur = conn.cursor()

    # Получаем опрос
    cur.execute('SELECT * FROM polls WHERE id = %s', (poll_id,))
    poll = cur.fetchone()

    if not poll:
        cur.close(); conn.close()
        return jsonify({'error': 'Голосование не найдено'}), 404

    poll_type = poll.get('poll_type', 'choice')

    # Проверяем голосовал ли текущий пользователь
    vote_hash = make_vote_hash(session['user_id'], poll_id)
    cur.execute('SELECT id FROM votes WHERE poll_id = %s AND voter_hash = %s', (poll_id, vote_hash))
    has_voted = bool(cur.fetchone())

    # Создатель? Он видит результаты сразу, без голосования
    is_creator = poll['created_by'] == session['user_id']
    if is_creator:
        has_voted = True  # создатель не голосует, но сразу видит результаты

    # Варианты с результатами
    cur.execute('SELECT * FROM options WHERE poll_id = %s ORDER BY vote_count DESC', (poll_id,))
    options = cur.fetchall()

    # Подсчёт общего количества голосов
    cur.execute('SELECT COUNT(*) as cnt FROM votes WHERE poll_id = %s', (poll_id,))
    total = cur.fetchone()['cnt']

    options_data = []
    for opt in options:
        votes = opt['vote_count']
        percent = round(votes / total * 100) if total > 0 else 0
        options_data.append({
            'id': opt['id'],
            'text': opt['text'],
            'votes': votes,
            'percent': percent,
        })

    # Комментарии (для open и choice_comment — создателю показываем все, участнику тоже для open)
    comments = []
    if poll_type in ('open', 'choice_comment'):
        if is_creator:
            cur.execute('''
                SELECT comment_text FROM votes
                WHERE poll_id = %s AND comment_text IS NOT NULL AND comment_text != ''
                ORDER BY created_at DESC
            ''', (poll_id,))
            comments = [{'text': r['comment_text']} for r in cur.fetchall()]
        elif poll_type == 'open' and has_voted:
            # Обычный участник в open-опросе тоже видит анонимные мнения
            cur.execute('''
                SELECT comment_text FROM votes
                WHERE poll_id = %s AND comment_text IS NOT NULL AND comment_text != ''
                ORDER BY created_at DESC
            ''', (poll_id,))
            comments = [{'text': r['comment_text']} for r in cur.fetchall()]

    cur.close()
    conn.close()

    return jsonify({
        'poll': {
            'id': poll['id'],
            'code': poll['code'],
            'question': poll['question'],
            'closed': poll['closed'],
            'poll_type': poll_type,
            'comment_label': poll.get('comment_label'),
            'is_creator': is_creator,
        },
        'options': options_data,
        'total': total,
        'has_voted': has_voted,
        'comments': comments,
        'my_token': vote_hash[:16] + '...' if has_voted else None,
    })