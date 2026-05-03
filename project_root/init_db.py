from app import app
from extensions import db, bcrypt
from models import Usuario, Grupo, Tarjeta


def create_initial_data():
    pw_hash = bcrypt.generate_password_hash("mortadela1326").decode('utf-8')

    # Crea usuario administrador
    admin = Usuario(username='admin', password_hash=pw_hash)

    # Crear grupo inicial
    grupo1 = Grupo(nombre='Grupo 1')

    # Crear tarjeta ejemplo
    tarjeta1 = Tarjeta(
        nombre='Tarjeta Ejemplo',
        imagen_url='/blueprints/Corazon3DV/Corazon3DV.jpg',  # Ruta absoluta o relativa según config de Flask
        carpeta='Corazon3DV',  # Nombre carpeta blueprint
        archivo_html='Corazon3DV.html'
    )

    # Relacionamos admin con el grupo y grupo con la tarjeta
    admin.grupos.append(grupo1)
    grupo1.tarjetas.append(tarjeta1)

    # Guardamos todo en la base de datos
    db.session.add_all([admin, grupo1, tarjeta1])
    db.session.commit()
    print("Datos iniciales insertados exitosamente.")


if __name__ == "__main__":
    with app.app_context():
        # Crear todas las tablas (si no existen)
        db.create_all()
        # Insertar datos iniciales
        create_initial_data()
