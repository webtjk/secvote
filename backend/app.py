from flask import Flask, jsonify, session, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import os
from routes.auth import auth_bp
from routes.polls import polls_bp
from routes.votes import votes_bp
from database import init_db

load_dotenv()

# FIX: приложение не запустится без SECRET_KEY — нет fallback с известным значением
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError(
        'SECRET_KEY environment variable is required. '
        'Set it in .env or Render environment variables.'
    )

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

app = Flask(__name__, static_folder=ROOT_DIR, static_url_path='')
app.secret_key = SECRET_KEY

# Для мобильных браузеров: Lax работает лучше чем None при OAuth redirect
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 30  # 30 дней

FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://securevote-l5rf.onrender.com')
CORS(app, supports_credentials=True, origins=[
    FRONTEND_URL,
    "http://localhost:5000",
    "http://127.0.0.1:5000",
])

app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(polls_bp, url_prefix='/api/polls')
app.register_blueprint(votes_bp, url_prefix='/api/votes')

@app.route('/')
def index():
    return send_from_directory(ROOT_DIR, 'index.html')

@app.route('/dashboard.html')
def dashboard():
    return send_from_directory(ROOT_DIR, 'dashboard.html')

@app.route('/vote.html')
def vote():
    return send_from_directory(ROOT_DIR, 'vote.html')

@app.route('/style.css')
def style():
    return send_from_directory(ROOT_DIR, 'style.css')

@app.route('/dashboard.css')
def dashboard_css():
    return send_from_directory(ROOT_DIR, 'dashboard.css')

@app.route('/vote.css')
def vote_css():
    return send_from_directory(ROOT_DIR, 'vote.css')

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    init_db()
    app.run(debug=False, port=5000)