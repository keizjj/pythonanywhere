from flask_login import UserMixin
from extensions import db
from datetime import datetime, timezone


# ──────────────────────────────────────────────
# Tablas de asociación existentes (sin cambios)
# ──────────────────────────────────────────────

usuarios_grupos = db.Table(
    'usuarios_grupos',
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True),
    db.Column('grupo_id', db.Integer, db.ForeignKey('grupos.id'), primary_key=True)
)

acceso_tarjetas_grupos = db.Table(
    'acceso_tarjetas_grupos',
    db.Column('grupo_id', db.Integer, db.ForeignKey('grupos.id'), primary_key=True),
    db.Column('tarjeta_id', db.Integer, db.ForeignKey('tarjetas.id'), primary_key=True)
)


# ──────────────────────────────────────────────
# Modelos existentes (sin cambios)
# ──────────────────────────────────────────────

class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    grupos = db.relationship('Grupo', secondary=usuarios_grupos, back_populates='usuarios')

    def __repr__(self):
        return f'<Usuario {self.username}>'

    def verificar_password(self, password):
        # Evita import circular (models -> app -> models)
        from extensions import bcrypt
        return bcrypt.check_password_hash(self.password_hash, password)


class Grupo(db.Model):
    __tablename__ = 'grupos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), unique=True, nullable=False)
    usuarios = db.relationship('Usuario', secondary=usuarios_grupos, back_populates='grupos')
    tarjetas = db.relationship('Tarjeta', secondary=acceso_tarjetas_grupos, back_populates='grupos')

    def __repr__(self):
        return f'<Grupo {self.nombre}>'


class Tarjeta(db.Model):
    __tablename__ = 'tarjetas'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    imagen_url = db.Column(db.String(200), nullable=False)
    carpeta = db.Column(db.String(100), nullable=False)
    archivo_html = db.Column(db.String(200), nullable=False)
    grupos = db.relationship('Grupo', secondary='acceso_tarjetas_grupos', back_populates='tarjetas')

    def __repr__(self):
        return f'<Tarjeta {self.nombre}>'


# ──────────────────────────────────────────────
# NUEVOS — Modelos del sistema de chat
# ──────────────────────────────────────────────

class Chat(db.Model):
    """
    Representa una conversación, ya sea directa (1 a 1) o grupal.
    - es_grupo=False  → chat directo entre dos usuarios
    - es_grupo=True   → grupo, solo creado por admin
    - nombre          → solo relevante en grupos; en chats directos
                        se genera dinámicamente desde el otro usuario
    - creado_por      → FK al usuario que creó el chat
    """
    __tablename__ = 'chats'

    id         = db.Column(db.Integer, primary_key=True)
    nombre     = db.Column(db.String(100), nullable=True)          # null en chats directos
    es_grupo   = db.Column(db.Boolean, nullable=False, default=False)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relaciones
    creador   = db.relationship('Usuario', foreign_keys=[creado_por])
    miembros  = db.relationship('ChatUsuario', back_populates='chat',
                                cascade='all, delete-orphan')
    mensajes  = db.relationship('Mensaje', back_populates='chat',
                                cascade='all, delete-orphan')

    def __repr__(self):
        tipo = 'Grupo' if self.es_grupo else 'Directo'
        return f'<Chat {tipo} id={self.id}>'


class ChatUsuario(db.Model):
    """
    Relación entre un usuario y un chat.
    Almacena estado individual: último mensaje leído y si está fijado.
    - last_read_message_id  → id del último Mensaje que el usuario ha visto
                              (None = nunca ha leído nada)
    - is_pinned             → True si el usuario ha fijado este chat (máx 3)
    - joined_at             → cuándo se unió al chat (útil para ordenar y auditoría)
    """
    __tablename__ = 'chat_usuarios'

    chat_id              = db.Column(db.Integer, db.ForeignKey('chats.id'), primary_key=True)
    user_id              = db.Column(db.Integer, db.ForeignKey('usuarios.id'), primary_key=True)
    last_read_message_id = db.Column(db.Integer, db.ForeignKey('mensajes.id'), nullable=True)
    is_pinned            = db.Column(db.Boolean, nullable=False, default=False)
    joined_at            = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Índice compuesto: acelera la consulta "dame los chats de este usuario"
    __table_args__ = (
        db.Index('idx_chat_usuarios_chat_user', 'chat_id', 'user_id'),
    )

    # Relaciones
    chat    = db.relationship('Chat', back_populates='miembros')
    usuario = db.relationship('Usuario', foreign_keys=[user_id])
    ultimo_leido = db.relationship('Mensaje', foreign_keys=[last_read_message_id])

    def __repr__(self):
        return f'<ChatUsuario chat={self.chat_id} user={self.user_id}>'


