"""
ALERTA DEL LP DE PAPERTRADE (corre en GitHub Actions cada ~5 min, con el PC apagado).

Solo LEE la API pública de Papertrade y avisa por Telegram:
  - una vez por cada nivel de AVISOS_LP_USD que el LP cruza bajando
  - al bajar de $2M (la tasa vuelve a 100 PAPER por $1) y al volver a subir
  - un resumen diario a las 9 a. m. (hora Colombia): así sabes que sigue vivo
El token y el chat de Telegram vienen de los "secrets" de GitHub (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID).
Lo último que vio se guarda en estado.json (el workflow lo sube al repositorio).
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

AVISOS_LP_USD = [3_000_000, 2_500_000, 2_200_000]   # niveles de aviso camino a $2M
HORA_RESUMEN = 9                                      # resumen diario (hora Colombia)

API = "https://exchange.papertrade.xyz/query/protocol/summary"
ARCHIVO_ESTADO = Path(__file__).resolve().parent / "estado.json"
COLOMBIA = timezone(timedelta(hours=-5))
E18 = 10 ** 18


def leer_lp():
    """LP, piso ($2M) y tasa de PAPER por $1. Reintenta si la API falla."""
    for intento in range(3):
        try:
            req = urllib.request.Request(API, headers={"User-Agent": "bot-papertrade-alerta-lp"})
            p = json.loads(urllib.request.urlopen(req, timeout=15).read())["paper"]
            break
        except Exception:
            if intento == 2:
                raise
            time.sleep(10)
    lp = int(p["trackedLp"]) / E18
    piso = int(p["cliff"]) / E18
    escala = int(p["decay"]) / E18
    cola = int(p["tailProgress"]) / E18
    tasa_base = int(p["rate"]) / E18
    tasa = tasa_base if lp < piso else tasa_base * (escala / (escala + cola)) ** 2
    return lp, piso, tasa


def telegram(texto):
    datos = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": texto}).encode()
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
    urllib.request.urlopen(url, data=datos, timeout=15)


def millones(usd):
    return f"${usd / 1e6:.2f}M"


def main():
    lp, piso, tasa = leer_lp()
    niveles = sorted(set(AVISOS_LP_USD) | {piso}, reverse=True)
    zona = sum(1 for nivel in niveles if lp < nivel)   # cuántos niveles ya cruzó bajando
    ahora = datetime.now(COLOMBIA)
    hoy = f"{ahora:%Y-%m-%d}"

    anterior = json.loads(ARCHIVO_ESTADO.read_text()) if ARCHIVO_ESTADO.exists() else None
    estado = dict(anterior or {})
    situacion = f"LP {millones(lp)} | {tasa:.1f} PAPER por $1 | faltan {millones(max(lp - piso, 0))} para {millones(piso)}"

    mensajes = []
    if anterior is None:
        mensajes.append(f"✅ Alerta del LP activa en GitHub. {situacion}")
        estado["dia_resumen"] = hoy

    debajo, debajo_antes = lp < piso, (anterior or {}).get("debajo_piso", False)
    if debajo and not debajo_antes:
        mensajes.append(f"🚀 El LP bajó de {millones(piso)} ({millones(lp)}): la tasa volvió a "
                        f"{tasa:.0f} PAPER por $1. Momento de farmear fuerte.")
    elif not debajo and debajo_antes:
        mensajes.append(f"El LP volvió a pasar {millones(piso)} ({millones(lp)}): la tasa bajó a {tasa:.1f} PAPER por $1.")
    elif zona > (anterior or {}).get("zona", 0):
        mensajes.append(f"⚠️ El LP bajó de {millones(niveles[zona - 1])}. {situacion}")

    if estado.get("dia_resumen") != hoy and ahora.hour >= HORA_RESUMEN:
        mensajes.append(f"Resumen diario: {situacion}")
        estado["dia_resumen"] = hoy

    for m in mensajes:
        print(m)
        telegram(m)
    if not mensajes:
        print(f"Sin novedades. {situacion}")

    estado.update(zona=zona, debajo_piso=debajo)
    ARCHIVO_ESTADO.write_text(json.dumps(estado, indent=1) + "\n")


if __name__ == "__main__":
    main()
