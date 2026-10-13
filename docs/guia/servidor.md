# Vinci en un servidor (Coolify)

Vinci también corre en un servidor, encendido todo el día, con la imagen de Docker de este repo (`Dockerfile`). La
imagen parte de la imagen oficial de Hermes Agent: un solo contenedor con un solo gateway para tu Vinci y el de
cada amigo, por WhatsApp. Todo lo que cambia (datos del aula, memoria, perfiles, sesión de WhatsApp y `secrets.env`) vive
en el volumen `/opt/data`. Necesita unos 1,5 GB de RAM y unos 10 GB de disco: la imagen sola ocupa casi 5 GB, y la construcción pide más.

Corre una sola copia de Vinci a la vez. Dos copias contestan dos veces por WhatsApp y se rompen la cadena del token de
Canvas una a la otra. Por eso Coolify debe apagar el contenedor viejo antes de encender el nuevo (paso 4).

## Crear la app

1. En tu proyecto, pulsa **+ New** → **Public Repository** y pega la dirección de este repo, rama `main`.
2. En **Build Pack**, elige **Dockerfile**. Vinci no abre ningún puerto: deja vacíos el dominio y los puertos.
3. En **Persistent Storage**, agrega un volumen montado en `/opt/data`.
4. En **Advanced**, activa **Consistent Container Names**. Con un nombre fijo, Coolify apaga el contenedor viejo antes
   de encender el nuevo en cada despliegue. Sin eso, los dos corren a la vez un momento sobre el mismo volumen. No
   actives **Preview Deployments**, y deja una sola réplica.
5. En **Resource Limits**, pon 2 GB de memoria, si el servidor tiene esa memoria libre. Si Vinci llega al tope, se
   reinicia solo Vinci y no las otras apps.
6. En **Environment Variables**, agrega estas:

   | Variable | Valor |
   |---|---|
   | `OPENAI_API_KEY` | tu key de OpenAI (márcala como secreta) |
   | `VINCI_PROVIDER` | `openai-api` |
   | `VINCI_MODEL` | `gpt-6-luna`, u otro modelo del proveedor |

   En una instalación nueva, agrega también `CANVAS_TOKEN`, `WHATSAPP_CAPTAIN` y, si ya publicaste el relé,
   `WHATSAPP_RELAY_URL` y `WHATSAPP_RELAY_TOKEN`. Estas solo llenan lo que falta en `secrets.env`: Vinci renueva su
   token de Canvas ahí, así que un reinicio nunca le devuelve uno viejo. Si pasas tu Vinci desde la PC (abajo), no
   agregues ninguna: la mudanza trae tu `secrets.env`.
7. Pulsa **Deploy**. En cada arranque, la imagen hace lo mismo que `./setup.sh`: crea o actualiza los perfiles, los
   cron jobs y los plugins.
8. Espera a que Coolify muestre la app como **Healthy**, no solo **Running**. La imagen marca **Unhealthy** si la
   creación de perfiles falló o si el gateway no corre: en ese caso, mira los **Logs** (las líneas `[vinci]`).

Para cambiar el modelo, cambia `VINCI_MODEL` y redespliega. Las notas de voz se transcriben con la misma key de
OpenAI. El lector de tu carpeta de apuntes (`[notes]`) no corre en el servidor, porque esa carpeta vive en tu PC.
El servidor usa el `config.toml` del repo: para cambiar algo, haz commit del cambio y redespliega. Así se enciende
Telegram también (`[channels] telegram = true`), junto con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_USER_ID`.

## Pasar tu Vinci de la PC al servidor

La mudanza lleva la memoria, los cuadernos, los amigos, el material y la sesión de WhatsApp. No tienes que vincular
el chip otra vez.

1. En tu PC, apaga el gateway: `hermes gateway stop`.
2. Corre `.venv/bin/python deploy/move.py export`. Crea `vinci-export.bin`, cifrado, en una carpeta temporal propia, y
   te muestra la clave y la carpeta. No pegues la clave en un chat.
3. Sirve solo esa carpeta con un túnel temporal: corre el `python3 -m http.server 8765 --directory …` que te mostró el
   paso 2, y `cloudflared tunnel --url http://localhost:8765` en otra terminal. No sirvas la carpeta del repo: ahí
   está tu `secrets.env` sin cifrar.
4. En Coolify, abre la **Terminal** del contenedor de Vinci y corre `vinci-move import https://…/vinci-export.bin`.
   Escribe la clave cuando la pida. Vinci corrige las rutas de tu PC, guarda aparte lo que ya había en el volumen y
   enciende el gateway.
5. Cierra el túnel y borra la carpeta temporal.
6. En tu PC, aparta los perfiles de Vinci para que tu gateway no los vuelva a encender:
   `mkdir -p ~/.hermes/vinci-en-servidor && mv ~/.hermes/profiles/{vinci,vinci-*,amigo-*} ~/.hermes/vinci-en-servidor/`.

## Vincular WhatsApp en el servidor

Solo hace falta en una instalación nueva, porque la mudanza ya trae la sesión. En la Terminal del
contenedor:

1. Corre `hermes gateway stop`.
2. Corre `espol-bot whatsapp-vincular 593…` con el número de Vinci, y escribe el código en el celular.
3. Corre `espol-bot hermes-perfil`. Enciende WhatsApp en el gateway, ahora que hay sesión.
4. Corre `hermes gateway start`.

Desde la Terminal de Coolify usa siempre `espol-bot`, `vinci-move` y `hermes` tal cual: los tres corren como el
usuario de Hermes, y así no dejan archivos que el gateway no pueda leer.

