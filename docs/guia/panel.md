# El panel de administración

El panel es una página para ti, el dueño de la instalación: muestra si Vinci está vivo, cuánto gasta y qué hizo en
cada conversación. Solo lee: no usa el modelo, no llama al aula y no cambia nada.

## Qué muestra

| Parte | Qué ves |
|---|---|
| Arriba | Si el gateway de Hermes está vivo y cuántas veces se reinició, si WhatsApp está conectado, los turnos en curso o trabados (más de 5 min), el gasto de hoy y de 7 días, y los errores de las últimas 24 h. |
| Salud de Vinci | Lo mismo que `/estado` y `espol-bot doctor`: el sondeo, la lectura del aula, el mantenimiento y el token de Canvas. |
| Gasto por día | Los últimos 14 días, por grupo: Vinci, bots de materia y amigos. Al pasar el mouse sobre un día (o tocarlo en el celular) ves su total frente al promedio, el gasto por grupo y por bot, las llamadas al modelo, los tokens y el costo por llamada. |
| Gasto por bot | Llamadas al modelo, tokens y costo de cada perfil y modelo en esos 14 días. |
| Tareas automáticas | Cada tarea de Hermes (sondeo, mantenimiento, resumen…), cuándo corrió y si falló. |
| Conversaciones recientes | Cada chat con sus mensajes, herramientas, tokens, costo y cuánto tardó la última respuesta. Al tocar una fila ves sus pasos con el tiempo entre cada uno: ahí ves dónde se trabó. |
| Errores y avisos | Las líneas de `errors.log` de Hermes, agrupadas por tipo, con cuántas veces salieron. |

El texto de un chat solo se ve en tus chats privados. De un amigo o de un grupo, el panel muestra solo los tiempos,
las herramientas y el largo de cada mensaje.

Los costos son los que estima Hermes con su tabla de precios, no la factura de tu proveedor.

## Encenderlo

`./setup.sh` lo deja encendido como el servicio de usuario `vinci-panel`, que arranca con la sesión. Escucha solo en
`http://127.0.0.1:8787`: desde la misma máquina, ábrelo en el navegador.

Sin systemd (por ejemplo, en Docker), enciéndelo a mano:

```bash
.venv/bin/espol-bot panel                 # --puerto 8787 por defecto
```

## Verlo desde tu PC o tu celular, en privado

[Tailscale](https://tailscale.com) arma una red privada entre tus dispositivos. Con Tailscale Serve, el panel se ve
solo dentro de esa red, con HTTPS y sin abrir puertos a internet.

1. En la máquina de Vinci, corre `tailscale serve --bg 8787`.
2. Si Tailscale te pide activar HTTPS, abre el enlace que muestra, actívalo y repite el paso 1.
3. Corre `tailscale serve status` y copia la dirección `https://<máquina>.<tu-red>.ts.net`.
4. En tu celular, instala la app de Tailscale y entra con la misma cuenta.
5. Abre esa dirección en el navegador de cualquier dispositivo de tu red.

No uses `tailscale funnel`: Funnel publica la página en internet, y el panel no tiene contraseña. Tailscale Serve
recuerda la configuración tras un reinicio. Para quitarla, corre `tailscale serve --https=443 off`.

## Apagarlo

```bash
systemctl --user disable --now vinci-panel
```
