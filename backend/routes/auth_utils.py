"""
FIX #16: require_auth вынесен в единый модуль.
Раньше дублировался в polls.py и votes.py — теперь один источник истины.
"""
from functools import wraps
from flask import jsonify, session


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Не авторизован'}), 401
        return f(*args, **kwargs)
    return decorated