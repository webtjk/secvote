from flask import Flask, jsonify, session, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import os
from routes.auth import auth_bp
from routes.polls import polls_bp
from routes.votes import votes_bp
from database import init_db

load_dotenv()

# Путь к корню проекта (папка anonim)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

app = Flask(__name__, static_folder=ROOT_DIR, static_url_path='')
app.secret_key = os.getenv('SECRET_KEY', 'securevote_secret_2026')

CORS(app, supports_credentials=True, origins=[
    "http://localhost:5000",
    "http://127.0.0.1:5000",
])

# Регистрируем маршруты
app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(polls_bp, url_prefix='/api/polls')
app.register_blueprint(votes_bp, url_prefix='/api/votes')

# Раздаём HTML файлы из корня проекта
@app.route('/')
def index():
    return send_from_directory(ROOT_DIR, 'index.html')

@app.route('/dashboard.html')
def dashboard():
    return send_from_directory(ROOT_DIR, 'dashboard.html')

@app.route('/vote.html')
def vote():
    return send_from_directory(ROOT_DIR, 'vote.html')

# CSS файлы
@app.route('/style.css')
def style():
    return send_from_directory(ROOT_DIR, 'style.css')

@app.route('/dashboard.css')
def dashboard_css():
    return send_from_directory(ROOT_DIR, 'dashboard.css')

@app.route('/vote.css')
def vote_css():
    return send_from_directory(ROOT_DIR, 'vote.css')

# Проверка
@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'message': 'SecureVote API работает!'})

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)