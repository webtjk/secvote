from flask import Blueprint, request, jsonify, session
from database import get_db
import hashlib
import math
import os

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
    """SHA-256 анонимизация с SECRET_KEY из окружения"""
    secret = os.environ['SECRET_KEY']  # KeyError если не задан — намеренно
    raw = f"{user_id}:{poll_id}:{secret}"
    return hashlib.sha256(raw.encode()).hexdigest()

@votes_bp.route('/submit', methods=['POST'])
@require_auth
def submit_vote():
    data = request.json
    poll_id = data.get('poll_id')
    option_id = data.get('option_id')

    # FIX: comment_text ограничен 500 символами на сервере
    comment_text = (data.get('comment_text') or '').strip()[:500] or None

    # FIX: weight — строгая валидация, верхний лимит, проверка isfinite
    try:
        raw_weight = data.get('weight')
        if raw_weight is None:
            weight = 1.0
        else:
            weight = float(raw_weight)
            if not math.isfinite(weight) or weight <= 0:
                weight = 1.0
            if weight > 1_000_000:
                return jsonify({'error': 'Вес слишком большой (максимум 1 000 000)'}), 400
    except (TypeError, ValueError):
        weight = 1.0

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

    # FIX: создатель не может голосовать в своём опросе
    if poll['created_by'] == session['user_id']:
        cur.close(); conn.close()
        return jsonify({'error': 'Создатель не может голосовать'}), 403

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

    # FIX: проверка allowed_domain при голосовании
    access_type = poll.get('access_type', 'open')
    allowed_domain = poll.get('allowed_domain')
    if access_type == 'domain' and allowed_domain:
        user_email = session.get('user_email', '')  # FIX: правильный ключ сессии
        user_domain = user_email.split('@')[-1] if '@' in user_email else ''
        if user_domain.lower() != allowed_domain.strip().lower():
            cur.close(); conn.close()
            return jsonify({'error': f'Доступ только для домена {allowed_domain}'}), 403

    # Анонимный хеш — проверяем уже голосовал
    vote_hash = make_vote_hash(session['user_id'], poll_id)
    cur.execute('SELECT id FROM votes WHERE poll_id = %s AND voter_hash = %s', (poll_id, vote_hash))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({'error': 'Вы уже проголосовали'}), 400

    # Для невзвешенного голосования вес всегда 1.0
    if not poll.get('weighted_voting', False):
        weight = 1.0

    # Сохраняем голос
    cur.execute('''
        INSERT INTO votes (poll_id, voter_hash, option_id, comment_text, weight)
        VALUES (%s, %s, %s, %s, %s)
    ''', (poll_id, vote_hash, option_id, comment_text, weight))

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
    min_votes = poll.get('min_votes', 0) or 0
    weighted_voting = bool(poll.get('weighted_voting', False))

    # Проверяем голосовал ли текущий пользователь
    vote_hash = make_vote_hash(session['user_id'], poll_id)
    cur.execute('SELECT id, weight FROM votes WHERE poll_id = %s AND voter_hash = %s', (poll_id, vote_hash))
    my_vote = cur.fetchone()
    has_voted = bool(my_vote)
    my_weight = float(my_vote['weight']) if my_vote else None

    # Создатель? Он видит результаты сразу, без голосования
    is_creator = poll['created_by'] == session['user_id']
    if is_creator:
        has_voted = True  # создатель не голосует, но сразу видит результаты

    # Подсчёт: для взвешенного — сумма весов, для обычного — количество голосов
    cur.execute('SELECT COUNT(*) as cnt, COALESCE(SUM(weight), 0) as weight_sum FROM votes WHERE poll_id = %s', (poll_id,))
    row = cur.fetchone()
    total_count = row['cnt']       # количество участников
    total_weight = float(row['weight_sum'])  # сумма весов

    # Для порога используем количество участников (не сумму весов)
    total = total_count
    threshold_reached = (min_votes == 0 or total >= min_votes or is_creator)

    # Варианты с результатами
    cur.execute('SELECT * FROM options WHERE poll_id = %s ORDER BY vote_count DESC', (poll_id,))
    options = cur.fetchall()

    options_data = []
    if weighted_voting:
        # Взвешенный подсчёт: SUM(weight) по каждому варианту
        cur.execute('''
            SELECT option_id, COALESCE(SUM(weight), 0) as w_sum
            FROM votes WHERE poll_id = %s AND option_id IS NOT NULL
            GROUP BY option_id
        ''', (poll_id,))
        weight_map = {r['option_id']: float(r['w_sum']) for r in cur.fetchall()}

    for opt in options:
        if threshold_reached:
            if weighted_voting:
                w_votes = weight_map.get(opt['id'], 0.0)
                percent = round(w_votes / total_weight * 100) if total_weight > 0 else 0
                options_data.append({
                    'id': opt['id'],
                    'text': opt['text'],
                    'votes': opt['vote_count'],       # количество участников
                    'weight_sum': round(w_votes, 4),  # сумма весов
                    'percent': percent,
                })
            else:
                votes = opt['vote_count']
                percent = round(votes / total * 100) if total > 0 else 0
                options_data.append({
                    'id': opt['id'],
                    'text': opt['text'],
                    'votes': votes,
                    'percent': percent,
                })
        else:
            # Скрываем реальные цифры до достижения порога
            options_data.append({
                'id': opt['id'],
                'text': opt['text'],
                'votes': None,
                'percent': None,
            })

    # Комментарии (для open и choice_comment — создателю показываем все, участнику тоже для open)
    comments = []
    if poll_type in ('open', 'choice_comment') and threshold_reached:
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
            'min_votes': min_votes,
            'weighted_voting': weighted_voting,
        },
        'options': options_data,
        'total': total,
        'total_weight': round(total_weight, 4) if weighted_voting else None,
        'my_weight': my_weight,
        'has_voted': has_voted,
        'threshold_reached': threshold_reached,
        'comments': comments,
        'my_token': vote_hash[:16] + '...' if has_voted else None,
    })