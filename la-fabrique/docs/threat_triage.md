# Triaje del modelo de amenazas (OWASP pytm)

Fuente: `docs/threat_model.json` (113 amenazas STRIDE). Este documento
clasifica las amenazas **aplicables** al despliegue real de La Fabrique y
registra la mitigación existente o el residual aceptado. Las amenazas
genéricas de pytm (buffer overflow en C, LDAP, SOAP, SSI, PHP) se descartan
cuando el componente no existe en la arquitectura.

## Resumen

| Clasificación | Cantidad aproximada | Acción |
|---|---|---|
| Aplicable y mitigada | 18 | Control en código o configuración |
| Parcial | 22 | Residual documentado; revisar al desplegar |
| No aplicable | 73 | Descartar por tecnología o alcance |

## Inyección y ejecución (INP*, AC06, LLM05, LLM06)

| Amenaza | Estado | Mitigación / residual |
|---|---|---|
| INP07, INP13, INP26, INP31 | Mitigado | La API usa SQLModel/SQLAlchemy con parámetros; no construye SQL ni comandos con entrada del usuario. |
| INP11, HA01 | Parcial | El daemon escribe en el workspace del proyecto; el backend no acepta rutas absolutas arbitrarias del usuario. El daemon corre en el host y debe operar con un usuario sin privilegios. |
| AC06, INP23 | Parcial | Los agentes generan archivos; el daemon los escribe y, si `DELIVERY_TESTS_ENABLED=true`, ejecuta tests. Por defecto está apagado. El workspace no es un sandbox: el residual se acepta para el despliegue single-host y se revisa antes de exponer el daemon. |
| LLM05 | Mitigado | El agente no recibe herramientas de shell libres; las acciones pasan por el daemon y por el contrato de `workspace.generate`. |
| LLM06 | Parcial | La ejecución de código generado existe solo si se habilita `DELIVERY_TESTS_ENABLED`; el comando se limita a tests del proyecto y tiene timeout. No hay sandbox de contenedor en v1. |

## Autenticación, sesión y CSRF (AA*, AC*, CR*)

| Amenaza | Estado | Mitigación / residual |
|---|---|---|
| AA03, AA04, AC17, AC18 | Mitigado | JWT HS256 firmado con `JWT_SECRET_KEY`, expiración de 60 minutos (`ACCESS_TOKEN_EXPIRE_MINUTES`) y resolución del usuario en cada request. |
| AC21 | Mitigado | La API usa bearer token en cabecera `Authorization`; no hay cookies de sesión para el backend. |
| CR03 | Mitigado | Contraseñas con bcrypt (`passlib`), rate limiting global y por endpoint con `slowapi`. |
| CR01, CR02, CR06 | Parcial | En producción el TLS lo termina un proxy externo; el compose de desarrollo habla HTTP. No se publica el backend directamente. |
| AC24 | Mitigado | Las claves se leen del entorno; no hay credenciales hardcodeadas en el código. `FERNET_SECRET_KEY` y `JWT_SECRET_KEY` son obligatorias en producción. |

## XSS y cliente (SC*, INP38–INP40)

| Amenaza | Estado | Mitigación / residual |
|---|---|---|
| SC02, SC03, SC04, INP38–INP40 | Parcial | El frontend es React y escapa por defecto; no usa `dangerouslySetInnerHTML` para contenido de agentes. Cualquier renderizado HTML nuevo debe pasar por revisión y sanitización. |
| SC01 | Mitigado | La API responde JSON con `Content-Type: application/json`; no hay JSONP. |
| SC05 | Mitigado | Las comprobaciones de autorización se hacen en el backend, no solo en el cliente. |

## Datos y privacidad (DS*, DE*, CR*)

| Amenaza | Estado | Mitigación / residual |
|---|---|---|
| DS06 | Parcial | PostgreSQL y Neo4j no cifran en reposo por defecto en el compose. El host y los volúmenes deben cifrarse a nivel de disco; las credenciales de proyecto se cifran con Fernet si `FERNET_SECRET_KEY` está configurada. |
| AC03 | Mitigado | La configuración se lee de variables de entorno/.env con permisos del host; no se expone al cliente. |
| AC14 | Mitigado | Las excepciones se manejan en `exception_handlers.py` y no se devuelven trazas internas al cliente. |
| CR06 | Parcial | NATS, PostgreSQL y Neo4j viajan por la red compose; el aislamiento depende del host. No se publican puertos fuera de loopback en el despliegue por defecto. |

## API y superficie expuesta (API01, DO*)

| Amenaza | Estado | Mitigación / residual |
|---|---|---|
| API01 | Mitigado | `/docs`, `/redoc` y `/openapi.json` existen solo en desarrollo; en producción se desactivan o se protegen en el proxy. |
| DO01–DO05 | Parcial | Rate limiting por IP y timeouts de workers; no hay protección anti-DoS a nivel de red. El despliegue es single-host y no público por defecto. |

## LLM y cadena de proveedores (LLM01–LLM09)

| Amenaza | Estado | Mitigación / residual |
|---|---|---|
| LLM01, LLM02 | Parcial | Los prompts incluyen backlog, procedimientos y memoria; el contenido del repositorio es no confiable. El proxy audita y limita tokens, pero no hay una compuerta de aprobación por cada prompt. |
| LLM03, LLM08 | Parcial | El código y los datos del proyecto se envían a Gemini/DeepSeek. El despliegue debe usar claves propias y políticas de retención del proveedor; no se envían secretos al prompt. |
| LLM04 | No aplicable | No se entrenan modelos; se usan APIs externas. |
| LLM07 | Parcial | Depende del proveedor; la salida se valida antes de aplicarla al workspace. |
| LLM09 | Mitigado | El proxy y el cliente validan configuración y modelo; no se permite una URL arbitraria de proveedor desde el usuario. |

## Amenazas descartadas

Buffer overflow de C/C++ (INP01, INP02, INP05, INP07, INP12, INP24), SSI
(INP03), HTTP request splitting (INP04), LDAP (INP09), PHP RFI (INP16), SOAP
(INP06, INP34), XML (AC04, AC10, DO05, INP22), iFrame overlay (INP20),
hardware (HA*). No hay componentes de esos tipos en La Fabrique.
