# Cobertura del front sobre la API

Relevamiento hecho el 2026-10-18 sobre `main` en `93c24f5`. La especificación se
generó con `app.openapi()` desde el código del backend de ese commit: **57
operaciones**, con las etiquetas Auth, Enterprise, Core, Agents, Agent Runs,
Support, GitHub y Workspace, más `/health`, `/health/deep` y `/metrics` sin
etiqueta. El lado del front se relevó en `frontend/src` (sin tests): llamadas en
`services/api.ts`, hooks en `hooks/useQueries.ts`, y qué pantalla montada en
`App.tsx` usa cada hook.

La tabla está actualizada al final del trabajo de alineación (PR #113): cada
fila que cambió dice con qué pantalla quedó cubierta. El resto del documento
conserva el relevamiento de la fase 1; el [resumen final](#resumen-final) está
al pie.

Estados:
- **cubierto**: hay una pantalla montada que dispara la llamada;
- **cliente sin UI**: existe la función o el hook, pero ninguna pantalla montada lo usa;
- **sin cliente**: el front no lo llama;
- **n/a**: no está pensado para la UI (lo llama GitHub, Prometheus u otro productor).

## Tabla de cobertura

| Método y path | `api.ts` | Hook | Pantalla (ruta) | Estado |
|---|---|---|---|---|
| GET `/health` | `health` | `useQuery` en `App.tsx` | `App.tsx`: indicador "Online" del encabezado | cubierto |
| GET `/health/deep` | `deepHealth` | `useQuery` en `App.tsx`, solo con el panel abierto | `App.tsx`: "Estado de los servicios" al abrir el indicador "Online" | cubierto (nuevo, decisión 3) |
| GET `/metrics` | — | — | — | n/a (Prometheus) |
| POST `/v1/auth/login` | `login` | `useAuthStore.login` | `Login` (`/login`) | cubierto |
| GET `/v1/auth/me` | `me` | `useAuthStore.loadMe` | `ProtectedRoute` (todas las rutas protegidas) | cubierto |
| POST `/v1/auth/register` | `register` | — | `Register` (`/register`) | cubierto |
| POST `/v1/company/invite` | `inviteMember` | `useInviteMember` | `CompanyMembers` (`/company/members`, Owner) | cubierto (nuevo) |
| GET `/v1/agents` | `getAgents` | `useAgents` | `AgentSettings` (`/agents`) | cubierto |
| POST `/v1/agents` | `createAgent` | `useCreateAgent` | `AgentSettings`: "Nuevo agente" | cubierto |
| POST `/v1/agents/generate_prompt` | `generateAgentPrompt` | `useGenerateAgentPrompt` | `AgentSettings`: generar prompt | cubierto |
| PATCH `/v1/agents/{agent_id}` | `updateAgent` | `useUpdateAgentConfig` | `AgentSettings`: guardar tarjeta de agente | cubierto |
| DELETE `/v1/agents/{agent_id}` | `deleteAgent` | `useDeleteAgent` | `AgentSettings`: eliminar agente | cubierto |
| GET `/v1/analytics/orchestration_health` | `getOrchestrationHealth` | `useOrchestrationHealth` | `AnalyticsDashboard` (`/sprints/:id/analytics`) | cubierto |
| GET `/v1/analytics/summary` | `getAnalyticsSummary` | `useAnalyticsSummary` | `AnalyticsDashboard`; resumen del sprint (`/sprints/:id`) | cubierto |
| POST `/v1/approve_task` | — | — | — | sin cliente; **el backend lo devuelve como 410 Gone** (ver punto 4 abajo) |
| GET `/v1/capabilities` | `capabilities` | `useCapabilities` | `App.tsx`: muestra u oculta Generar y Memoria | cubierto |
| POST `/v1/discover_team` | `discoverTeam` | `useDiscoverTeam` | `CompanyNew` (`/companies/new`) | cubierto |
| GET `/v1/enterprise/lineage` | `getLineage` | `useLineage` | `Lineage` (`/lineage?file=`), enlazado desde los archivos declarados en `TaskDetails` cuando hay Neo4j | cubierto (nuevo) |
| GET `/v1/enterprise/quota_usage_history` | `getQuotaUsageHistory` | `useQuotaUsageHistory` | `QuotaPanel` (`/company/quotas`) | cubierto |
| GET `/v1/enterprise/quotas` | `getQuotas` | `useQuotas` | `QuotaPanel`; `GlassRoom`; resumen del sprint | cubierto |
| POST `/v1/enterprise/quotas/{bu_id}/reset` | `resetQuota` | `useResetQuota` | `QuotaPanel`: botón reiniciar por unidad | cubierto |
| POST `/v1/init_company` | `initCompany` | `useInitCompany` | `CompanyNew`; resumen del sprint (arranque rápido) | cubierto |
| GET `/v1/models` | (inline `api.get`) | `useModels` | `CompanyNew`, `AgentSettings` | cubierto |
| PATCH `/v1/backlog/{item_id}` | `updateBacklogItem` | `useUpdateBacklogItem` | `KanbanBoard` (`/sprints/:id/board`): selector de estado | cubierto |
| POST `/v1/plan_self_improvement_sprint` | `planSelfImprovementSprint` | `usePlanSelfImprovementSprint` | resumen del sprint (`Dashboard.tsx` montado como pestaña Resumen) | cubierto |
| POST `/v1/plan_sprint` | `planSprint` | `usePlanSprint` | resumen del sprint | cubierto |
| GET `/v1/sprints` | `listSprints` | `useSprints` | `Sprints` (`/sprints`) | cubierto |
| GET `/v1/sprints/{sprint_id}/board` | `getSprintBoard` | `useSprintBoard` | `SprintWorkspace` y sus pestañas, `TaskDetails` | cubierto |
| POST `/v1/sprints/{sprint_id}/dispatch` | `dispatchSprint` | `useDispatchSprint` | `SprintWorkspace`, pestaña Tablero: "Despachar pendientes" | cubierto (nuevo) |
| POST `/v1/sprints/{sprint_id}/pause` | `pauseSprint` | `usePauseSprint` | `SprintWorkspace`, pestaña Tablero: "Pausar" | cubierto |
| POST `/v1/sprints/{sprint_id}/resume` | `resumeSprint` | `useResumeSprint` | `SprintWorkspace`, pestaña Tablero: "Reanudar" | cubierto |
| POST `/v1/start_sprint` | `startSprint` (sin uso) + inline en el hook | `useStartSprint` | resumen del sprint | cubierto |
| POST `/v1/audit` | — | — | — | n/a (escritura de auditoría interna) |
| GET `/v1/audit/verify` | `getAuditVerification` | `useAuditVerification` | `EvidenceDetail` (`/evidence/:runId`) | cubierto |
| POST `/v1/generate` | `generate` | `useGenerate` | `Generate` (`/generate`, solo con `agent_graph`) | cubierto |
| GET `/v1/glassroom/stream` | (EventSource en `store/agentStore.ts`) | — | `GlassRoom` (`/sprints/:id/live`) | cubierto |
| GET `/v1/memory/search` | `searchMemory` | `useSearchMemory` | `MemorySearch` (`/memory`) | cubierto (ahora con los parámetros de la API) |
| POST `/v1/memory/store` | `storeMemory` | `useStoreMemory` | `MemorySearch`: "Agregar a la memoria" | cubierto (nuevo) |
| POST `/v1/agent_runs` | — | — | — | n/a (lo usan productores externos para registrar corridas) |
| GET `/v1/agent_runs` | `getAgentRuns` | `useAgentRuns` | `Evidence` (`/evidence`), `GovernancePanel` (`/governance`), insignias del `KanbanBoard`, `TaskDetails` | cubierto |
| GET `/v1/agent_runs/{run_id}` | `getAgentRun` | `useAgentRun` | `EvidenceDetail` | cubierto |
| GET `/v1/agent_runs/{run_id}/approvals` | `getAgentRunApprovals` | `useAgentRunApprovals` | `EvidenceDetail` | cubierto |
| POST `/v1/agent_runs/{run_id}/approve` | `approveAgentRun` | `useApproveAgentRun` | `EvidenceDetail`: aprobar/rechazar | cubierto |
| GET `/v1/agent_runs/{run_id}/verifications` | `getAgentRunVerifications` | `useAgentRunVerifications` | `EvidenceDetail` | cubierto |
| POST `/v1/agent_runs/{run_id}/verify` | `verifyAgentRun` | `useVerifyAgentRun` | `EvidenceDetail`: botón Verificar | cubierto |
| POST `/v1/integrations/github/webhook` | — | — | — | n/a (lo llama GitHub) |
| POST `/v1/integrations/github/bindings` | `createGitHubBinding` | `useCreateGitHubBinding` | `GitHubIntegration` (`/company/github`, Manager) | cubierto (nuevo) |
| POST `/v1/integrations/github/backfill` | `backfillGitHub` | `useBackfillGitHub` | `GitHubIntegration`: "Importar pull requests anteriores" | cubierto (nuevo) |
| POST `/v1/support/chat` | `supportChat` | — | `SupportBot` (botón flotante, todas las rutas) | cubierto (el cuerpo se corrigió: antes daba 422) |
| GET `/v1/support/logs` | `downloadSupportLogs` | — | `HelpDesk` (`/support`): "Descargar logs" | cubierto (nuevo) |
| POST `/v1/support/report_bug` | `reportBug` | — | `SupportBot`: reportar error | cubierto |
| GET `/v1/support/tickets` | `listTickets` | `useTickets` | `SupportBot` (por email); `HelpDesk` (filtros de estado, impacto y email) | cubierto |
| GET `/v1/support/tickets/{ticket_num}` | `getTicket` | `useTicket` | `SupportBot`; `HelpDesk`: detalle | cubierto |
| PATCH `/v1/support/tickets/{ticket_num}` | `updateTicket` | `useUpdateTicket` | `HelpDesk`: estado, asignación y resolución | cubierto (nuevo) |
| GET `/v1/workspace/status` | `workspaceStatus` | `useWorkspaceStatus` | `CompanyNew`: estado del daemon | cubierto |
| GET `/v1/workspace/browse` | `browseWorkspace` | — | `FolderPicker` dentro de `CompanyNew` | cubierto (hallazgo A resuelto en #112) |
| GET `/v1/workspace/inspect` | `inspectWorkspace` | — | `CompanyNew`: tarjeta del proyecto | cubierto |

Totales al cierre: **52 cubiertos**, 1 sin cliente (`approve_task`, retirado)
y 4 n/a. En la fase 1 eran 43 cubiertos y 10 sin
cliente. Ningún endpoint queda como "cliente sin UI".

## Llamadas del front a paths que el backend no tiene

Las tres quedaron resueltas: `browse_fs` se revirtió en #112, y los clientes de
soporte se corrigieron y se usan desde `SupportBot` (commit de limpieza de este
PR). Tabla de la fase 1:

| Llamada | Dónde | Efecto |
|---|---|---|
| GET `/v1/browse_fs` | `CompanyNew.tsx` (3 lugares, con `http://localhost:8000` fijo) | **404 en `main`**: el endpoint se eliminó en #111 (hallazgo A) |
| GET `/v1/tickets` | `api.getTickets` → `useTickets` | latente: ninguna pantalla usa el hook |
| POST `/v1/report_bug` | `api.reportBug` → `useReportBug` | latente: ninguna pantalla usa el hook |

## Verificación de los puntos de la fase 1

**Punto 2. Endpoints que el prompt da como "sin referencia".** Se confirman sin
cliente: `company/invite`, `approve_task`, `enterprise/lineage`,
`sprints/{id}/dispatch`, `memory/store`, `support/logs`, `github/bindings`,
`github/backfill` y `health/deep`. Falso positivo: `POST /v1/support/chat` está
cubierto, porque `SupportBot.tsx` lo llama directamente con `api.post`.

**Punto 3. `/v1/tickets` y `/v1/report_bug`.** No hay ningún prefijo que los
resuelva: `API_BASE` es solo el host. Son bugs, pero latentes, porque `useTickets`
y `useReportBug` no se usan en ninguna pantalla; `SupportBot` ya llama a los paths
correctos `/v1/support/...`. Propuesta: corregir los dos paths en `api.ts` y hacer
que `SupportBot` use esos clientes, o borrar los clientes y hooks sin uso.

**Punto 4. Controles para las mutaciones que sí están en el cliente.**

| Endpoint | Control | Pantalla |
|---|---|---|
| pause / resume | botones Pausar y Reanudar, solo en la pestaña Tablero | `/sprints/:id/board` |
| approve (corrida) | Aprobar/Rechazar con categoría y comentario | `/evidence/:runId` |
| verify | botón Verificar | `/evidence/:runId` |
| reset de cuotas | botón por unidad de negocio | `/company/quotas` |
| `workspace/*` | estado del daemon, selector de carpetas, tarjeta del proyecto | `/companies/new` |
| PATCH / DELETE agents | guardar y eliminar en cada tarjeta | `/agents` |

## Estado del relevamiento del 2026-10-17

`docs/audits/front-2026-10-17.md` **no está en el repo**. Su contenido se cargó
como los issues #83, #84 y #85, y los tres se cerraron el 2026-10-17 con los PRs
#87, #88 y #89. Después, #100 reorganizó la navegación (`/sprints`, una página
por sprint con pestañas, redirecciones de las rutas viejas). Cada punto,
comparado con el código actual:

| Punto del prompt | Estado en `main` | Evidencia |
|---|---|---|
| F2: no persistir `activeSprintId` antes de un 200 del board; limpiarlo ante 404 | resuelto (#87) | `useSprintBoard` limpia el id ante 403/404; `SprintWorkspace.test.tsx` cubre "waits for URL sprint validation before persisting" |
| F2: `/workspace/999` muestra "sprint-999" y conecta el stream | resuelto (#87, #100) | `/workspace/:id` redirige a `/sprints/:id/live`, que valida el id antes de conectar |
| F2: no reintentar 4xx; query del board compartida | resuelto | `lib/queryClient.ts`: `retry: !isClientError && count < 1`; el board usa una sola clave, `QUERY_KEYS.sprintBoard`, y deja de consultar periódicamente tras un 4xx |
| F2: `TaskDetails` distingue tarea, sprint y red | resuelto (#87, #100) | `TaskDetails.test.tsx`: "distinguishes a missing sprint from a missing task", reintento ante fallo de carga |
| F2: `EvidenceDetail` con id inválido | resuelto (#87) | distingue id mal formado, 404 y fallo de carga (`EvidenceDetail.test.tsx`) |
| F2: reintentar y enlace en todo error | resuelto en esas pantallas | `ErrorState` con Retry y enlace |
| F3: Dashboard con 5 `t()`, Home con 1, CompanyNew con 0 | resuelto (#89) | hoy hay 66 `t()` en `Dashboard.tsx` y 134 en `CompanyNew.tsx`; `Home.tsx` ya no existe (`/` redirige a `/evidence`) |
| F3: el selector de idioma muestra "EN" con la UI en español | resuelto (#89) | muestra el idioma activo (test `LanguageSwitcher` en `App.test.tsx`) |
| F3: `eslint-plugin-i18next` | **pendiente** | el front no tiene ESLint configurado (ni dependencia ni config); el workflow corre `npx eslint src \|\| true`. Mientras tanto, `src/i18n/coverage.test.ts` falla si una clave literal falta en en/es |
| F4: overflow del encabezado a ~1270px | resuelto (#88, #100) | navegación corta + menú de empresa. Re-verificado ahora con Playwright sobre el build de `main`: sin overflow a 1024, 1269, 1366 y 1440 px, en inglés y en español, con los 5 ítems visibles |
| F4: `/login` y `/register` con sesión | resuelto (#88) | redirigen (`Login.test.tsx`) |
| F4: cambiar de empresa | resuelto (#88, #100) | "Cambiar de empresa" en el menú de empresa, con 2+ membresías. La redirección de `/companies/select` con una sola membresía es intencional (#61) y ahora está documentada en `ProtectedRoute.tsx` |
| F4: flags v7 de React Router | resuelto (#88) | `App.tsx:371` |
| F4: `/v1/auth/me` dos veces | era `StrictMode` en desarrollo (anotado en #85) | medido con Playwright sobre `vite build` + `vite preview`: 1 llamada por carga completa de `/evidence`, `/sprints` y `/governance`, y 0 al navegar dentro de la app |
| F4: el botón del SupportBot tapa contenido | resuelto (#88) | espacio inferior reservado en los contenedores con scroll |

Las cifras del prompt (CompanyNew de 2040 líneas, 547 claves, Home.tsx) son del
código anterior a esos PRs. Hoy CompanyNew tiene 1310 líneas y Home no existe.

## Hallazgos nuevos

**A. `main` está en rojo desde `93c24f5`.** Ese commit ("restore navigable
directory picker after upstream merge") volvió a poner el desplegable viejo de
`/v1/browse_fs` en `CompanyNew.tsx`:
- ese endpoint ya no existe en el backend (se quitó en #111 porque el backend,
  dentro de Docker, no ve el disco del usuario), así que "Examinar" recibe un 404;
- usa claves de i18n que #111 había quitado (`companyNew.directoryError`,
  `companyNew.unknownError`, `companyNew.close`) y textos fijos ("⬆ Subir",
  "Entrar") y `http://localhost:8000` fijo;
- reemplazó el diálogo nativo de Electron.

Fallan 5 tests (4 de `CompanyNew.test.tsx` y la cobertura de i18n), y con ellos
los workflows Frontend Build y Frontend Tests en `main`. Sospecho que el selector
nuevo mostró "daemon no conectado" porque el daemon no estaba corriendo, y que el
backend que estaba en ejecución todavía tenía `browse_fs` cargado en memoria.
**Necesita decisión**: ver pregunta 1.

**B. Código muerto.** `components/ControlPanel.tsx` y `pages/SprintBoard.tsx` no
se montan en ninguna ruta. `useSearchMemory`, `useTickets`, `useReportBug` y
`api.startSprint` no se usan.

**C. `approve_task` está retirado.** `POST /v1/approve_task` devuelve 410 a
propósito: la aprobación humana pasó a la evidencia, con
`POST /v1/agent_runs/{id}/approve` y la regla de POSITIONING de que se aprueba
una corrida verificada, no una tarea. El "aprobar/rechazar tarea desde el board"
de la fase 5 no puede usar ese endpoint. Propuesta: en el board, un enlace
"Revisar evidencia" a `/evidence/:runId` desde la insignia de veredicto que ya
existe, o aprobar la última corrida de la tarea desde el board con el endpoint de
corridas.

## Brechas priorizadas

| # | Brecha | Alcance | Propuesta | Estado |
|---|---|---|---|---|
| 1 | `main` en rojo por `browse_fs` (hallazgo A) | chico | decisión pendiente (pregunta 1) | resuelto: se restauró el selector del daemon (#112) |
| 2 | `POST /v1/sprints/{id}/dispatch` sin control | chico | botón "Despachar tareas pendientes" junto a Pausar/Reanudar en la pestaña Tablero (fase 5) | hecho |
| 3 | `POST /v1/memory/store` sin control | chico | "Guardar en memoria" en `MemorySearch` (fase 5) | hecho |
| 4 | Clientes de soporte con paths inexistentes | chico | corregir y usarlos desde `SupportBot`, o borrarlos (fase 5) | hecho, y el chat dejó de dar 422 |
| 5 | Código muerto (hallazgo B) | chico | borrar `ControlPanel`, `SprintBoard` y los hooks sin uso | hecho (también `SprintCalendar`) |
| 6 | Aprobar desde el board | chico | con el endpoint de corridas, no con `approve_task` (hallazgo C) | elegiste el enlace: la insignia de veredicto ya lleva a `/evidence/:runId` |
| 7 | `eslint-plugin-i18next` | medio | requiere introducir ESLint en el front: no hay configuración | hecho; `npm run lint` bloquea en CI |
| 8 | `POST /v1/company/invite` sin UI | medio-grande | invitaciones desde el menú de empresa (Owner) | hecho: `/company/members` |
| 9 | Integraciones GitHub (`bindings`, `backfill`) sin UI | grande | página de integraciones por empresa | hecho: `/company/github` |
| 10 | `GET /v1/enterprise/lineage` sin UI | medio | linaje por archivo desde `EvidenceDetail` o la tarea | hecho: `/lineage`, enlazado desde la tarea |
| 11 | `GET /v1/support/logs` y `PATCH /v1/support/tickets/{n}` sin UI | medio | vista de mesa de ayuda para administradores | hecho: `/support` |
| 12 | `GET /health/deep` sin UI | chico | detalle por servicio al pasar el mouse sobre el indicador "Online" | hecho: panel al abrir el indicador (decisión 3) |

## Resumen final

### Qué quedó cubierto

Commits de este PR (#113), uno por fase o tema:

| Commit | Qué cubre |
|---|---|
| limpieza | chat de soporte con el cuerpo `{messages}` (antes 422); clientes de soporte tipados; borrado de `ControlPanel`, `SprintBoard` y los hooks muertos |
| fase 3 | ESLint con `eslint-plugin-i18next` en CI; 72 textos fijos pasados a claves |
| fase 4 | `/companies/select` documentado; `/v1/auth/me` medido en producción (1 llamada por carga) |
| fase 5 | despachar pendientes; guardar en memoria; búsqueda de memoria con los parámetros reales |
| arreglo | `AgentSettings` sin temporizadores vivos al desmontarse (fallaba en CI) |
| brechas grandes | las cuatro páginas que elegiste, en un commit porque comparten `api.ts`, los hooks, el menú y las traducciones: |
| · invitaciones | `/company/members`: el Owner invita por email con rol; 404 explica que la persona tiene que registrarse antes |
| · GitHub | `/company/github` (Manager): conectar un repositorio con un secreto generado en el navegador, instrucciones del webhook con la URL y el secreto (se muestra una sola vez), e importación de pull requests anteriores con el resultado por PR |
| · linaje | `/lineage?file=`: decisiones registradas sobre un archivo; aviso cuando no hay Neo4j; los archivos declarados de una tarea enlazan ahí si hay Neo4j |
| · mesa de ayuda | `/support` (administradores de soporte, ver decisión 1): tickets con filtros, detalle, cambio de estado con resolución obligatoria para resolver o cerrar, y descarga de logs |
| cuotas | el selector de días del historial de uso ahora vuelve a pedir el historial (antes pedía siempre 7) |

El menú de empresa muestra Miembros solo al Owner, GitHub al Manager o al Owner,
y Mesa de ayuda a los administradores de soporte. Todo está en `en.json` y `es.json`. Hay tests de cada página
nueva y del menú por rol.

Verificado contra el backend real (Postgres, NATS con JetStream, auth activada,
sin Neo4j) con Playwright sobre el build de producción. Pasaron 21 de 21
chequeos:
- el menú por rol;
- invitar a alguien sin cuenta (404) y a alguien con cuenta, confirmando la membresía en `/v1/auth/me`;
- conectar un repositorio y el 409 al repetirlo;
- importar desde un repositorio sin conectar (404);
- listar y filtrar tickets, y resolver uno, confirmando en la API que quedó `resolved` con su resolución y `resolved_at`;
- logs con 404 y luego la descarga con contenido;
- linaje sin Neo4j, con error y Reintentar;
- la mesa de ayuda en español;
- un Viewer no ve las páginas de administración;
- ningún error de consola inesperado.

### Decisiones tomadas

La dueña delegó estas decisiones. Lo que se decidió y cómo quedó:

1. **Administrador de la mesa de ayuda: un rol de plataforma por
   configuración.** `SUPPORT_ADMIN_EMAILS` (emails separados por coma) define
   quién ve y cambia todos los tickets y descarga los logs. El backend lo
   aplica, y `/v1/auth/me` lo informa como `support_admin`. El resto de los
   usuarios ve solo los tickets reportados con el email de su cuenta: pedir los
   de otro da 403 y el detalle de un ticket ajeno da 404. La página y la
   entrada del menú dependen de ese rol, no del rol en la empresa, porque los
   tickets no pertenecen a ninguna empresa. Con `AUTH_REQUIRED=false` y sin
   token, la mesa sigue abierta, como el resto de una demo local.
   Elegí configuración y no una columna en la base porque no requiere
   migración y alcanza para pocos administradores. Si hace falta gestionarlos
   desde la UI, el siguiente paso es un flag en `users`.
2. **URL del webhook: `PUBLIC_API_URL`.** `/v1/capabilities` la informa como
   `public_api_url`, y la página de GitHub la usa como Payload URL. Sin ella, la
   página usa la URL del navegador y explica cómo configurarla.
3. **`/health/deep`: sí, a demanda.** Al hacer clic en el indicador "Online" se
   abre "Estado de los servicios", con cada servicio y el motivo si está caído.
   La consulta corre solo con el panel abierto, porque las sondas tardan hasta 3
   segundos cuando un servicio no responde.
4. **`VITE_DEFAULT_PROJECT_PATH`: eliminada** de `docker-compose.yml`. Además,
   `docker-compose.yml` no pasaba al backend variables que `.env.example`
   documenta (`FERNET_SECRET_KEY`, `AUDIT_SIGNING_KEY`, `GITHUB_TOKEN`). Ahora
   las pasa, junto con las dos nuevas; vacías se tratan como no configuradas.

### Cambios de API

Hechos junto con las decisiones:
- Invitar a alguien que ya es miembro devuelve **409** con su rol actual, en
  lugar de 500.
- `Access-Control-Expose-Headers: Content-Disposition`, para que el navegador
  lea el nombre del archivo de logs.

Siguen propuestos:
- **Gestión de miembros:** `GET /v1/company/{id}/members` para listarlos, y
  `PATCH`/`DELETE` para cambiar o quitar un rol, sin dejar a la empresa sin
  Owner. Hoy no hay forma de ver quién está en la empresa ni de cambiar un rol.
- **Las respuestas 500 no llevan cabeceras CORS.** El manejador global de
  excepciones responde fuera de `CORSMiddleware`, así que el navegador ve un
  error de red en lugar del 500 y su detalle. Propuesta: capturar las
  excepciones dentro de CORS.
- **Bindings de GitHub:** `GET /v1/integrations/github/bindings?company_id=` para
  listarlos, `DELETE` para desconectar uno y un endpoint para rotar el secreto.
- **Linaje:** responder 503 cuando Neo4j no está conectado, como la memoria, en
  lugar de 500.
- **Memoria:** recibir `content` en el cuerpo de `POST /v1/memory/store`. Hoy va
  en la query, y el front lo limita a 2000 caracteres.
- **Membresías con el nombre de la empresa** en `/v1/auth/me`. El menú muestra
  "Empresa N" cuando no tiene el nombre guardado localmente.
- **Un endpoint de una sola tarea** (`GET /v1/backlog/{item_id}`), para que
  `/task/:taskId` no tenga que resolver la tarea a través del board del sprint
  activo.
- **`/health/deep` es público y devuelve el texto de las excepciones** (por
  ejemplo, direcciones internas). Conviene recortar el motivo, o exigir sesión
  para el detalle.
