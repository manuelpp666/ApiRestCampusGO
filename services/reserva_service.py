from datetime import datetime, timedelta

from database import get_connection
from repositories.reserva_repository import ReservaRepository


class ReservaService:
    def crear(self, usuario_id, datos):
        if not isinstance(datos, dict):
            return None, "El body debe ser un objeto JSON", 400

        viajes = datos.get("viajes", [])

        if not isinstance(viajes, list) or len(viajes) not in (1, 2):
            return None, "Debe seleccionar uno o dos viajes", 400
        if any(not isinstance(item, dict) for item in viajes):
            return None, "Los viajes son inválidos", 400

        ids = [item.get("viaje_id") for item in viajes]
        if any(
            isinstance(viaje_id, bool) or not isinstance(viaje_id, int) or viaje_id <= 0
            for viaje_id in ids
        ) or len(ids) != len(set(ids)):
            return None, "Los viajes son inválidos o están repetidos", 400

        connection = get_connection()
        try:
            connection.begin()
            repository = ReservaRepository(connection)

            pasajero_id = repository.obtener_pasajero_id_por_usuario(usuario_id)
            if pasajero_id is None:
                connection.rollback()
                return None, "El usuario no posee perfil de pasajero", 403

            viajes_bd = []
            for item in viajes:
                cantidad = item.get("cantidad", 0)
                tipo = item.get("tipo_tramo")
                if isinstance(cantidad, bool):
                    cantidad = 0
                try:
                    cantidad = int(cantidad)
                except (TypeError, ValueError):
                    cantidad = 0

                if cantidad <= 0 or tipo not in ("IDA", "RETORNO"):
                    connection.rollback()
                    return None, "Datos de tramo inválidos", 400

                viaje = repository.obtener_viaje_para_actualizar(item["viaje_id"])
                if viaje is None:
                    connection.rollback()
                    return None, "Uno de los viajes no existe", 404
                if viaje["estado"] != "DISPONIBLE":
                    connection.rollback()
                    return None, "Uno de los viajes no está disponible", 409
                if viaje["cupos"] < cantidad:
                    connection.rollback()
                    return None, "No existen cupos suficientes", 409
                if str(viaje["conductor_usuario_id"]) == str(usuario_id):
                    connection.rollback()
                    return None, "No puede reservar su propio viaje", 409

                viajes_bd.append((item, viaje, cantidad))

            if len(viajes_bd) == 2:
                tipos = [item["tipo_tramo"] for item, _, _ in viajes_bd]
                if set(tipos) != {"IDA", "RETORNO"}:
                    connection.rollback()
                    return None, "Debe seleccionar IDA y RETORNO", 400

                ida = next(item for item in viajes_bd if item[0]["tipo_tramo"] == "IDA")
                retorno = next(item for item in viajes_bd if item[0]["tipo_tramo"] == "RETORNO")

                fecha_ida = self._combinar_fecha_hora(ida[1]["fecha"], ida[1]["hora"])
                fecha_retorno = self._combinar_fecha_hora(
                    retorno[1]["fecha"], retorno[1]["hora"]
                )
                if fecha_retorno <= fecha_ida:
                    connection.rollback()
                    return None, "El retorno debe ser posterior a la ida", 409

            reserva_id = repository.crear_reserva(pasajero_id)
            for orden, (item, _, cantidad) in enumerate(viajes_bd, start=1):
                repository.crear_detalle(
                    reserva_id,
                    item["viaje_id"],
                    cantidad,
                    item["tipo_tramo"],
                    orden
                )
                repository.descontar_cupos(item["viaje_id"], cantidad)

            connection.commit()
            return {"reserva_id": reserva_id}, "Reserva registrada correctamente", 201
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cancelar(self, usuario_id, reserva_id):
        connection = get_connection()
        try:
            connection.begin()
            repository = ReservaRepository(connection)

            reserva = repository.obtener_reserva_para_actualizar(reserva_id)
            if reserva is None:
                connection.rollback()
                return None, "La reserva no existe", 404
            if str(reserva["pasajero_id"]) != str(usuario_id):
                pasajero_id = repository.obtener_pasajero_id_por_usuario(usuario_id)
                if pasajero_id is None or str(reserva["pasajero_id"]) != str(pasajero_id):
                    connection.rollback()
                    return None, "No puede cancelar una reserva de otro pasajero", 403
            if reserva["estado"] == "CANCELADA":
                connection.rollback()
                return None, "La reserva ya se encuentra cancelada", 409

            detalles = repository.obtener_detalles_para_actualizar(reserva_id)
            if not detalles:
                connection.rollback()
                return None, "La reserva no tiene viajes asociados", 409

            viajes = []
            for detalle in detalles:
                if detalle["estado"] == "CANCELADA":
                    connection.rollback()
                    return None, "La reserva contiene un detalle cancelado", 409

                viaje = repository.obtener_viaje_para_actualizar(detalle["viaje_id"])
                if viaje is None:
                    connection.rollback()
                    return None, "Uno de los viajes de la reserva no existe", 404
                viajes.append((detalle, viaje))

            repository.cancelar_reserva(reserva_id)
            for detalle, _ in viajes:
                repository.cancelar_detalle(detalle["id"])
                repository.devolver_cupos(
                    detalle["viaje_id"],
                    detalle["cantidad"]
                )

            connection.commit()
            return {"reserva_id": reserva_id}, "Reserva cancelada correctamente", 200
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _combinar_fecha_hora(fecha, hora):
        if isinstance(hora, timedelta):
            hora = (datetime.min + hora).time()
        return datetime.combine(fecha, hora)