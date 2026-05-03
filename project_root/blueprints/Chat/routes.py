from flask import jsonify, request, abort, render_template
from flask_login import login_required, current_user
from extensions import db
from models import Chat, ChatUsuario, Mensaje, MensajeEstado, Usuario, Tarjeta
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from . import chat_bp


# ─────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────

EDIT_WINDOW_SECONDS = 120
MAX_PINNED = 3
MAX_CONTENT_LENGTH = 2000


# ─────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────

def tiene_tarjeta_chat(usuario):
    tarjeta_chat = Tarjeta.query.filter(func.lower(Tarjeta.carpeta) == 'chat').first()
    if not tarjeta_chat:
        return False
    return any(tarjeta_chat in grupo.tarjetas for grupo in usuario.grupos)


def es_miembro(chat_id, user_id):
    return ChatUsuario.query.filter_by(chat_id=chat_id, user_id=user_id).first()


def nombre_chat_directo(chat, user_id):
    if chat.es_grupo:
        return chat.nombre
    for cu in chat.miembros:
        if cu.user_id != user_id:
            return cu.usuario.username
    return 'Chat'


def ultimo_mensaje_visible(chat_id, user_id):
    eliminados = db.session.query(MensajeEstado.mensaje_id).filter_by(user_id=user_id)
    return (
        Mensaje.query
        .filter(Mensaje.chat_id == chat_id, ~Mensaje.id.in_(eliminados))
        .order_by(Mensaje.id.desc())
        .first()
    )


def contar_no_leidos(chat_id, user_id):
    cu = es_miembro(chat_id, user_id)
    if not cu:
        return 0

    eliminados = db.session.query(MensajeEstado.mensaje_id).filter_by(user_id=user_id)

    last_read = cu.last_read_message_id or 0

    return Mensaje.query.filter(
        Mensaje.chat_id == chat_id,
        Mensaje.id > last_read,
        Mensaje.sender_id != user_id,
        ~Mensaje.id.in_(eliminados)
    ).count()


def serializar_chat(chat, user_id):
    cu = es_miembro(chat.id, user_id)
    ult = ultimo_mensaje_visible(chat.id, user_id)

    return {
        'id': chat.id,
        'nombre': nombre_chat_directo(chat, user_id),
        'es_grupo': chat.es_grupo,
        'is_pinned': cu.is_pinned if cu else False,
        'no_leidos': contar_no_leidos(chat.id, user_id),
        'ultimo_msg': ult.content[:60] if ult else '',
        'ultimo_msg_at': ult.created_at.isoformat() if ult else None,
    }


def usuarios_con_chat():
    tarjeta_chat = Tarjeta.query.filter(func.lower(Tarjeta.carpeta) == 'chat').first()
    if not tarjeta_chat:
        return []

    resultado = set()
    for grupo in tarjeta_chat.grupos:
        for usuario in grupo.usuarios:
            if usuario.id != current_user.id:
                resultado.add(usuario)

    return list(resultado)


# ─────────────────────────────────────────────────────────
# Guard global
# ─────────────────────────────────────────────────────────

@chat_bp.before_request
@login_required
def verificar_acceso_chat():
    if not tiene_tarjeta_chat(current_user):
        abort(403)


# ─────────────────────────────────────────────────────────
# INDEX (MEJORADO)
# ─────────────────────────────────────────────────────────

@chat_bp.route('/', methods=['GET'])
def index():
    memberships = ChatUsuario.query.filter_by(user_id=current_user.id).all()

    chats_data = [serializar_chat(cu.chat, current_user.id) for cu in memberships]

    # ordenar: fijados primero + último mensaje
    chats_data.sort(key=lambda c: (
        not c['is_pinned'],
        c['ultimo_msg_at'] or ''
    ))

    return render_template(
        'Chat_home.html',
        chats=chats_data,
        es_admin=(current_user.username == 'admin'),
        posibles_usuarios=usuarios_con_chat()
    )


# ─────────────────────────────────────────────────────────
# ROOM (MEJORADO)
# ─────────────────────────────────────────────────────────

@chat_bp.route('/<int:chat_id>', methods=['GET'])
def room(chat_id):
    cu = es_miembro(chat_id, current_user.id)
    if not cu:
        abort(403)

    chat = Chat.query.get_or_404(chat_id)

    eliminados = db.session.query(MensajeEstado.mensaje_id).filter_by(user_id=current_user.id)

    mensajes = (
        Mensaje.query
        .filter(Mensaje.chat_id == chat_id, ~Mensaje.id.in_(eliminados))
        .order_by(Mensaje.id.desc())
        .limit(50)
        .all()
    )

    mensajes.reverse()

    if mensajes:
        cu.last_read_message_id = mensajes[-1].id
        db.session.commit()

    return render_template(
        'Chat_room.html',
        chat=chat,
        nombre_chat=nombre_chat_directo(chat, current_user.id),
        mensajes=[m.to_dict(user_id=current_user.id) for m in mensajes],
        current_user_id=current_user.id,
        es_admin=(current_user.username == 'admin'),
        edit_window=EDIT_WINDOW_SECONDS,
        last_id=mensajes[-1].id if mensajes else 0,
        server_time=datetime.now(timezone.utc).timestamp()
    )


# ─────────────────────────────────────────────────────────
# NUEVO DIRECTO (MEJORADO + SEGURO)
# ─────────────────────────────────────────────────────────

