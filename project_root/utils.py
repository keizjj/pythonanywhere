import logging
import os

from extensions import db, bcrypt
from models import Usuario, Grupo, Tarjeta

logging.basicConfig(level=logging.INFO)

def crear_usuario(username: str, password: str) -> Usuario:
    if Usuario.query.filter_by(username=username).first():
        raise ValueError(f"El usuario '{username}' ya existe.")

    pw_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    usuario = Usuario(username=username, password_hash=pw_hash)
    db.session.add(usuario)
    try:
        db.session.commit()
        logging.info(f"Usuario '{username}' creado.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creando usuario '{username}': {e}")
        raise
    return usuario

def crear_grupo(nombre: str) -> Grupo:
    if Grupo.query.filter_by(nombre=nombre).first():
        raise ValueError(f"El grupo '{nombre}' ya existe.")
    grupo = Grupo(nombre=nombre)
    db.session.add(grupo)
    try:
        db.session.commit()
        logging.info(f"Grupo '{nombre}' creado.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creando grupo '{nombre}': {e}")
        raise
    return grupo

def obtener_tarjetas_desde_carpetas(base_path: str):
    tarjetas = []
    if not os.path.exists(base_path):
        logging.warning(f"Base path '{base_path}' no existe.")
        return tarjetas

    for item in os.listdir(base_path):
        ruta = os.path.join(base_path, item)
        if os.path.isdir(ruta) and os.path.exists(os.path.join(ruta, 'main.py')):
            tarjetas.append(item)
    return tarjetas

def sincronizar_tarjetas_db(base_path: str):
    carpetas = obtener_tarjetas_desde_carpetas(base_path)
    for carpeta in carpetas:
        existencia = Tarjeta.query.filter_by(carpeta=carpeta).first()
        if existencia:
            continue
        imagen_fs_path = os.path.join(base_path, carpeta, 'Corazon3DV.jpg')
        if not os.path.isfile(imagen_fs_path):
            logging.warning(f"No se encontró la imagen esperada: {imagen_fs_path}")
            continue
        imagen_url = '/'.join([base_path, carpeta, 'Corazon3DV.jpg']).replace(os.sep, '/')

        tarjeta = Tarjeta(
            nombre=carpeta.capitalize(),
            imagen_url=imagen_url,
            carpeta=carpeta,
            archivo_html='index.html'
        )
        db.session.add(tarjeta)
    try:
        db.session.commit()
        logging.info("Sincronización de tarjetas completada.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error en sincronización de tarjetas: {e}")
        raise

def asignar_usuario_a_grupo(usuario: Usuario, grupo: Grupo):
    if grupo not in usuario.grupos:
        usuario.grupos.append(grupo)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

def remover_usuario_de_grupo(usuario: Usuario, grupo: Grupo):
    if grupo in usuario.grupos:
        usuario.grupos.remove(grupo)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
