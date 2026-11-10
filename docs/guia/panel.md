# El panel de administración

El panel es una página para ti, el dueño de la instalación: muestra si Vinci está vivo, cuánto gasta y qué hizo en
cada conversación. La página solo lee: no usa el modelo, no llama al aula y no cambia nada. La puerta del agente
([abajo](#el-agente-desde-tu-pc)) es aparte, con su propia clave.

## Qué muestra

El panel tiene el diseño de las páginas de Vinci (el token y el dashboard) y tres pestañas. Arriba de las tres
ves si Vinci está vivo, si WhatsApp está conectado, los turnos trabados (más de 5 min) y los errores de las últimas
24 h.

| Pestaña | Qué ves |
|---|---|
| Personas | Cuántas personas funcionan, cuántas tienen el token cortado y cuántas no conectan su aula. Toca un número para ver solo a esas. Debajo hay un buscador: escribe un nombre o las últimas cifras de un número (o presiona `/` en el teclado). Cada persona es una tarjeta con su estado, por qué está así en una línea y su gasto de 7 días. De cada amigo ves su nombre y las 3 últimas cifras de su número. Al final, «Cómo funcionan el sondeo y el token» lo explica en 4 párrafos. |
| Ficha de una persona | Se abre al tocar su tarjeta (o con `Enter` en el buscador, para la primera). Arriba dice qué pasa y quién lo arregla. Debajo: su gasto de 7 días, sus llamadas al modelo, si le llegaron las novedades, su gasto de cada día, su historia (cuándo la invitaste, la última renovación del token, cuándo Vinci le pidió reconectar, cuándo te escribió sin conectar y cuándo vence su enlace), la salud de su Vinci y sus conversaciones. Al tocar una conversación ves sus pasos. |
| Gasto | El gasto de hoy, de 7 días y de 14 días. El gráfico muestra los últimos 14 días, por grupo: tu Vinci, bots de materia y amigos. Al pasar el mouse sobre un día (o tocarlo en el celular) ves su total frente al promedio, el gasto por grupo y por bot, las llamadas al modelo y los tokens. Debajo, las llamadas, los tokens, el costo y el último día de uso de cada perfil y modelo. |
| Sistema | La salud de cada Vinci (lo mismo que `/estado` y `espol-bot doctor`: el sondeo, la lectura del aula, el mantenimiento y el token de Canvas; de un amigo ves solo lo que falla), las tareas automáticas de Hermes, los errores y avisos de `errors.log` agrupados por tipo, y las conversaciones recientes. Al tocar una conversación ves sus pasos con el tiempo entre cada uno: ahí ves dónde se trabó. |

En el servidor, las tareas automáticas de Hermes son solo la agenda y los apuntes: el sondeo, el resumen y el
mantenimiento corren aparte, como servicios, y su última corrida sale en la salud de cada Vinci.

El texto de un chat solo se ve en tus chats privados. De un amigo o de un grupo, el panel muestra solo los tiempos,
las herramientas y el largo de cada mensaje.

Los costos son los que estima Hermes con su tabla de precios, no la factura de tu proveedor. Hermes guarda un
solo total por conversación: si una conversación cruza la medianoche, el panel reparte su gasto entre los días según
cuántas respuestas dio Vinci en cada uno.

## Avisos por WhatsApp

Cada 10 minutos, tu mantenimiento revisa la salud de cada Vinci, el tuyo y el de cada amigo. Cuando algo pasa a
fallar (❌), Vinci te escribe una sola vez, por ejemplo «⚠️ Vigilancia · Angel · Token de Canvas: …». Cuando se
arregla, te escribe «✅ Vigilancia · Angel · Token de Canvas: volvió a estar bien». Si lo mismo falla o se arregla
para varios a la vez, llega un solo mensaje con todos los nombres: «⚠️ Vigilancia · Tú, Angel y Beto · Sondeo: …».
El sondeo cuenta como caído después de 25 minutos sin correr (dos vueltas y media). Lo que solo está para revisar
(⚠️) no te avisa. Tu propio token tampoco, porque tu Vinci ya te lo dice en su chat. Si WhatsApp no responde en
ese momento, el aviso sale en una revisión siguiente.

`espol-bot doctor` también muestra a cada amigo, debajo de tu estado.

## En Coolify

El contenedor ya trae el panel encendido en el puerto 8787. Para verlo:

1. En Coolify, abre la app de Vinci. En **General**, pon el dominio del panel en **Domains** (por ejemplo
   `https://vinci.tu-dominio.com`) y `8787` en **Ports Exposes**.
2. Presiona **Redeploy** y espera a que diga **Healthy**.
3. En la **Terminal** del contenedor, corre `espol-bot panel --nueva-clave`. Imprime el enlace con la clave, con el
   dominio del paso 1.
4. Abre ese enlace. El navegador guarda la clave 30 días.

Sin la clave, el dominio responde «no existe». Con la clave ves todo el panel menos el texto de los chats, también los
tuyos. Para cortar el acceso, corre otra vez `espol-bot panel --nueva-clave`.

## Entrar con Google

Con esto, solo tu cuenta de Google abre el panel, y el enlace con la clave deja de servir:

1. En [Google Cloud](https://console.cloud.google.com), crea un proyecto. En **Google Auth Platform**, configura la
   pantalla de consentimiento como «Usuarios externos» y agrega tu cuenta en **Público → Usuarios de prueba**.
2. En **Clientes**, crea un ID de cliente de tipo «Aplicación web». En «Orígenes autorizados de JavaScript», pon el
   dominio del panel.
3. En la **Terminal** del contenedor, corre `espol-bot panel --google tu@gmail.com <ID de cliente>`.

Desde ese momento, el dominio muestra «Entrar con Google». Al entrar con esa cuenta ves todo el panel, también el
texto de tus chats privados, y el navegador te recuerda 30 días. Con otra cuenta, el panel responde «esa cuenta no
puede entrar». Correr el comando otra vez cierra la sesión en todos los navegadores. `vinci-check remote` no cambia:
usa su propia clave.

## El agente desde tu PC

Un agente de código en tu PC (Claude Code, Codex) puede revisar y arreglar el Vinci del servidor sin que copies nada
de la Terminal de Coolify. Entra por el mismo dominio del panel, con una clave aparte, `AGENT_KEY`. Con ella lee
los logs, los errores, la salud y los turnos, corre comandos en el contenedor y edita archivos de `/opt/data`.

1. En la **Terminal** del contenedor, corre `espol-bot panel --clave-agente`. Imprime la clave una sola vez.
2. Copia la clave.
3. En tu PC, en la carpeta del repo, corre `.venv/bin/vinci-check remote login https://<dominio del panel>`.
4. Pega la clave cuando la pida. No se ve al escribir, y queda en `~/.config/vinci/remote.env`, que solo tu usuario
   lee.
5. Corre `.venv/bin/vinci-check remote status` para probarla.

Pega la clave solo en ese paso, nunca en un chat ni en un archivo del repo. Quien la tenga controla el contenedor: tus
tokens, los de tus amigos y sus chats.

| Comando | Qué hace |
|---|---|
| `vinci-check remote status` | el gateway, WhatsApp, la salud de cada Vinci, los turnos trabados y cuántos errores hubo |
| `vinci-check remote errors` | los errores de las últimas 24 h, agrupados, como en el panel |
| `vinci-check remote logs [nombre] [-n 200] [--grep …] [-f]` | la cola de un log (`gateway`, `errors`, `bot`, `boot`, `remote-access`, `vinci/gateway`…); `boot` son las líneas `[vinci]` de cada arranque; sin nombre, la lista. `all` junta el `gateway.log` de cada perfil, y cada línea dice qué perfil la escribió |
| `vinci-check remote turns [--profile vinci] [-n 30]` | los últimos turnos de un perfil, con las herramientas que usó |
| `vinci-check remote run <comando>` | un comando en el contenedor, como el usuario `hermes`, en `/opt/data` |
| `vinci-check remote doctor` · `restart` | `espol-bot doctor` · `hermes gateway restart` |
| `vinci-check remote get <ruta> [local]` · `put <local> <ruta>` | baja o sube un archivo de `/opt/data` |

Los logs y los turnos ocultan por defecto los números de teléfono (quedan sus 3 últimas cifras), los nombres de tus
amigos (quedan sus iniciales) y el texto de los mensajes (queda su largo). `--raw` lo muestra todo. De un amigo o de
un grupo, `turns` muestra el texto solo con `--raw`.

Cada pedido va firmado con la clave y la hora, así que la clave misma nunca viaja, y un pedido copiado no sirve
dos veces. Sin la firma, `/agente/` responde «no existe», como el resto del panel; la clave del enlace
(`PANEL_KEY`) no abre esta puerta. Cada comando, subida y bajada queda en `/opt/data/logs/remote-access.log` (sin su
salida). La clave vive en `secrets.env`, en el volumen, así que sobrevive a cada **Redeploy**.

Para cortar el acceso, corre `espol-bot panel --quitar-agente` en la Terminal. Para cambiar la clave, corre otra vez
`--clave-agente` y repite los pasos 3 y 4.

## Encenderlo en una PC

`./setup.sh` lo deja encendido como el servicio de usuario `vinci-panel`, que arranca con la sesión. Escucha solo en
`http://127.0.0.1:8787`: desde la misma máquina, ábrelo en el navegador.

Sin systemd (por ejemplo, en Docker), enciéndelo a mano:

```bash
.venv/bin/espol-bot panel                 # --puerto 8787 por defecto
```

## Verlo desde cualquier dispositivo

[Tailscale](https://tailscale.com) arma una red privada entre tus dispositivos, y Tailscale Funnel publica una
página de esa red en internet, con HTTPS, sin abrir puertos del router. El panel distingue dos visitas:

- **Tú, desde tu red de Tailscale** (o desde la misma máquina): ves todo, sin contraseña.
- **Cualquier otra persona**: la página responde «no existe», salvo que traiga el enlace con la clave. Con el enlace
  ve el mismo panel, pero sin el texto de ningún chat ni de los errores.

Para publicarlo:

1. En la máquina de Vinci, corre `tailscale funnel --bg 8787`.
2. Si Tailscale te pide activar HTTPS o Funnel, abre el enlace que muestra, actívalo y repite el paso 1.
3. Corre `.venv/bin/espol-bot panel --nueva-clave`. Imprime el enlace `https://<máquina>.<tu-red>.ts.net/?k=…`.
4. Comparte ese enlace solo con quien quieras.

Pásalo por un chat privado, no en un grupo ni en un lugar público. Quien tenga el enlace ve tu gasto, tus tareas y a
qué hora conversaste con Vinci.

El enlace funciona 30 días en cada navegador, y después hay que abrirlo otra vez. Para cortar el acceso a todos los
que tienen el enlace, corre de nuevo `--nueva-clave`: el enlace anterior deja de servir al instante. La clave queda
en `secrets.env` como `PANEL_KEY`.

Para volver a dejarlo solo en tu red, corre `tailscale serve --bg 8787`. Para quitarlo del todo, corre
`tailscale serve --https=443 off`.

## Apagarlo

```bash
systemctl --user disable --now vinci-panel
```
