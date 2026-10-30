# La Fabrique — guía para responsables de área

Para quien responde por el resultado y no por el código. Explica qué hace el
sistema, qué decides tú y qué no va a hacer por ti. No hace falta usar la línea
de comandos: todo lo de esta guía ocurre en el panel.

Para instalar, consulta [`README.es.md`](README.es.md). Para el diseño técnico,
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## La idea en un párrafo

Fijas un objetivo para un sprint. Un equipo de agentes de IA planifica el
trabajo, lo escribe y te lo entrega con evidencia de lo que realmente hizo: qué
archivos se escribieron, con qué huella de contenido, y si las pruebas corrieron.
El producto no es la generación de código — cualquier herramienta genera código.
El producto es que cada entrega se contrasta con evidencia que el agente que
entrega no puede fabricar, y que el resultado queda registrado para auditarlo
después.

Esa diferencia decide cómo se usa. No se te pide leer código y confiar en él. Se
te pide leer un veredicto.

## Cómo es un sprint

1. **Planificación.** Describes el objetivo y un tamaño de alcance. El
   planificador lo convierte en elementos de backlog con criterios de aceptación.
2. **Despacho.** Los elementos salen como tareas. Cada una la toma un agente con
   un rol: product owner, arquitecto, desarrollador, QA, redactor técnico.
3. **Trabajo.** El agente produce un cambio y se lo pasa al daemon del espacio de
   trabajo, el pequeño programa en tu máquina que escribe archivos en la carpeta
   de tu proyecto.
4. **Verificación.** Cada afirmación de la entrega se compara con lo que el
   daemon observó. El resultado es uno de tres veredictos:
   - **Verificado**: toda afirmación está respaldada por evidencia.
   - **Refutado**: la evidencia contradice una afirmación.
   - **No verificable**: no hay contra qué contrastar la afirmación.
5. **Revisión.** Un agente revisor lee la entrega contra la tarea. Si encuentra un
   problema, la tarea vuelve con el hallazgo concreto.
6. **Decisión.** Según tu configuración, aprueba una persona. Lo que se decide
   queda guardado y firmado en el registro de auditoría.

«No verificable» no es un aprobado blando. Un agente que entrega trabajo que
nadie presenció no demostró su trabajo, y el sistema lo dice en vez de suponerlo.

## Las pantallas

| Pantalla | Qué haces ahí |
|---|---|
| **Evidencia** (la pantalla de entrada) | La lista de ejecuciones de agentes con su veredicto. Empieza aquí. Al abrir una, ves cada comprobación y su observación. |
| **Sprints** | Todos los sprints con su estado. Al abrir uno ves el tablero, la transmisión en vivo y su analítica. |
| **Tablero** | Las tareas por columna, con la insignia de veredicto en cada entrega. Mueves o detienes trabajo. |
| **En vivo** | Lo que hacen los agentes ahora mismo, según ocurre. |
| **Analítica** | Salud del sprint y la tendencia de aprendizaje del propio equipo. |
| **Cuotas** | Presupuesto de tokens por unidad de negocio, y cuánto se gastó. |
| **Miembros** | Quién de tu empresa tiene acceso, y con qué rol. |
| **Procedimientos** | Reglas que el equipo aprendió de sus propias retrospectivas. Propone; tú adoptas o rechazas. |
| **Linaje** | Por qué se tomó una decisión: la cadena de registros detrás. |
| **GitHub** | A qué repositorio está vinculada la empresa. |
| **Mesa de ayuda** | Tickets de soporte. Un agente los clasifica; una persona decide. |

## Qué decides tú

Tres ajustes definen cuánto hace el equipo por su cuenta.

- **Nivel de autonomía** (1 a 3). El nivel 3 permite que el equipo inicie solo un
  sprint de mejora propia cuando un sprint cierra con hallazgos. Por debajo de 3,
  eso ocurre únicamente cuando lo pide una persona.
- **Aprobaciones.** Una persona con rol Manager decide sobre las ejecuciones que
  importan. La decisión lleva tu nombre, una categoría y, si rechazas, un texto
  que el agente lee como corrección.
- **Cuotas.** Un presupuesto de tokens por unidad de negocio. La pasarela lo
  aplica antes de cada llamada al modelo, así que el techo se respeta durante el
  sprint y no después de la factura.

## Roles

| Rol | Qué puede hacer |
|---|---|
| **Owner** | Todo, incluidos los ajustes de la empresa y sus miembros |
| **Manager** | Aprobar entregas, verificar ejecuciones, adoptar procedimientos |
| **Viewer** | Leer el tablero, la evidencia y la analítica |

Los datos están separados por empresa: un miembro de una empresa no ve los
sprints, ejecuciones ni evidencia de otra.

## Qué no hace

Decirlo con claridad es parte del producto.

- **No escanea tu código en busca de problemas de seguridad por su cuenta.** Hay
  un rol SecOps con su instrucción, pero ningún analizador de vulnerabilidades
  corre como parte de un sprint. Usa un analizador.
- **No despliega.** Escribe archivos y ejecuta los comandos que el daemon tiene
  permitidos en la carpeta que abriste. Publicar es tu decisión.
- **No da por buenas las pruebas porque un agente lo diga.** Una afirmación sobre
  pruebas cuenta solo con evidencia independiente, como el resultado de una
  ejecución de CI.
- **No califica el trabajo con un modelo.** Las comprobaciones son comparaciones
  deterministas. Un modelo escribe el trabajo; nunca decide si el trabajo se
  sostiene.
- **No corre sola por defecto.** El nivel 3 sigue escribiendo una fila de
  auditoría por acción, y la pantalla de evidencia sigue mostrando cada veredicto.

## Cómo leer un veredicto

Abre una ejecución y lee las comprobaciones en orden. Cada una tiene un nombre, un
resultado y una frase de observación.

- `artifact_nonempty`: si se entregó algo, aunque sea.
- `claimed_files_present`: si los archivos que el agente nombró aparecen en lo
  que envió.
- `claimed_tests_evidenced`: si hay evidencia independiente que respalde lo que
  afirma sobre las pruebas.
- `files_written`: si el daemon informó haber escrito esos archivos, con la misma
  huella de contenido que envió el backend.
- `tests_run`: qué devolvió realmente el comando de pruebas.
- `risk_tier`: cuánto debería mirarlo una persona, de bajo a alto, con los
  motivos.

Si una comprobación es `no verificable`, la observación dice qué faltó. Casi
siempre es un cable sin conectar, no un fallo del agente.

## Ayuda

Abre un ticket desde la pantalla de la mesa de ayuda. El agente de soporte añade
una primera lectura; un administrador de soporte ve todos los tickets y puede
descargar los registros. Incluye qué estabas haciendo y qué esperabas.
