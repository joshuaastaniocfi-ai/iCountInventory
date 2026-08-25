# Third-party imports
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

# Initialize Flask extensions
db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

# Configure login manager
login_manager.login_view = 'auth.login'
