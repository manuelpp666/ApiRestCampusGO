from database import get_connection
from repositories.viaje_repository import ViajeRepository
from datetime import date, datetime, timedelta


ESTADOS_VIAJE = {"DISPONIBLE", "COMPLETO", "FINALIZADO", "CANCELADO"}

class ViajeService:
    # Ejercicio 7: validación de viaje duplicado antes del INSERT
    def crear(self, usuario_id, datos):
        obligatorios = ["origen", "destino", "fecha", "hora", "cupos", "precio"]
        if any(campo not in datos for campo in obligatorios):
            return None, "Faltan datos obligatorios", 400
        try:
            cupos = int(datos["cupos"])
            precio = float(datos["precio"])
        except (TypeError, ValueError):
            return None, "Los cupos y el precio deben ser numéricos", 400
        if cupos <= 0:
            return None, "Los cupos deben ser mayores que cero", 400
        if precio < 0:
            return None, "El precio no puede ser negativo", 400

        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            conductor_id = repository.obtener_conductor_id_por_usuario(usuario_id)
            if conductor_id is None:
                return None, "El usuario no posee perfil de conductor", 403
            if repository.existe_duplicado(conductor_id, datos):
                return None, "Ya existe un viaje con los mismos datos", 409

            viaje_id = repository.crear(conductor_id, datos)
            connection.commit()
            return {"viaje_id": viaje_id}, "Viaje creado correctamente", 201
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # Ejercicio 1, 2 y 3: validaciones y filtros por precio, disponibilidad y fechas
    def listar(self, filtros):
        try:
            precio_min = self._numero_opcional(filtros.get("precio_min"))
            precio_max = self._numero_opcional(filtros.get("precio_max"))
        except ValueError:
            return None, "Los precios deben ser numéricos", 400
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            return None, "precio_min debe ser menor o igual que precio_max", 400

        solo_disponibles = filtros.get("solo_disponibles")
        if solo_disponibles is not None:
            if solo_disponibles.lower() not in ("true", "false"):
                return None, "solo_disponibles debe ser true o false", 400
            solo_disponibles = solo_disponibles.lower() == "true"
        else:
            solo_disponibles = False

        for nombre in ("desde", "hasta"):
            valor = filtros.get(nombre)
            if valor:
                try:
                    datetime.strptime(valor, "%Y-%m-%d")
                except ValueError:
                    return None, f"{nombre} debe tener formato YYYY-MM-DD", 400
        if filtros.get("desde") and filtros.get("hasta") and filtros["desde"] > filtros["hasta"]:
            return None, "desde debe ser menor o igual que hasta", 400

        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            viajes = repository.listar(
                origen=filtros.get("origen"),
                destino=filtros.get("destino"),
                fecha=filtros.get("fecha"),
                estado=filtros.get("estado"),
                precio_min=precio_min,
                precio_max=precio_max,
                solo_disponibles=solo_disponibles,
                desde=filtros.get("desde"),
                hasta=filtros.get("hasta")
            )
            self._normalizar_viajes(viajes)
            return viajes, "Viajes obtenidos correctamente", 200
        finally:
            connection.close()

    # Ejercicio 4: viajes del conductor autenticado (con filtro opcional por estado)
    def listar_mios(self, usuario_id, estado=None):
        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            if repository.obtener_conductor_id_por_usuario(usuario_id) is None:
                return None, "El usuario no posee perfil de conductor", 403
            if estado and estado not in ESTADOS_VIAJE:
                return None, "Estado de viaje inválido", 400
            viajes = repository.listar_por_usuario(usuario_id, estado)
            self._normalizar_viajes(viajes)
            return viajes, "Viajes obtenidos correctamente", 200
        finally:
            connection.close()

    # Ejercicio 8: detalle enriquecido del viaje con conductor
    def obtener(self, viaje_id):
        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            viaje = repository.obtener_por_id(viaje_id)
            if viaje is None:
                return None, "Viaje no encontrado", 404

            if isinstance(viaje.get("hora"),timedelta):
                viaje["hora"] = str(viaje["hora"])

            if isinstance(viaje.get("fecha"), date):
                viaje["fecha"] = viaje["fecha"].isoformat()

            return viaje, "Viaje obtenido correctamente", 200

        finally:
            connection.close()

    # Ejercicio 5: actualización de cupos con validaciones de negocio
    def actualizar_cupos(self, usuario_id, viaje_id, datos):
        if not isinstance(datos, dict):
            return None, "El body debe ser un objeto JSON", 400
        if set(datos) != {"cupos"} or isinstance(datos["cupos"], bool):
            return None, "El body debe contener únicamente cupos", 400
        if not isinstance(datos["cupos"], int) or datos["cupos"] < 0:
            return None, "Los cupos deben ser un entero mayor o igual que cero", 400

        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            viaje = repository.obtener_por_id(viaje_id)
            if viaje is None:
                return None, "Viaje no encontrado", 404
            if str(viaje["conductor_usuario_id"]) != str(usuario_id):
                return None, "No puede modificar un viaje de otro conductor", 403
            if viaje["estado"] in ("FINALIZADO", "CANCELADO"):
                return None, "El estado actual no permite modificar el viaje", 409

            repository.actualizar_cupos(viaje_id, datos["cupos"])
            connection.commit()
            return {"viaje_id": viaje_id, "cupos": datos["cupos"]}, "Cupos actualizados correctamente", 200
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # Ejercicio 6: validación de transiciones de estado del viaje
    def actualizar_estado(self, usuario_id, viaje_id, datos):
        if not isinstance(datos, dict):
            return None, "El body debe ser un objeto JSON", 400
        if set(datos) != {"estado"} or datos["estado"] not in ESTADOS_VIAJE:
            return None, "El estado de viaje es inválido", 400

        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            viaje = repository.obtener_por_id(viaje_id)
            if viaje is None:
                return None, "Viaje no encontrado", 404
            if str(viaje["conductor_usuario_id"]) != str(usuario_id):
                return None, "No puede modificar un viaje de otro conductor", 403
            if viaje["estado"] in ("FINALIZADO", "CANCELADO"):
                return None, "El estado actual no permite cambiar el viaje", 409
            if datos["estado"] == viaje["estado"]:
                return None, "El viaje ya tiene ese estado", 409
            if viaje["estado"] == "DISPONIBLE" and datos["estado"] not in ("COMPLETO", "CANCELADO"):
                return None, "La transición de estado no es válida", 409
            if viaje["estado"] == "COMPLETO" and datos["estado"] not in ("DISPONIBLE", "FINALIZADO", "CANCELADO"):
                return None, "La transición de estado no es válida", 409

            repository.actualizar_estado(viaje_id, datos["estado"])
            connection.commit()
            return {"viaje_id": viaje_id, "estado": datos["estado"]}, "Estado actualizado correctamente", 200
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # Ejercicio 10: reporte agrupado por estado para el conductor autenticado
    def resumen(self, usuario_id):
        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            if repository.obtener_conductor_id_por_usuario(usuario_id) is None:
                return None, "El usuario no posee perfil de conductor", 403
            resumen = repository.resumen_por_usuario(usuario_id)
            return resumen, "Resumen obtenido correctamente", 200
        finally:
            connection.close()

    @staticmethod
    def _numero_opcional(valor):
        if valor is None or valor == "":
            return None
        return float(valor)

    @staticmethod
    def _normalizar_viajes(viajes):
        for viaje in viajes:
            if isinstance(viaje.get("hora"), timedelta):
                viaje["hora"] = str(viaje["hora"])
            if isinstance(viaje.get("fecha"), date):
                viaje["fecha"] = viaje["fecha"].isoformat()

    def actualizar(self, usuario_id, viaje_id, datos):
        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            viaje = repository.obtener_por_id(viaje_id)
            if viaje is None:
                return None, "Viaje no encontrado", 404
            if str(viaje["conductor_usuario_id"]) != str(usuario_id):
                return None, "No puede modificar un viaje de otro conductor", 403
            if viaje["estado"] in ("FINALIZADO", "CANCELADO"):
                return None, "El estado actual no permite modificar el viaje", 409

            repository.actualizar(viaje_id, datos)
            connection.commit()
            return {"viaje_id": viaje_id}, "Viaje actualizado correctamente", 200
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # Ejercicio 9: cancelación con validación de propietario y estado terminal
    def cancelar(self, usuario_id, viaje_id):
        connection = get_connection()
        try:
            repository = ViajeRepository(connection)
            viaje = repository.obtener_por_id(viaje_id)
            if viaje is None:
                return None, "Viaje no encontrado", 404
            if str(viaje["conductor_usuario_id"]) != str(usuario_id):
                return None, "No puede cancelar un viaje de otro conductor", 403
            if viaje["estado"] == "FINALIZADO":
                return None, "No puede cancelar un viaje finalizado", 409
            if viaje["estado"] == "CANCELADO":
                return None, "El viaje ya se encuentra cancelado", 409

            repository.cancelar(viaje_id)
            connection.commit()
            return {"viaje_id": viaje_id}, "Viaje cancelado correctamente", 200
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()