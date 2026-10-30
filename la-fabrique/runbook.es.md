# Runbook de Fortalecimiento para Producción

Este documento describe los pasos para fortalecer el sistema Factory para su despliegue en producción.

## URLs de Servicios

| Servicio | URL | Descripción |
|---|---|---|
| Frontend | `http://localhost:5173` | Dashboard React |
| Backend API | `http://localhost:8000/docs` | FastAPI + Swagger |
| LLM Proxy | `http://localhost:5100` | Gateway de presupuesto de tokens |
| **Jaeger Tracing UI** | **`http://localhost:16686`** | Explorador de trazas distribuidas |
| Neo4j Browser | `http://localhost:7474` | UI del grafo de conocimiento |

---

## Trazabilidad Distribuida (OpenTelemetry + Jaeger)

La Fabrique incluye instrumentación OpenTelemetry en el backend, el proxy LLM y el agente worker.
Las trazas fluyen al contenedor Jaeger all-in-one via OTLP/HTTP en el puerto `4318`.

**Habilitar trazas** (por defecto en Docker Compose):
```
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
```

**Deshabilitar trazas** (para reducir sobrecarga):
```
OTEL_SDK_DISABLED=true
```

---

## 1. Gestión de Secretos

### Estado Actual (Desarrollo)
- Tokens de API almacenados en variables de entorno
- Contraseñas de base de datos en `.env`

### Pasos para Producción

#### Integración con HashiCorp Vault
```python
# Reemplazar acceso a variables de entorno con Vault
import hvac

client = hvac.Client(url='https://vault.example.com', token='...')

# Leer secretos
gemini_api_key = client.secrets.kv.v2.read_secret(
    path='le-fabrique/llm'
)['data']['data']['gemini_api_key']

deepseek_api_key = client.secrets.kv.v2.read_secret(
    path='le-fabrique/llm'
)['data']['data']['deepseek_api_key']
```

#### AWS KMS (Alternativa)
```python
import boto3

kms = boto3.client('kms')
response = kms.decrypt(CiphertextBlob=base64.b64decode(encrypted_token))
token = response['Plaintext'].decode()
```

## 2. Seguridad de Red

### Configuración mTLS para NATS

```yaml
# docker-compose.override.yml
services:
  nats:
    command: "--tlsverify --tlscert=/certs/server.crt --tlskey=/certs/server.key"
    volumes:
      - ./certs:/certs:ro
  
  backend:
    environment:
      NATS_URL: nats://nats:4222
    volumes:
      - ./certs:/certs:ro
```

## 3. Cumplimiento del Presupuesto de Tokens

### Enrutamiento del Proxy LLM
*Nota: Todos los modelos (incluyendo DeepSeek para Devs/QA) DEBEN enrutarse a través del `llm-proxy` local (`http://localhost:5100`) para garantizar que se respeten los presupuestos globales de tokens y que las claves estén centralizadas.*

### Presupuesto de Tokens en el Proxy LLM

```python
# llm-proxy/app.py (agregar seguimiento de presupuesto)
from collections import defaultdict

token_budgets = defaultdict(lambda: {"used": 0, "limit": 2_000_000})

@app.middleware("http")
async def enforce_token_budget(request, call_next):
    agent_id = request.headers.get("X-Agent-ID")
    if agent_id:
        if token_budgets[agent_id]["used"] >= token_budgets[agent_id]["limit"]:
            return JSONResponse(
                status_code=429,
                content={"error": "Token budget exceeded"}
            )
    
    response = await call_next(request)
    
    # Realizar seguimiento del uso
    tokens_used = int(response.headers.get("X-Tokens-Used", 0))
    token_budgets[agent_id]["used"] += tokens_used
    
    return response
```

## 4. Verificación de Commits de Agentes

### Hook de Git para Verificación
```bash
# .git/hooks/pre-receive
#!/bin/bash
while read oldrev newrev refname; do
    commit_msg=$(git log -1 --format=%B $newrev)
    interaction_id=$(echo "$commit_msg" | grep -oP 'interaction_id: \K.*')
    decision_sig=$(echo "$commit_msg" | grep -oP 'decision_signature: \K.*')
    
    if [ -z "$interaction_id" ] || [ -z "$decision_sig" ]; then
        echo "Commit must include interaction_id and decision_signature"
        exit 1
    fi
done
```

## 5. Transacciones Distribuidas (Patrón Outbox)
El sistema utiliza el patrón Transactional Outbox (Bandeja de Salida Transaccional) a través de la tabla `outbox_events` en Postgres para garantizar la entrega de mensajes a NATS, evitando problemas de sincronización entre Postgres y LangGraph.

- **Worker en Segundo Plano**: La tarea `process_outbox` en `backend/app/main.py` sondea esta tabla y despacha eventos de forma segura.
- **Monitoreo**: Asegúrate de monitorear la tabla `outbox_events` en busca de registros atascados en estado `failed` o perpetuamente en `pending`, lo que indica problemas de conectividad con NATS.

