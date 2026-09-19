from flask import Blueprint, request, jsonify, session
from database import get_db, release_db
from auth_utils import require_auth  # FIX #16: единый модуль, не дублируем
import secrets
import re

polls_bp = Blueprint('polls', __name__)

def generate_code():
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(secrets.choice(chars) for _ in range(6))

def parse_bool(value):
    """Строгий парсинг bool — 'false' → False, 'true' → True"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == 'true'
    return bool(value)

DOMAIN_RE = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$')

@polls_bp.route('/create', methods=['POST'])
@require_auth
def create_poll():
    data = request.json
    question = data.get('question', '').strip()
    options = data.get('options', [])
    poll_type = data.get('poll_type', 'choice')
    comment_label = (data.get('comment_label') or '').strip()[:100] or None

    try:
        min_votes = int(data.get('min_votes') or 0)
        if min_votes < 0:
            min_votes = 0
        if min_votes > 9999:
            min_votes = 9999
    except (TypeError, ValueError):
        min_votes = 0

    weighted_voting = parse_bool(data.get('weighted_voting', False))

    if not question:
        return jsonify({'error': 'Введи вопрос'}), 400
    if len(question) > 300:
        return jsonify({'error': 'Вопрос слишком длинный'}), 400
    if poll_type not in ('choice', 'choice_comment', 'open'):
        return jsonify({'error': 'Неверный тип голосования'}), 400

    if poll_type in ('choice', 'choice_comment'):
        if len(options) < 2:
            return jsonify({'error': 'Минимум 2 варианта'}), 400
        if len(options) > 10:
            return jsonify({'error': 'Максимум 10 вариантов'}), 400
        for opt in options:
            if len(str(opt).strip()) > 200:
                return jsonify({'error': 'Вариант слишком длинный (максимум 200 символов)'}), 400

    access_type = data.get('access_type', 'open')
    allowed_domain = (data.get('allowed_domain') or '').strip() or None
    if access_type == 'domain':
        if not allowed_domain:
            return jsonify({'error': 'Укажите домен email'}), 400
        if not DOMAIN_RE.match(allowed_domain):
            return jsonify({'error': 'Неверный формат домена (например: company.com)'}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('SELECT COUNT(*) as cnt FROM polls WHERE created_by = %s', (session['user_id'],))
        count = cur.fetchone()['cnt']
        if count >= 10:
            return jsonify({'error': 'Лимит 10 голосований'}), 400

        # FIX #11: UNIQUE(code) в БД гарантирует уникальность на уровне PostgreSQL
        # Здесь — дополнительная проверка на случай race condition при генерации
        code = generate_code()
        for _ in range(10):
            cur.execute('SELECT id FROM polls WHERE code = %s', (code,))
            if not cur.fetchone():
                break
            code = generate_code()

        cur.execute('''
            INSERT INTO polls (code, question, created_by, access_type, allowed_domain, poll_type, comment_label, min_votes, weighted_voting)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, code
        ''', (code, question, session['user_id'], access_type, allowed_domain, poll_type, comment_label, min_votes, weighted_voting))
        poll = cur.fetchone()

        if poll_type in ('choice', 'choice_comment'):
            for opt_text in options:
                if opt_text.strip():
                    cur.execute('INSERT INTO options (poll_id, text) VALUES (%s, %s)', (poll['id'], opt_text.strip()))

        conn.commit()
        return jsonify({'success': True, 'code': poll['code'], 'id': poll['id']})

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        release_db(conn)  # FIX #15: возвращаем в пул, не закрываем

@polls_bp.route('/join/<code>')
@require_auth
def join_poll(code):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM polls WHERE code = %s', (code.upper(),))
        poll = cur.fetchone()

        if not poll:
            return jsonify({'error': 'Голосование не найдено'}), 404

        access_type = poll.get('access_type', 'open')
        allowed_domain = poll.get('allowed_domain')
        if access_type == 'domain' and allowed_domain:
            user_email = session.get('user_email', '')
            user_domain = user_email.split('@')[-1] if '@' in user_email else ''
            if user_domain.lower() != allowed_domain.strip().lower():
                return jsonify({'error': f'Доступ только для домена {allowed_domain}'}), 403

        cur.execute('SELECT * FROM options WHERE poll_id = %s', (poll['id'],))
        options = cur.fetchall()

        return jsonify({
            'id': poll['id'],
            'code': poll['code'],
            'question': poll['question'],
            'closed': poll['closed'],
            'poll_type': poll.get('poll_type', 'choice'),
            'comment_label': poll.get('comment_label'),
            'options': [{'id': o['id'], 'text': o['text']} for o in options],
        })
    finally:
        cur.close()
        release_db(conn)

@polls_bp.route('/my')
@require_auth
def my_polls():
    conn = get_db()
    cur = conn.cursor()
    try:
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
                'poll_type': poll.get('poll_type', 'choice'),
                'comment_label': poll.get('comment_label'),
                'min_votes': poll.get('min_votes', 0) or 0,
                'weighted_voting': bool(poll.get('weighted_voting', False)),
                'options': [{'id': o['id'], 'text': o['text'], 'vote_count': o['vote_count']} for o in options],
            })

        return jsonify(result)
    finally:
        cur.close()
        release_db(conn)

@polls_bp.route('/<int:poll_id>/toggle', methods=['POST'])
@require_auth
def toggle_poll(poll_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM polls WHERE id = %s AND created_by = %s', (poll_id, session['user_id']))
        if not cur.fetchone():
            return jsonify({'error': 'Нет доступа'}), 403

        cur.execute('UPDATE polls SET closed = NOT closed WHERE id = %s RETURNING closed', (poll_id,))
        updated = cur.fetchone()
        conn.commit()
        return jsonify({'closed': updated['closed']})
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        release_db(conn)

@polls_bp.route('/<int:poll_id>/delete', methods=['DELETE'])
@require_auth
def delete_poll(poll_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM polls WHERE id = %s AND created_by = %s', (poll_id, session['user_id']))
        if not cur.fetchone():
            return jsonify({'error': 'Нет доступа'}), 403

        cur.execute('DELETE FROM polls WHERE id = %s', (poll_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        release_db(conn)

@polls_bp.route('/<int:poll_id>/comments')
@require_auth
def get_comments(poll_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM polls WHERE id = %s AND created_by = %s', (poll_id, session['user_id']))
        if not cur.fetchone():
            return jsonify({'error': 'Нет доступа'}), 403

        cur.execute('''
            SELECT comment_text, created_at
            FROM votes
            WHERE poll_id = %s AND comment_text IS NOT NULL AND comment_text != ''
            ORDER BY created_at DESC
        ''', (poll_id,))
        comments = cur.fetchall()

        return jsonify([{'text': c['comment_text'], 'time': str(c['created_at'])} for c in comments])
    finally:
        cur.close()
        release_db(conn)