class Mensaje(db.Model):
    """
    Un mensaje dentro de un chat.
    - client_msg_id  → UUID generado por el cliente para idempotencia:
                       si el cliente reintenta el envío, el servidor detecta
                       el duplicado y devuelve el mensaje ya guardado.
    - is_edited      → True si el mensaje fue modificado después de crearse.
    - edited_at      → timestamp de la última edición (None si nunca editado).
    - content        → texto del mensaje (máx 2000 caracteres).
    """
    __tablename__ = 'mensajes'

    id             = db.Column(db.Integer, primary_key=True)
    chat_id        = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False)
    sender_id      = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    content        = db.Column(db.String(2000), nullable=False)
    created_at     = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    edited_at      = db.Column(db.DateTime, nullable=True)
    is_edited      = db.Column(db.Boolean, nullable=False, default=False)
    client_msg_id  = db.Column(db.String(64), nullable=True)       # UUID del cliente

    # Índices compuestos:
    # 1. Acelera el polling incremental: WHERE chat_id=X AND id > Y
    # 2. Acelera la búsqueda de ediciones recientes: WHERE chat_id=X AND edited_at >= T
    __table_args__ = (
        db.Index('idx_mensajes_chat_id',  'chat_id', 'id'),
        db.Index('idx_mensajes_edited',   'chat_id', 'edited_at'),
        db.UniqueConstraint('chat_id', 'client_msg_id', name='uq_chat_client_msg'),
    )

    # Relaciones
    chat   = db.relationship('Chat', back_populates='mensajes')
    sender = db.relationship('Usuario', foreign_keys=[sender_id])
    estados = db.relationship('MensajeEstado', back_populates='mensaje',
                              cascade='all, delete-orphan')

    def to_dict(self, user_id=None):
        """
        Serializa el mensaje a dict para los endpoints de polling.
        Si se pasa user_id, incluye si el mensaje está eliminado para ese usuario.
        """
        data = {
            'id':         self.id,
            'chat_id':    self.chat_id,
            'sender_id':  self.sender_id,
            'sender':     self.sender.username if self.sender else None,
            'content':    self.content,
            'created_at': self.created_at.isoformat(),
            'edited_at':  self.edited_at.isoformat() if self.edited_at else None,
            'is_edited':  self.is_edited,
        }
        if user_id is not None:
            eliminado = MensajeEstado.query.filter_by(
                mensaje_id=self.id, user_id=user_id
            ).first()
            data['deleted_for_me'] = eliminado is not None
        return data

    def __repr__(self):
        return f'<Mensaje id={self.id} chat={self.chat_id} sender={self.sender_id}>'


class MensajeEstado(db.Model):
    """
    Registro de mensajes eliminados 'solo para mí'.
    Cuando un usuario elimina un mensaje, se crea una fila aquí.
    El mensaje sigue existiendo en la BD y visible para otros participantes.
    - deleted_at  → cuándo el usuario eliminó el mensaje (para auditoría y limpieza)
    """
    __tablename__ = 'mensaje_estados'

    id          = db.Column(db.Integer, primary_key=True)
    mensaje_id  = db.Column(db.Integer, db.ForeignKey('mensajes.id'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    deleted_at  = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Índice compuesto: acelera la limpieza y la consulta de mensajes ocultos
    __table_args__ = (
        db.Index('idx_mensaje_estados_user', 'user_id', 'mensaje_id'),
    )

    # Relaciones
    mensaje = db.relationship('Mensaje', back_populates='estados')
    usuario = db.relationship('Usuario', foreign_keys=[user_id])

    def __repr__(self):
        return f'<MensajeEstado mensaje={self.mensaje_id} user={self.user_id}>'