@chat_bp.route('/nuevo-directo', methods=['POST'])
def nuevo_directo():
    data = request.get_json(silent=True) or {}
    otro_id = data.get('user_id')

    if not otro_id:
        return jsonify({'error': 'Falta user_id'}), 400

    if otro_id == current_user.id:
        return jsonify({'error': 'No puedes crear un chat contigo mismo'}), 400

    otro = Usuario.query.get(otro_id)
    if not otro or not tiene_tarjeta_chat(otro):
        return jsonify({'error': 'Usuario inválido'}), 400

    chats_current = db.session.query(ChatUsuario.chat_id).filter_by(user_id=current_user.id)
    chats_otro = db.session.query(ChatUsuario.chat_id).filter_by(user_id=otro_id)

    existente = Chat.query.filter(
        Chat.id.in_(chats_current),
        Chat.id.in_(chats_otro),
        Chat.es_grupo == False
    ).first()

    if existente:
        return jsonify({'ok': True, 'chat_id': existente.id, 'nuevo': False})

    chat = Chat(es_grupo=False, creado_por=current_user.id)
    db.session.add(chat)
    db.session.flush()

    db.session.add(ChatUsuario(chat_id=chat.id, user_id=current_user.id))
    db.session.add(ChatUsuario(chat_id=chat.id, user_id=otro_id))

    db.session.commit()

    return jsonify({'ok': True, 'chat_id': chat.id, 'nuevo': True}), 201


# ─────────────────────────────────────────────────────────
# MENSAJES (MEJORADO CON IntegrityError)
# ─────────────────────────────────────────────────────────

@chat_bp.route('/<int:chat_id>/mensajes', methods=['POST'])
def send_mensaje(chat_id):
    if not es_miembro(chat_id, current_user.id):
        abort(403)

    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    client_msg_id = (data.get('client_msg_id') or '').strip()

    if not content:
        return jsonify({'error': 'Vacío'}), 400

    if len(content) > MAX_CONTENT_LENGTH:
        return jsonify({'error': 'Muy largo'}), 400

    if client_msg_id:
        existente = Mensaje.query.filter_by(
            chat_id=chat_id,
            client_msg_id=client_msg_id
        ).first()
        if existente:
            return jsonify({'ok': True, 'mensaje': existente.to_dict(), 'duplicado': True})

    msg = Mensaje(
        chat_id=chat_id,
        sender_id=current_user.id,
        content=content,
        client_msg_id=client_msg_id or None
    )
    db.session.add(msg)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existente = Mensaje.query.filter_by(
            chat_id=chat_id,
            client_msg_id=client_msg_id
        ).first()
        if existente:
            return jsonify({'ok': True, 'mensaje': existente.to_dict(), 'duplicado': True})
        return jsonify({'error': 'Error DB'}), 500

    return jsonify({'ok': True, 'mensaje': msg.to_dict(), 'duplicado': False}), 201


# ─────────────────────────────────────────────────────────
# RESTO (SIN ROMPER)
# ─────────────────────────────────────────────────────────

@chat_bp.route('/mensaje/<int:msg_id>', methods=['PATCH'])
def edit_mensaje(msg_id):
    msg = Mensaje.query.get_or_404(msg_id)

    if not es_miembro(msg.chat_id, current_user.id):
        abort(403)

    if msg.sender_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403

    edad = (datetime.now(timezone.utc) - msg.created_at.replace(tzinfo=timezone.utc)).total_seconds()
    if edad > EDIT_WINDOW_SECONDS:
        return jsonify({'error': 'Tiempo expirado'}), 403

    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()

    if not content:
        return jsonify({'error': 'Vacío'}), 400

    msg.content = content
    msg.edited_at = datetime.now(timezone.utc)
    msg.is_edited = True
    db.session.commit()

    return jsonify({'ok': True, 'mensaje': msg.to_dict()})


@chat_bp.route('/mensaje/<int:msg_id>/eliminar', methods=['POST'])
def eliminar_mensaje(msg_id):
    msg = Mensaje.query.get_or_404(msg_id)

    if not es_miembro(msg.chat_id, current_user.id):
        abort(403)

    if not MensajeEstado.query.filter_by(mensaje_id=msg_id, user_id=current_user.id).first():
        db.session.add(MensajeEstado(mensaje_id=msg_id, user_id=current_user.id))
        db.session.commit()

    return jsonify({'ok': True})


@chat_bp.route('/<int:chat_id>/fijar', methods=['POST'])
def fijar_chat(chat_id):
    cu = es_miembro(chat_id, current_user.id)
    if not cu:
        abort(403)

    if cu.is_pinned:
        return jsonify({'ok': True})

    fijados = ChatUsuario.query.filter_by(user_id=current_user.id, is_pinned=True).count()

    if fijados >= MAX_PINNED:
        return jsonify({'error': 'Límite alcanzado'}), 409

    cu.is_pinned = True
    db.session.commit()

    return jsonify({'ok': True})


@chat_bp.route('/<int:chat_id>/desfijar', methods=['POST'])
def desfijar_chat(chat_id):
    cu = es_miembro(chat_id, current_user.id)
    if not cu:
        abort(403)

    cu.is_pinned = False
    db.session.commit()

    return jsonify({'ok': True})