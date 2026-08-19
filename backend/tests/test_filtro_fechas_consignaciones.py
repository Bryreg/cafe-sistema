"""EL FILTRO DE FECHAS TIENE QUE HABLAR EN HORA DE CALI.

`CajaTurno.fecha_cierre` guarda instantes en UTC y Colombia va CINCO HORAS ATRÁS.
El filtro de `get_resumen_admin` armaba el rango con `datetime(desde.year, ...)`,
o sea medianoche UTC — las 19:00 del día anterior en Cali.

Palmetto cierra 19:42, que son las 00:42 UTC del día SIGUIENTE. Con eso, TODOS
sus días caían del lado equivocado: pedir «del 15 al 15» no devolvía el sábado, y
el sábado aparecía al filtrar el domingo. Un mes entero corrido un día.

Y el peor caso no es el número: es que un día no aparezca en su propia fecha. Eso
no se lee como un filtro raro — se lee como que el sistema perdió la información.
"""
import unittest

from tests.base_cuadre import CuadreCajaBase
from app.services import consignaciones as consig_svc


class FiltroEnHoraDeCaliTest(CuadreCajaBase):

    def _turno_que_cierra(self, dia, hora, *, base=0, abre=8):
        """`base` es lo que ya había en el cajón: dos turnos del mismo día
        encadenan, y abrir el segundo en cero le inventaría un faltante."""
        t = self.abrir(base_real=base, momento=self.momento(dia, abre))
        self.vender_efectivo(t, 200_000)
        self.cerrar(t, contado=base + 200_000, momento=self.momento(dia, hora))
        return t

    def ids(self, **rango):
        return {f["turno_id"] for f in
                consig_svc.get_resumen_admin(self.db, self.palmetto.id, **rango)}

    def test_el_turno_que_cierra_a_las_1942_aparece_en_SU_dia(self):
        """EL CASO DE PALMETTO. 19:42 en Cali son las 00:42 UTC del día siguiente:
        con el rango armado en UTC crudo, este turno no aparecía en su fecha."""
        sabado = self.dia(-3)
        t = self._turno_que_cierra(sabado, 19)
        self.assertIn(t.id, self.ids(desde=sabado, hasta=sabado))

    def test_y_no_aparece_en_el_dia_siguiente(self):
        """La otra mitad: si solo se corriera el borde de abajo, el turno saldría
        en los dos días y el total del mes contaría de más."""
        sabado, domingo = self.dia(-3), self.dia(-2)
        t = self._turno_que_cierra(sabado, 19)
        self.assertNotIn(t.id, self.ids(desde=domingo, hasta=domingo))

    def test_un_turno_que_cierra_temprano_tambien_cae_en_su_dia(self):
        """El control: los cierres de la mañana nunca estuvieron rotos, y el
        arreglo no puede haberlos movido."""
        sabado = self.dia(-3)
        t = self._turno_que_cierra(sabado, 11)
        self.assertIn(t.id, self.ids(desde=sabado, hasta=sabado))
        self.assertNotIn(t.id, self.ids(desde=self.dia(-2), hasta=self.dia(-2)))

    def test_el_borde_de_las_1900_en_cali(self):
        """Las 19:00 de Cali son exactamente medianoche UTC: es el instante en el
        que el rango viejo cambiaba de día. Un minuto antes y un minuto después
        tienen que caer los dos en el MISMO día de Cali."""
        sabado = self.dia(-3)
        temprano = self._turno_que_cierra(sabado, 18)
        tarde = self._turno_que_cierra(sabado, 20, base=200_000, abre=19)
        del_sabado = self.ids(desde=sabado, hasta=sabado)
        self.assertIn(temprano.id, del_sabado)
        self.assertIn(tarde.id, del_sabado)

    def test_sin_rango_siguen_saliendo_todos(self):
        sabado = self.dia(-3)
        t = self._turno_que_cierra(sabado, 19)
        self.assertIn(t.id, self.ids())


if __name__ == "__main__":
    unittest.main()
