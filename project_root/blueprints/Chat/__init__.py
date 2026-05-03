from flask import Blueprint

chat_bp = Blueprint(
    'chat',
    __name__,
    url_prefix='/chat',
    template_folder='templates'
)

from . import routes