import os
from datetime import timedelta


class Config:
    """Base configuration class"""
    # Flask configuration
    SECRET_KEY = "moneyfest"
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = 'sqlite:///inventory.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Flask-Mail configuration
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'nexentry.2025@gmail.com'
    MAIL_PASSWORD = 'xnck aehe cjgu msud'
    MAIL_DEFAULT_SENDER = ('No Reply - iCount', 'nexentry.2025@gmail.com')
    
    # Application specific settings
    BARCODE_BASE = "12082016"
    LOW_STOCK_THRESHOLD_DEFAULT = 10
    EXPIRY_WARNING_DAYS = 90
    EXPIRY_CRITICAL_DAYS = 30
    
    # Pagination settings
    PRODUCTS_PER_PAGE = 2
    REQUISITIONS_PER_PAGE = 10
    LOGS_PER_PAGE = 10
    USERS_PER_PAGE = 2


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    
    # Database configuration for MySQL on PythonAnywhere
    # Format: mysql://username:password@hostname/database_name
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 
        'mysql://nexentry2025:YOUR_ACTUAL_MYSQL_PASSWORD@nexentry2025.mysql.pythonanywhere-services.com/nexentry2025$default')
    
    # Override with environment variables in production
    SECRET_KEY = os.environ.get('SECRET_KEY', Config.SECRET_KEY)
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', Config.MAIL_USERNAME)
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', Config.MAIL_PASSWORD)


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
