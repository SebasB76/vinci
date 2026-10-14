# El panel de administración

El panel es una página para ti, el dueño de la instalación: muestra si Vinci está vivo, cuánto gasta y qué hizo en
cada conversación. Solo lee: no usa el modelo, no llama al aula y no cambia nada.

## Qué muestra

| Parte | Qué ves |
|---|---|
| Arriba | Si el gateway de Hermes está vivo y cuántas veces se reinició, si WhatsApp está conectado, los turnos en curso o trabados (más de 5 min), el gasto de hoy y de 7 días, y los errores de las últimas 24 h. |
| Salud de Vinci | Lo mismo que `/estado` y `espol-bot doctor`: el sondeo, la lectura del aula, el mantenimiento y el token de Canvas. |
| Gasto por día | Los últimos 14 días, por grupo: Vinci, bots de materia y amigos. Al pasar el mouse sobre un día (o tocarlo en el celular) ves su total frente al promedio, el gasto por grupo y por bot, las llamadas al modelo, los tokens y el costo por llamada. |
| Gasto por bot | Llamadas al modelo, tokens, costo y el último día de uso de cada perfil y modelo en esos 14 días. |
| Tareas automáticas | Cada tarea de Hermes (sondeo, mantenimiento, resumen…), el día y la hora en que corrió, cuándo corre de nuevo y si falló. |
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
