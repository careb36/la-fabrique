# 🚀 Plan Maestro: La Fabrique Enterprise v2.0

Este documento contiene la estrategia de refactorización y mejora para el ecosistema de La Fabrique. 
Sigue las fases en orden para garantizar la estabilidad del sistema.

---

## 🏛️ Fase 1: Cimientos de Acero (Backend Refactor) — ✅ COMPLETADO
**Objetivo:** Salir del `main.py` gigante y pasar a una arquitectura modular y tipada.

1.  **Migración a SQLModel:** ✅ Reemplazado `psycopg2` por **SQLModel**.
    *   Modelos creados para: `Company`, `Agent`, `Sprint`, `BacklogItem`, `AuditLog`, `BusinessUnit`.
2.  **Modularización por Routers:** ✅ `main.py` dividido en `backend/app/routers/`:
    *   `auth.py`, `enterprise.py`, `sprint.py`, `agents.py`, `support.py`.
3.  **Capa de Servicios:** ✅ Lógica de negocio movida a `backend/app/services/`:
    *   `outbox_service.py`, `agent_service.py`, `discovery_service.py`, `task_worker.py`.

---

## 🧠 Fase 2: Inteligencia Auto-Sanable (LangGraph Evolution) — ✅ COMPLETADO
**Objetivo:** Agentes con bucles de retroalimentación y memoria persistente.

1.  **Bucle de Feedback (Self-Correction):** ✅ `real_execution_node` ahora realiza validación sintáctica (compile) y reintenta con feedback específico.
2.  **Validación de Salida (Guardrails):** ✅ `validate_design_node` asegura diagramas Mermaid no vacíos y bien formateados.
3.  **RAG sobre Grafos (Neo4j):** ✅ `EngramProcessor` integra búsqueda semántica (pgvector) con búsqueda estructural (Neo4j) para un contexto RAG superior.

---

## 🎨 Fase 3: Frontend de Alta Performance (React Upgrade) — ✅ COMPLETADO
**Objetivo:** UI reactiva, liviana y con mejor manejo de estado.

1.  **Zustand Store:** ✅ Migración completa a Zustand (`useAppStore.ts` y `agentStore.ts`).
2.  **TanStack Query (React Query):** ✅ Implementados hooks personalizados en `useQueries.ts` para todas las operaciones de API.
3.  **Refactor de Componentes:** ✅ `CompanyNew`, `ControlPanel`, `KanbanBoard`, `Generate`, `GovernancePanel` y `AnalyticsDashboard` refactorizados para usar hooks de Query/Mutation.

---

## 🛡️ Fase 4: Governance y Observabilidad — 🚧 PRÓXIMAMENTE
**Objetivo:** Control de costos y trazabilidad total.

1.  **Cuotas en Tiempo Real:** 
    *   Validar `token_quota` en cada llamada al LLM Proxy. Frenar la ejecución si se supera el límite de la Business Unit.
2.  **OpenTelemetry Tracing:** 
    *   Instrumentar los nodos de LangGraph para ver la latencia y fallos en Jaeger/SigNoz.
3.  **Human-in-the-Loop:** 
    *   Mejorar el endpoint `/approve_task` para permitir feedback textual del PO humano que el Agente deba procesar.

---

## 🏗️ Estándares de Ingeniería y Git Strategy
**Objetivo:** Mantener el orden y la disciplina del repositorio.

1.  **Git Flow Disciplinado:**
    *   No trabajar directamente sobre `main` ni `develop`.
    *   Cada cambio debe ir en su propia rama `feature/` o `bugfix/`.
2.  **Conventional Commits:**
    *   Usar prefijos: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
3.  **Código Tipado:**
    *   Usar `typing` de Python en todo el backend.
    *   Usar interfaces y tipos estrictos en el frontend (TypeScript).
4.  **Cero Acoplamiento:**
    *   No mezclar lógica de base de datos con controladores de FastAPI.
    *   Inyectar dependencias siempre que sea posible.

## 🛠️ Instrucciones para Copilot / AI Assistant
- **Principio de Atomicidad:** No intentes aplicar todo el plan de una vez. Trabaja fase por fase.
- **Git Flow:** Al iniciar una tarea, pregunta por el nombre de la rama siguiendo la convención.
- **Commits:** Sugiere commits siguiendo la convención de Conventional Commits.
- **Documentación:** Lee el archivo `CONTRIBUTING.md` para más detalles sobre las convenciones.
- **Seguridad:** No modifiques las variables de entorno ni las claves de acceso.
- **Convenciones:** Mantén el estilo de código existente (FastAPI + Pydantic v2).
