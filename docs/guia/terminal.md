# Desde la terminal y Claude Code

El comando `aula` consulta lo mismo desde la terminal (añade `--json` para salida de máquina):

```bash
aula cursos
aula tareas                            # pendientes, por fecha de entrega
aula tareas --curso calculo --dias 7
aula anuncios --curso fisica -n 5
aula notas
aula archivos --curso calculo --nombre "semana 3"   # el catálogo: leído o no, con módulo y carpeta
aula archivos bajar 5001               # descarga e indexa el archivo 5001
aula archivos leer 5001 --paginas 2-3
aula enlaces --curso fisica            # lo que está fuera del aula: Dropbox, SharePoint, videos…
aula buscar "regla de la cadena"
aula sincronizar --material            # leer el aula ahora y bajar los sílabos nuevos
aula ocr                               # leer ya con OCR las páginas escaneadas que esperan (--minutos N)
```

`--curso` acepta cualquier parte del nombre o del código, sin tildes. `aula` reutiliza los datos guardados si
tienen menos de 10 minutos; si no, vuelve a leer el aula (y si no puede, te muestra lo guardado). Con
`--actualizar` la lee siempre y falla si no puede; con `--sin-actualizar` usa solo lo guardado.

Para el Académico:

```bash
.venv/bin/espol-bot academico              # qué tiene la copia: fecha, período, tablas de cada sección
.venv/bin/espol-bot academico --conectar   # entra desde la terminal: usuario, contraseña oculta y el CAPTCHA en un archivo
.venv/bin/espol-bot academico --conectar --html /tmp/academico-html   # además guarda el HTML de cada página
```

Con `--html`, el HTML trae tus datos: sirve para revisar cómo Vinci lee las tablas, y después se borra.

**Con Claude Code:** en cualquier sesión de Claude Code en tu PC puedes pedir «bájate el PDF de la semana 3 de
Cálculo y explícame el ejercicio 4»; la skill `aula` le enseña a usar el comando.
