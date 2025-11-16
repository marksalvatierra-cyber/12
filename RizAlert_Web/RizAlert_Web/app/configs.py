import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key')
    FIREBASE_CREDENTIALS = os.environ.get('FIREBASE_CREDENTIALS', 'firebase-credentials.json')
    FIREBASE_DATABASE_URL = os.environ.get('FIREBASE_DATABASE_URL', 'https://rizalert-ca105-default-rtdb.asia-southeast1.firebasedatabase.app/') 
    DEBUG = False

class DevelopmentConfig(Config):
    DEBUG = True
    ENV = 'development'

class ProductionConfig(Config):
    ENV = 'production'