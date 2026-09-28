# Weather Moto

Evalúa si conviene salir en moto usando el pronóstico de una zona cercana, no sólo
del punto central. Consulta Open-Meteo para el centro y ocho direcciones en los
anillos de 3 km y del radio configurado; después toma el escenario más adverso de
cada hora.

El resultado puede mostrarse en consola, enviarse a Telegram o calcularse con la
ubicación que una persona comparta con el bot.

## Instalación

Requiere Python 3.10 o posterior.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` con las coordenadas de salida. Para activar Telegram completa
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`; ambos son opcionales, pero deben estar
presentes juntos. El chat ID también actúa como lista de acceso: el bot ignorará
cualquier mensaje que provenga de otro chat.

## Uso

```bash
python3 main.py
```

Si Telegram está configurado, el informe también se envía al chat. Para ejecutar
sin enviar un mensaje, por ejemplo al hacer una prueba:

```bash
python3 main.py --no-telegram
```

## Análisis con ubicación compartida por Telegram

Con Telegram configurado, inicia el proceso que escucha las ubicaciones:

```bash
python3 main.py --listen-telegram
```

Abre el chat privado con el bot, envía `/start` (también sirve `/ubicacion`) y
pulsa **“📍 Compartir mi ubicación”**. Telegram enviará las coordenadas GPS que
autorices; el bot analiza el centro en esas coordenadas y el radio definido en
`WEATHER_RADIUS_KM`, y devuelve el informe en el mismo chat. La ubicación de
`.env` no interviene en esa consulta y no se guarda en disco.

La precisión física depende del GPS y de los permisos del teléfono; el bot usa
las coordenadas recibidas directamente como centro del análisis, sin geocodificar
una dirección. Las coordenadas se muestran a seis decimales en la respuesta.

`--listen-telegram` usa long polling, así que debe quedar ejecutándose (por
ejemplo, en una terminal, `systemd` o un contenedor) y no puede convivir con un
webhook activo para el mismo bot. `TELEGRAM_POLL_TIMEOUT_SECONDS` controla la
espera de cada consulta y admite valores entre 1 y 50 segundos (30 por defecto).

## Criterios de recomendación

- 🟢 **APTO**: sin lluvia relevante, probabilidad menor a 30 % y viento menor a
  35 km/h.
- 🟡 **PRECAUCIÓN**: lluvia ligera, probabilidad entre 30 % y 60 %, o viento de
  35 km/h o más.
- 🟠 **ESPERAR**: más de 1 mm/h de lluvia o más de 60 % de probabilidad de lluvia.
- 🔴 **TRANSPORTE ALTERNATIVO**: tormenta eléctrica, más de 3 mm/h, viento mayor
  de 45 km/h o ráfagas mayores de 60 km/h.

Para estimar la espera se busca el primer bloque consecutivo de
`DRY_WINDOW_HOURS` (2 por defecto) con precipitación de hasta 0.1 mm, probabilidad
menor a 30 %, sin tormenta y con viento moderado. Es un apoyo para decidir, no una
garantía: verifica siempre las condiciones reales antes de circular.