## 6. Consideraciones de Escalabilidad

### Escalabilidad Horizontal
- Backend: Desplegar múltiples réplicas con balanceador de carga
- NATS: Usar clúster NATS para alta disponibilidad
- Postgres: Usar réplicas de lectura para escalabilidad de consultas

### Recomendaciones de Recursos
| Servicio | CPU | Memoria | Almacenamiento |
|---------|-----|--------|---------|
| backend | 2 núcleos | 4 GB | - |
| postgres | 4 núcleos | 8 GB | 100 GB |
| neo4j | 4 núcleos | 8 GB | 50 GB |
| nats | 1 núcleo | 512 MB | - |

## 7. Estrategia de Respaldo (Backup)

### Postgres
```bash
# Script de respaldo
pg_dump -h postgres -U factory factory > backup_$(date +%Y%m%d).sql
```

### Neo4j
```bash
# Respaldo usando neo4j-admin
docker exec factory-neo4j neo4j-admin database dump neo4j --to-path=/backup
```

## 8. Arquitectura de Despliegue Híbrido

Fabrique está diseñado para ejecutarse en cualquier lugar. Elige la estrategia que mejor se adapte a tus necesidades de seguridad y escalabilidad:

### 🏠 Estrategia A: On-Premise (Servidores Propios)
Ideal para máxima privacidad de datos y entornos con regulaciones estrictas.
*   **Infraestructura:** Servidores físicos o máquinas virtuales (VMWare/Nutanix).
*   **Orquestación:** Docker Compose para servidores únicos o Kubernetes (OpenShift/Rancher) para clústeres.
*   **Almacenamiento:** Volúmenes persistentes locales.
*   **Acceso IA:** Requiere un proxy de salida configurado en el firewall para alcanzar las APIs de IA.

### ☁️ Estrategia B: Cloud-Native (Nube Pública)
Ideal para alta disponibilidad, alcance global y mantenimiento cero de infraestructura.
*   **Infraestructura:** K8s gestionado (EKS/AKS/GKE).
*   **Base de Datos:** Usa servicios gestionados (AWS RDS, Google Cloud SQL).
*   **Secretos:** Integración nativa con AWS Secrets Manager o Azure Key Vault.
*   **Escalabilidad:** Auto-escalado basado en demanda de tareas y CPU.

### 🌉 Estrategia C: Modelo Híbrido
La lógica y los datos permanecen On-Premise, mientras que el cómputo pesado (LLMs) ocurre en la Nube de forma segura.

---

## 9. Inicio Rápido con Kubernetes
Para desplegar el clúster Enterprise:
```bash
kubectl apply -f deployment/k8s/configmap.yaml
kubectl apply -f deployment/k8s/secrets.yaml
kubectl apply -f deployment/k8s/backend.yaml
---

## 10. Telemetría y Soporte Proactivo (Flujo del Proveedor)

Fabrique incluye un sistema de telemetría de nivel Enterprise que reporta automáticamente los fallos críticos del motor a la proveedora (Carolina Pereira) sin exponer datos sensibles del cliente ni su código fuente.

### El Flujo de Telemetría Segura:
1. **Detección de Errores:** Si ocurre un error crítico en el backend (HTTP 500), el Manejador Global de Excepciones intercepta la caída.
2. **Sanitización de Datos:** El sistema extrae *únicamente* el rastro técnico (stack trace), el endpoint y la versión de Fabrique. **Nunca se transmiten datos del cliente, prompts ni código propietario.**
3. **Webhook del Proveedor:** El reporte sanitizado se envía de forma segura vía HTTPS POST a la `FABRIQUE_VENDOR_SUPPORT_URL`.
4. **Resolución Centralizada:** La infraestructura de la proveedora recibe el reporte, agrupa problemas duplicados y crea automáticamente un ticket de ingeniería en el repositorio central de GitHub.
5. **Entrega de Parches:** La proveedora lanza una actualización del sistema (imagen de Docker) para resolver el problema para todos los clientes a nivel global.

*Nota para Administradores de TI: Esta conexión de salida es de solo lectura desde la perspectiva del cliente y requiere acceso al puerto 443 (HTTPS) hacia el endpoint de telemetría del proveedor.*

## 11. Lista de Verificación de Seguridad

- [ ] Rotar todas las contraseñas predeterminadas
- [ ] Habilitar autenticación NATS
- [ ] Habilitar conexiones SSL en Postgres
- [ ] Habilitar conexiones SSL en Neo4j
- [ ] Configurar reglas de firewall
- [ ] Configurar Vault para secretos
- [ ] Habilitar registro de auditoría (audit logging)
- [ ] Configurar límite de velocidad (rate limiting)
- [ ] Configurar WAF (Web Application Firewall)
- [ ] Actualizaciones de seguridad regulares

## Contacto

Para problemas o preguntas, consulta la documentación del proyecto o contacta al equipo de plataforma.
